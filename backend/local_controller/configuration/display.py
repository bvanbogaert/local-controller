"""Libellés et valeurs présentés à l'utilisateur, en français.

Tout vient du modèle de données : « comment » pour les libellés, « values »
pour les énumérations, « format » pour oui/non et les dates, « references »
pour le nom des enregistrements liés.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from ..datamodel import primary_key
from .tables import EXCLUDED_TABLES, LINK_TABLES

EMPTY = "(vide)"
UNNAMED = "(sans nom)"
TIME_ZONE = ZoneInfo("Europe/Paris")
YES_NO = {0: "Non", 1: "Oui"}


def not_found(text):
    return f"introuvable ({text})"


def plain(value):
    """Valeur sans présentation particulière ; virgule décimale."""
    if isinstance(value, float):
        text = repr(value)
        return (text[:-2] if text.endswith(".0") else text).replace(".", ",")
    return str(value)


class Display:
    """Présente les enregistrements d'une comparaison.

    Le nom d'un enregistrement lié est cherché du côté demandé : « file » (le
    fichier, puis la base) pour une valeur importée, « database » pour une
    valeur actuelle."""

    def __init__(self, model, file, diffs, connection):
        self.model = model
        self.file = file
        self.diffs = diffs
        self.connection = connection
        self.names = {}    # table hors comparaison -> {identifiant: nom}

    def table_label(self, table):
        return self.model[table]["comment"] if table in self.model else table

    def column_label(self, table, column):
        return self.model[table]["columns"][column]["comment"] or column

    def name_column(self, table, preferred=None):
        """Colonne qui nomme un enregistrement de la table, None s'il n'y en a pas."""
        columns = self.model[table]["columns"]
        for candidate in (preferred, f"{table}_name"):
            if candidate in columns:
                return candidate
        return None

    def linked_name(self, reference, identifier, side):
        """Nom de l'enregistrement visé par une clé étrangère."""
        table = reference["table"]
        number = f"#{identifier}"
        if table not in self.model or table in EXCLUDED_TABLES:
            return number            # table non importée : seul l'identifiant est connu
        column = self.name_column(table, reference.get("label"))
        if column is None:
            return number
        sources = []
        if side == "file" and table in self.file.tables:
            sources.append(self.file.tables[table].rows)
        if table in self.diffs:
            sources.append(self.diffs[table].database)
        for rows in sources:
            if identifier in rows:
                name = rows[identifier].get(column)
                return number if name is None else str(name)
        if table not in self.diffs:  # table absente du fichier : la base seule
            if table not in self.names:
                key = primary_key(self.model[table])
                self.names[table] = dict(self.connection.execute(
                    f'SELECT "{key}", "{column}" FROM "{table}"').fetchall())
            if self.names[table].get(identifier) is not None:
                return str(self.names[table][identifier])
        return not_found(number)

    def value(self, table, column, value, side):
        """Valeur d'un champ telle qu'elle est présentée."""
        if value is None:
            return EMPTY
        description = self.model[table]["columns"][column]
        if "references" in description:
            return self.linked_name(description["references"], value, side)
        if "values" in description:
            label = description["values"].get(str(value))
            return not_found(plain(value)) if label is None else label
        if description.get("format") == "yes_no":
            return YES_NO.get(value, plain(value))
        if description.get("format") == "datetime":
            try:
                return datetime.fromtimestamp(value, TIME_ZONE).strftime("%d/%m/%Y %H:%M")
            except (OverflowError, OSError, ValueError):
                return plain(value)
        return plain(value)

    def record(self, table, identifier, side):
        diff = self.diffs[table]
        return diff.file[identifier] if side == "file" else diff.database[identifier]

    def record_label(self, table, identifier, side):
        """Nom qui désigne un enregistrement : son nom, ou pour un lien les
        noms des enregistrements reliés."""
        record = self.record(table, identifier, side)
        if table not in LINK_TABLES:
            column = self.name_column(table)
            name = record.get(column) if column is not None else None
            return UNNAMED if name is None else str(name)
        linked = [self.value(table, name, record[name], side)
                  for name, description in self.model[table]["columns"].items()
                  if "references" in description and record.get(name) is not None]
        return " → ".join(linked) if linked else UNNAMED

    def fields(self, table, identifier, side):
        """Champs renseignés d'un enregistrement ajouté ou supprimé."""
        key = primary_key(self.model[table])
        return [{"label": self.column_label(table, column),
                 "value": self.value(table, column, value, side)}
                for column, value in self.record(table, identifier, side).items()
                if column != key and value is not None]

    def change(self, table, identifier, column):
        """Valeurs actuelle et importée d'un champ modifié. Deux valeurs
        différentes qui se présentent de la même façon sont complétées par
        leur valeur brute."""
        diff = self.diffs[table]
        current, imported = diff.database[identifier][column], diff.file[identifier][column]
        old = self.value(table, column, current, "database")
        new = self.value(table, column, imported, "file")
        if old == new:
            old, new = (text if value is None else f"{text} ({plain(value)})"
                        for text, value in ((old, current), (new, imported)))
        return {"column": column, "label": self.column_label(table, column),
                "old": old, "new": new}
