"""Import de la configuration exportée par RESASAT.

Logique sans HTTP : lecture et validation du fichier, filtres, comparaison avec
la base, application des modifications choisies. Les règles sont décrites dans
README.d/configuration-import.md.

Les noms de tables et de colonnes placés dans les requêtes SQL viennent toujours
du modèle de données, jamais du fichier ni de la sélection reçue.
"""

import json
import re
from dataclasses import dataclass, field

import duckdb

from ..datamodel import primary_key
from .tables import EXCLUDED_TABLES, IMPORTED_TABLES, LINK_TABLES

FILE_FORMAT = "resasat-configuration"
FILE_VERSION = 1
COLUMN_NAME = re.compile(r"[a-z][a-z0-9_]*")

PERIODS = ("active", "all")      # « Actifs et futurs », « Tout »
ORIGINS = ("resasat", "all")     # « RESASAT seul », « Tout »
# Valeur de <table>_is_foreign d'un enregistrement propre à RESASAT. NULL lui
# est assimilé, comme dans RESASAT (« is null or = 0 »).
ORIGIN_RESASAT = 0


class ConfigurationError(Exception):
    """Erreur présentée à l'utilisateur."""


# --------------------------------------------------------------------------
# Lecture du fichier
# --------------------------------------------------------------------------

@dataclass
class FileTable:
    columns: list                     # colonnes du fichier connues du modèle
    ignored_columns: list             # colonnes du fichier inconnues du modèle
    rows: dict                        # identifiant -> {colonne: valeur typée}
    invalid: dict = field(default_factory=dict)   # identifiant -> motif


@dataclass
class ConfigurationFile:
    date: int | None                  # date de l'export (Unix)
    tables: dict                      # table importée -> FileTable
    ignored_tables: list              # (table, motif)


def convert(value, column):
    """Valeur du fichier convertie au type de la colonne.

    RESASAT exporte des chaînes ; une chaîne vide vaut NULL, comme dans Oracle.
    Lève ValueError si la valeur n'est pas du type attendu."""
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        raise ValueError("valeur structurée")
    if isinstance(value, bool):
        value = int(value)
    text = str(value).strip() if column["type"] != "varchar" else str(value)
    if text == "":
        return None
    if column["type"] in ("int", "bigint"):
        try:
            return int(text)
        except ValueError:
            number = float(text)          # « 5.0 » est un entier, « 5.5 » non
            if not number.is_integer():
                raise ValueError("entier attendu") from None
            return int(number)
    if column["type"] == "double":
        number = float(text)
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError("nombre attendu")
        return number
    return text


def parse_file(content, model):
    """Lit et valide le fichier ; lève ConfigurationError s'il n'est pas un
    export de configuration de RESASAT."""
    try:
        data = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        raise ConfigurationError("le fichier n'est pas un fichier JSON") from None
    if (not isinstance(data, dict) or data.get("format") != FILE_FORMAT
            or not isinstance(data.get("tables"), dict)):
        raise ConfigurationError("le fichier n'est pas un export de configuration de RESASAT")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ConfigurationError("le fichier n'indique pas sa version")
    if version > FILE_VERSION:
        raise ConfigurationError("le fichier vient d'une version plus récente de RESASAT "
                                 f"(version {version}, version {FILE_VERSION} attendue)")
    date = data.get("date")

    def invalid(table, reason):
        return ConfigurationError(f"fichier invalide, table {table} : {reason}")

    tables = {}
    for name in IMPORTED_TABLES:
        entry = data["tables"].get(name)
        if entry is None:
            continue
        table = model[name]
        key = primary_key(table)
        if (not isinstance(entry, dict) or not isinstance(entry.get("columns"), list)
                or not isinstance(entry.get("rows"), list)):
            raise invalid(name, "« columns » et « rows » sont attendus")
        names = entry["columns"]
        if (not all(isinstance(c, str) and COLUMN_NAME.fullmatch(c) for c in names)
                or len(set(names)) != len(names)):
            raise invalid(name, "nom de colonne incorrect")
        if key not in names:
            raise invalid(name, f"la colonne {key} est absente")

        known = [c for c in names if c in table["columns"]]
        file_table = FileTable(known, [c for c in names if c not in table["columns"]], {})
        for row in entry["rows"]:
            if not isinstance(row, list) or len(row) != len(names):
                raise invalid(name, "une ligne n'a pas le nombre de valeurs attendu")
            raw = dict(zip(names, row))
            try:
                identifier = convert(raw[key], table["columns"][key])
            except ValueError:
                identifier = None
            if identifier is None:
                raise invalid(name, f"identifiant incorrect : {raw[key]!r}")
            if identifier in file_table.rows or identifier in file_table.invalid:
                raise invalid(name, f"identifiant {identifier} présent deux fois")
            record = {}
            try:
                for column in known:
                    current = column
                    record[column] = convert(raw[column], table["columns"][column])
            except ValueError:
                file_table.invalid[identifier] = (
                    f"valeur incorrecte pour {current} : {str(raw[current])[:40]!r}")
                continue
            file_table.rows[identifier] = record
        tables[name] = file_table

    ignored = [(name, EXCLUDED_TABLES.get(name, "table inconnue"))
               for name in data["tables"] if name not in IMPORTED_TABLES]
    return ConfigurationFile(date if isinstance(date, int) else None, tables, ignored)


