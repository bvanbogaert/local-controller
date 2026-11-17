"""Routes de l'import de la configuration (README.d/backend.md)."""

import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..database import connect
from ..datamodel import load_datamodel
from ..settings import get_settings
from . import importer, storage
from .display import Display
from .tables import IMPORTED_TABLES

MAX_FILE_SIZE = 64 * 1024 * 1024

router = APIRouter(prefix="/api/configuration/import", tags=["configuration"])


class Selection(BaseModel):
    selection: list[str]


def comparison(token, meta, file, diffs, display):
    """Comparaison présentée à l'utilisateur. Chaque case à cocher porte une
    clé : « table|i|id », « table|d|id » ou « table|u|id|colonne »."""
    tables = []
    for name in IMPORTED_TABLES:
        diff = diffs.get(name)
        entry = {"name": name, "label": display.table_label(name), "in_file": diff is not None,
                 "ignored_columns": [], "discarded": 0, "invalid": [],
                 "inserts": [], "updates": [], "deletes": []}
        if diff is not None:
            entry["ignored_columns"] = file.tables[name].ignored_columns
            entry["discarded"] = diff.discarded
            entry["invalid"] = [{"id": identifier, "reason": reason}
                                for identifier, reason in file.tables[name].invalid.items()]
            for action, side, identifiers in (("inserts", "file", diff.insert),
                                              ("deletes", "database", diff.delete)):
                entry[action] = [{"key": f"{name}|{action[0]}|{identifier}", "id": identifier,
                                  "label": display.record_label(name, identifier, side),
                                  "fields": display.fields(name, identifier, side)}
                                 for identifier in identifiers]
            for identifier, columns in diff.update.items():
                fields = [display.change(name, identifier, column) for column in columns]
                for item in fields:
                    item["key"] = f"{name}|u|{identifier}|{item.pop('column')}"
                entry["updates"].append(
                    {"id": identifier, "fields": fields,
                     "label": display.record_label(name, identifier, "database")})
        tables.append(entry)
    return {"token": token, "period": meta["period"], "origin": meta["origin"],
            "reference_time": meta["reference_time"], "file_date": file.date,
            "tables": tables,
            "ignored_tables": [{"name": name, "label": display.table_label(name) or name,
                                "reason": reason} for name, reason in file.ignored_tables],
            "total": sum(len(t["inserts"]) + len(t["updates"]) + len(t["deletes"])
                         for t in tables)}


def prepare(content, meta, connection):
    """Relit le fichier et recalcule la comparaison avec la base."""
    model = load_datamodel(get_settings().datamodel)
    file = importer.parse_file(content, model)
    diffs = importer.compare(file, model, connection, meta["period"], meta["origin"],
                             meta["reference_time"])
    return model, file, diffs, Display(model, file, diffs, connection)


def pending(token):
    try:
        return storage.load(get_settings().import_dir, token)
    except storage.UnknownImport:
        raise HTTPException(404, "Le fichier importé n'est plus disponible. "
                                 "Veuillez recommencer.") from None


@router.post("")
def upload(file: UploadFile = File(...), period: str = Form("active"),
           origin: str = Form("resasat")):
    """Dépose un fichier de configuration et retourne la comparaison."""
    if period not in importer.PERIODS or origin not in importer.ORIGINS:
        raise HTTPException(422, "Filtre inconnu.")
    content = file.file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "Le fichier dépasse 64 Mo.")
    settings = get_settings()
    meta = {"period": period, "origin": origin, "reference_time": int(time.time())}
    connection = connect(settings.database)
    try:
        # Le fichier n'est gardé que s'il est valide.
        _, parsed, diffs, display = prepare(content, meta, connection)
        token = storage.save(settings.import_dir, content, meta)
        return comparison(token, meta, parsed, diffs, display)
    finally:
        connection.close()


@router.get("/{token}")
def compare(token: str):
    """Recalcule la comparaison de l'import en attente."""
    content, meta = pending(token)
    connection = connect(get_settings().database)
    try:
        _, parsed, diffs, display = prepare(content, meta, connection)
        return comparison(token, meta, parsed, diffs, display)
    finally:
        connection.close()


@router.post("/{token}/apply")
def apply(token: str, body: Selection):
    """Applique les modifications désignées par leurs clés. Les valeurs sont
    relues dans le fichier stocké : la requête n'en transporte aucune."""
    content, meta = pending(token)
    settings = get_settings()
    connection = connect(settings.database)
    try:
        model, _, diffs, display = prepare(content, meta, connection)

        def describe(table, identifier, side):
            return (f"{display.table_label(table)} « "
                    f"{display.record_label(table, identifier, side)} » (#{identifier})")

        try:
            report, ignored = importer.apply(body.selection, diffs, model, connection, describe)
        except importer.ConfigurationError as error:
            # Rien n'est appliqué ; le fichier reste en attente pour une nouvelle sélection.
            raise HTTPException(409, f"Import annulé, aucune modification n'est conservée. "
                                     f"{error}") from None
    finally:
        connection.close()
    storage.discard(settings.import_dir)
    return {"tables": [{"name": name, "label": display.table_label(name), **counts}
                       for name, counts in report.items()],
            "ignored": ignored}


@router.delete("/{token}", status_code=204)
def cancel(token: str):
    """Abandonne l'import en attente."""
    pending(token)
    storage.discard(get_settings().import_dir)