# --------------------------------------------------------------------------
# Filtres
# --------------------------------------------------------------------------

def is_kept(table, record, period, origin, reference_time):
    """Vrai si l'enregistrement passe les deux filtres."""
    if period == "active":
        end = record.get(f"{table}_end")
        if end is not None and end < reference_time:
            return False
    if origin == "resasat":
        foreign = record.get(f"{table}_is_foreign")
        if foreign is not None and foreign != ORIGIN_RESASAT:
            return False
    return True


def references_of(table, model):
    """Colonnes de la table qui visent une table importée : (colonne, table visée)."""
    return [(name, column["references"]["table"])
            for name, column in model[table]["columns"].items()
            if column.get("references", {}).get("table") in IMPORTED_TABLES]


def select_records(file, model, period, origin, reference_time):
    """Identifiants retenus par table, après filtres.

    Un enregistrement écarté mais référencé par un enregistrement retenu est
    retenu aussi : aucune clé étrangère ne vise un enregistrement absent. Un
    lien n'est retenu que si les enregistrements qu'il relie le sont."""
    entities = [name for name in file.tables if name not in LINK_TABLES]
    retained = {name: {identifier for identifier, record in file.tables[name].rows.items()
                       if is_kept(name, record, period, origin, reference_time)}
                for name in entities}

    pending = [(name, identifier) for name in entities for identifier in retained[name]]
    while pending:
        name, identifier = pending.pop()
        record = file.tables[name].rows[identifier]
        for column, target in references_of(name, model):
            value = record.get(column)
            if (target in retained and value in file.tables[target].rows
                    and value not in retained[target]):
                retained[target].add(value)
                pending.append((target, value))

    for name in file.tables:
        if name not in LINK_TABLES:
            continue
        links = references_of(name, model)
        retained[name] = {
            identifier for identifier, record in file.tables[name].rows.items()
            if all(record.get(column) is None or target not in retained
                   or record[column] in retained[target] for column, target in links)}
    return retained


# --------------------------------------------------------------------------
# Comparaison
# --------------------------------------------------------------------------

@dataclass
class TableDiff:
    columns: list          # colonnes comparées
    file: dict             # enregistrements retenus du fichier
    database: dict         # enregistrements de la base
    discarded: int         # enregistrements du fichier écartés par les filtres
    insert: list = field(default_factory=list)   # identifiants à ajouter
    delete: list = field(default_factory=list)   # identifiants à supprimer
    update: dict = field(default_factory=dict)   # identifiant -> colonnes modifiées


def same_value(first, second):
    """Égalité typée : 12700.30 et 12700.3 sont égaux, 1 et « 1 » ne le sont pas."""
    if first is None or second is None:
        return first is None and second is None
    if isinstance(first, str) or isinstance(second, str):
        return first == second
    return float(first) == float(second)


def read_table(connection, table, columns):
    """Enregistrements d'une table de la base : identifiant -> {colonne: valeur}."""
    key = primary_key(table)
    names = ", ".join(f'"{column}"' for column in columns)
    rows = connection.execute(f'SELECT {names} FROM "{table["name"]}" ORDER BY "{key}"').fetchall()
    position = columns.index(key)
    return {row[position]: dict(zip(columns, row)) for row in rows}


def compare(file, model, connection, period, origin, reference_time):
    """Compare le fichier filtré à la base : TableDiff par table du fichier."""
    retained = select_records(file, model, period, origin, reference_time)
    diffs = {}
    for name in IMPORTED_TABLES:
        if name not in file.tables:
            continue
        table = model[name]
        key = primary_key(table)
        file_table = file.tables[name]
        diff = TableDiff(
            columns=file_table.columns,
            file={i: file_table.rows[i] for i in sorted(retained[name])},
            database=read_table(connection, table, list(table["columns"])),
            discarded=len(file_table.rows) - len(retained[name]))
        for identifier, record in diff.file.items():
            current = diff.database.get(identifier)
            if current is None:
                diff.insert.append(identifier)
                continue
            changed = [column for column in diff.columns
                       if column != key and not same_value(record[column], current[column])]
            if changed:
                diff.update[identifier] = changed
        # Un enregistrement illisible du fichier n'est ni importé ni supprimé.
        diff.delete = [identifier for identifier in diff.database
                       if identifier not in diff.file and identifier not in file_table.invalid]
        diffs[name] = diff
    return diffs


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------

def decode_selection(selection, diffs):
    """Traduit les clés reçues (« table|i|id », « table|d|id »,
    « table|u|id|colonne ») en modifications. Une clé qui ne correspond pas à
    un écart de la comparaison est comptée dans le troisième résultat et
    ignorée."""
    selected = {name: {"insert": [], "delete": [], "update": {}} for name in diffs}
    ignored = 0
    seen = set()
    for key in selection:
        parts = key.split("|") if isinstance(key, str) else []
        diff = diffs.get(parts[0]) if len(parts) in (3, 4) else None
        try:
            identifier = int(parts[2])
        except (IndexError, ValueError):
            diff = None
        if diff is None or key in seen:
            ignored += 1
            continue
        seen.add(key)
        chosen = selected[parts[0]]
        if parts[1] == "i" and len(parts) == 3 and identifier in diff.insert:
            chosen["insert"].append(identifier)
        elif parts[1] == "d" and len(parts) == 3 and identifier in diff.delete:
            chosen["delete"].append(identifier)
        elif parts[1] == "u" and len(parts) == 4 and parts[3] in diff.update.get(identifier, ()):
            chosen["update"].setdefault(identifier, []).append(parts[3])
        else:
            ignored += 1
    return selected, ignored


def advance_sequence(connection, table):
    """Avance la séquence de la clé primaire au-delà du plus grand identifiant,
    pour que le prochain enregistrement créé localement ne le reprenne pas.
    DuckDB n'a pas d'ALTER SEQUENCE ... RESTART : nextval est appelé en série."""
    key = table["columns"][primary_key(table)]
    if not key.get("auto_increment"):
        return
    row = connection.execute(
        "SELECT sequence_name, start_value, last_value FROM duckdb_sequences() "
        "WHERE sequence_name IN (?, ?)",
        [key["name"] + "_seq", f"{table['name']}_{key['name']}_seq"]).fetchone()
    if row is None:
        return
    sequence, start, last = row
    highest = connection.execute(
        f'SELECT max("{key["name"]}") FROM "{table["name"]}"').fetchone()[0]
    gap = (highest or 0) - (last if last is not None else start - 1)
    if gap > 0:
        connection.execute(f"SELECT max(nextval('{sequence}')) FROM range(?)", [gap])


def apply(selection, diffs, model, connection, describe):
    """Applique les modifications choisies dans une seule transaction.

    Les valeurs viennent des enregistrements du fichier (diffs) ; « selection »
    ne fait que désigner les écarts à appliquer. describe(table, identifiant,
    côté) nomme un enregistrement dans un message d'erreur.
    Retourne le nombre de modifications par table et le nombre de clés ignorées."""
    selected, ignored = decode_selection(selection, diffs)
    report = {}

    def run(name, action, identifier, side, statement, parameters):
        try:
            connection.execute(statement, parameters)
        except duckdb.Error as error:
            raise ConfigurationError(
                f"{action} refusé pour {describe(name, identifier, side)} : {error}") from None
        report.setdefault(name, {"insert": 0, "update": 0, "delete": 0})
        report[name][{"ajout": "insert", "modification": "update",
                      "suppression": "delete"}[action]] += 1

    connection.execute("BEGIN")
    try:
        # Ajouts et modifications : les tables référencées d'abord
        for name, diff in diffs.items():
            table, key = model[name], primary_key(model[name])
            for identifier in selected[name]["insert"]:
                record = {column: value for column, value in diff.file[identifier].items()
                          if value is not None}
                names = ", ".join(f'"{column}"' for column in record)
                marks = ", ".join("?" for _ in record)
                run(name, "ajout", identifier, "file",
                    f'INSERT INTO "{name}" ({names}) VALUES ({marks})', list(record.values()))
            for identifier, columns in selected[name]["update"].items():
                assignments = ", ".join(f'"{column}" = ?' for column in columns)
                run(name, "modification", identifier, "database",
                    f'UPDATE "{name}" SET {assignments} WHERE "{key}" = ?',
                    [diff.file[identifier][column] for column in columns] + [identifier])
            if selected[name]["insert"]:
                advance_sequence(connection, table)
        # Suppressions : les tables qui référencent d'abord
        for name in reversed(list(diffs)):
            key = primary_key(model[name])
            for identifier in selected[name]["delete"]:
                run(name, "suppression", identifier, "database",
                    f'DELETE FROM "{name}" WHERE "{key}" = ?', [identifier])
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    return report, ignored
