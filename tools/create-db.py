#!/usr/bin/env python3.11
"""Crée et met à jour la base de données DuckDB du contrôleur local.

Le modèle de données est lu dans datamodel/ : un fichier JSON par table, dont le
nom est celui de la table. La base build/db/local-controller.duckdb est créée si
elle n'existe pas ; sinon elle est comparée au modèle et mise à jour.

* Les ajouts (table, colonne acceptant NULL, index), les valeurs par défaut et
  les commentaires sont appliqués directement.
* Ce qui peut perdre des données ou échouer sur les données présentes (colonne
  ou table en trop, changement de type, de clé primaire, passage à NOT NULL)
  n'est appliqué qu'avec l'option --force.

Toutes les modifications d'une exécution sont faites dans une seule transaction.
Seule la structure est gérée : l'outil ne lit ni n'écrit aucune donnée métier et
ne se connecte jamais à la base Oracle de RESASAT.

Le module duckdb est nécessaire. Voir README.d/build.md pour les prérequis et
l'utilisation, README.d/database.md pour le format des fichiers JSON.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATAMODEL = ROOT / "datamodel"
DEFAULT_DATABASE = ROOT / "build" / "db" / "local-controller.duckdb"

# Types du modèle de données et type DuckDB correspondant
SQL_TYPES = {"int": "INTEGER", "bigint": "BIGINT", "double": "DOUBLE", "varchar": "VARCHAR"}
INTEGER_TYPES = ("int", "bigint")

# Les identifiants du modèle sont en minuscules, sans caractère à protéger.
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
# Nom provisoire d'une table en cours de reconstruction
REBUILD_SUFFIX = "__new"

TABLE_KEYS = {"name", "comment", "columns", "primary_key", "indexes"}
COLUMN_KEYS = {"name", "comment", "type", "length", "nullable", "default", "auto_increment",
               # Champs documentaires, non appliqués à la base
               "references", "values"}
INDEX_KEYS = {"name", "unique", "columns"}


class CreateError(Exception):
    """Erreur présentée à l'utilisateur sans trace d'exécution."""


# --------------------------------------------------------------------------
# Lecture et validation du modèle de données
# --------------------------------------------------------------------------

def is_identifier(value):
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def is_integer(value):
    """Entier JSON ; True et False n'en sont pas."""
    return isinstance(value, int) and not isinstance(value, bool)


def default_matches(kind, value):
    """Vrai si la valeur par défaut est du type de la colonne."""
    if kind in INTEGER_TYPES:
        return is_integer(value)
    if kind == "double":
        return is_integer(value) or isinstance(value, float)
    return isinstance(value, str)


def validate_column(column, position, names):
    """Erreurs d'une colonne ; son nom est ajouté à names."""
    if not isinstance(column, dict):
        return [f"colonne n° {position} : un objet est attendu"]
    name = column.get("name")
    if not is_identifier(name):
        return [f"colonne n° {position} : « name » doit être un identifiant en minuscules "
                f"(lettres, chiffres, _), trouvé {name!r}"]
    errors = []
    if name in names:
        errors.append("colonne déclarée deux fois")
    names.append(name)
    for key in sorted(set(column) - COLUMN_KEYS):
        errors.append(f"champ inconnu « {key} »")
    if not isinstance(column.get("comment", ""), str):
        errors.append("« comment » doit être une chaîne")

    kind = column.get("type")
    if kind not in SQL_TYPES:
        errors.append(f"type {kind!r} inconnu (types acceptés : {', '.join(SQL_TYPES)})")
    elif kind == "varchar":
        if not is_integer(column.get("length")) or column["length"] < 1:
            errors.append("« length » (largeur, entier positif) est obligatoire pour un varchar")
    elif "length" in column:
        errors.append(f"« length » ne s'applique pas au type {kind}")

    if not isinstance(column.get("nullable"), bool):
        errors.append("« nullable » (true ou false) est obligatoire")
    auto_increment = column.get("auto_increment", False)
    if not isinstance(auto_increment, bool):
        errors.append("« auto_increment » doit valoir true ou false")
    default = column.get("default")
    if default is not None and kind in SQL_TYPES and not default_matches(kind, default):
        errors.append(f"la valeur par défaut {default!r} n'est pas du type {kind}")
    if auto_increment is True:
        if kind in SQL_TYPES and kind not in INTEGER_TYPES:
            errors.append("« auto_increment » demande un type entier (int ou bigint)")
        if default is not None:
            errors.append("« auto_increment » et « default » sont incompatibles")
    return [f"colonne {name} : {error}" for error in errors]


def validate_table(table, stem):
    """Liste des erreurs du contenu d'un fichier <stem>.json."""
    if not isinstance(table, dict):
        return ["un objet JSON est attendu"]
    errors = []
    if not is_identifier(stem) or stem.endswith(REBUILD_SUFFIX):
        errors.append("le nom du fichier doit être un nom de table en minuscules "
                      f"(lettres, chiffres, _) qui ne finit pas par {REBUILD_SUFFIX}")
    if table.get("name") != stem:
        errors.append(f"« name » vaut {table.get('name')!r} : il doit être le nom du fichier, "
                      f"« {stem} »")
    for key in sorted(set(table) - TABLE_KEYS):
        errors.append(f"champ inconnu « {key} »")
    if not isinstance(table.get("comment", ""), str):
        errors.append("« comment » doit être une chaîne")

    names = []
    columns = table.get("columns")
    if not isinstance(columns, list) or not columns:
        errors.append("« columns » doit être une liste non vide")
        columns = []
    for position, column in enumerate(columns, start=1):
        errors += validate_column(column, position, names)
    nullable = {column["name"] for column in columns
                if isinstance(column, dict) and column.get("nullable") is True
                and isinstance(column.get("name"), str)}

    primary_key = table.get("primary_key")
    if not isinstance(primary_key, list) or not all(isinstance(c, str) for c in primary_key):
        errors.append("« primary_key » doit être une liste de noms de colonnes (vide si la "
                      "table n'a pas de clé primaire)")
    else:
        if len(set(primary_key)) != len(primary_key):
            errors.append("clé primaire : colonne citée deux fois")
        for column in primary_key:
            if column not in names:
                errors.append(f"clé primaire : colonne {column} inconnue")
            elif column in nullable:
                errors.append(f"clé primaire : la colonne {column} doit avoir "
                              "« nullable » à false")

    indexes = table.get("indexes")
    if not isinstance(indexes, list):
        errors.append("« indexes » doit être une liste (vide si la table n'a pas d'index)")
        indexes = []
    for position, index in enumerate(indexes, start=1):
        if not isinstance(index, dict) or not is_identifier(index.get("name")):
            errors.append(f"index n° {position} : « name » doit être un identifiant en "
                          "minuscules (lettres, chiffres, _)")
            continue
        prefix = f"index {index['name']} : "
        for key in sorted(set(index) - INDEX_KEYS):
            errors.append(prefix + f"champ inconnu « {key} »")
        if not isinstance(index.get("unique"), bool):
            errors.append(prefix + "« unique » (true ou false) est obligatoire")
        index_columns = index.get("columns")
        if (not isinstance(index_columns, list) or not index_columns
                or not all(isinstance(c, str) for c in index_columns)):
            errors.append(prefix + "« columns » doit être une liste non vide de noms de colonnes")
            continue
        if len(set(index_columns)) != len(index_columns):
            errors.append(prefix + "colonne citée deux fois")
        for column in index_columns:
            if column not in names:
                errors.append(prefix + f"colonne {column} inconnue")
    return errors


def normalize(table):
    """Complète les champs facultatifs d'une table valide."""
    return {
        "name": table["name"],
        "comment": table.get("comment", ""),
        "columns": [{"name": column["name"],
                     "comment": column.get("comment", ""),
                     "type": column["type"],
                     "length": column.get("length"),
                     "nullable": column["nullable"],
                     "default": column.get("default"),
                     "auto_increment": column.get("auto_increment", False)}
                    for column in table["columns"]],
        "primary_key": list(table["primary_key"]),
        "indexes": [{"name": index["name"], "unique": index["unique"],
                     "columns": list(index["columns"])} for index in table["indexes"]],
    }


def load_datamodel(directory):
    """Lit tous les fichiers JSON du répertoire ; retourne les tables par nom.

    Toutes les erreurs sont relevées avant d'échouer : la base n'est pas
    ouverte tant que le modèle n'est pas entièrement valide."""
    if not directory.is_dir():
        raise CreateError(f"répertoire du modèle de données introuvable : {directory}")
    files = sorted(directory.glob("*.json"))
    if not files:
        raise CreateError(f"aucun fichier .json dans {directory}")
    errors = []
    model = {}
    for path in files:
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            errors.append(f"{path.name} : fichier illisible ({error})")
            continue
        table_errors = validate_table(content, path.stem)
        errors += [f"{path.name} : {error}" for error in table_errors]
        if not table_errors:
            model[path.stem] = normalize(content)

    # Dans DuckDB, index et séquences partagent l'espace de noms des tables.
    owners = {name: f"table {name}" for name in model}
    for table in model.values():
        objects = [(index["name"], f"index de {table['name']}") for index in table["indexes"]]
        objects += [(sequence_name(table, column), f"séquence de {table['name']}")
                    for column in table["columns"] if column["auto_increment"]]
        for name, owner in objects:
            if name in owners:
                errors.append(f"{table['name']}.json : le nom {name} ({owner}) est déjà pris "
                              f"({owners[name]})")
            owners[name] = owner
    if errors:
        raise CreateError("modèle de données invalide :\n" + "\n".join(f"  {e}" for e in errors))
    return model


# --------------------------------------------------------------------------
# Instructions SQL
# --------------------------------------------------------------------------

def quote(identifier):
    return f'"{identifier}"'


def literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return repr(value)


def sequence_name(table, column):
    """Séquence d'une colonne auto-incrémentée. Le nom est celui de RESASAT
    quand la colonne porte le préfixe de sa table : resasat_r2s_id_seq."""
    name = column["name"]
    if not name.startswith(table["name"] + "_"):
        name = f"{table['name']}_{name}"
    return name + "_seq"


def sql_type(column):
    """Type DuckDB tel que le catalogue le rend : la largeur n'y figure pas."""
    return SQL_TYPES[column["type"]]


def declared_type(column):
    """Type écrit dans le DDL. DuckDB accepte la largeur d'un VARCHAR, sans
    l'appliquer ni la conserver."""
    if column["type"] == "varchar":
        return f"VARCHAR({column['length']})"
    return sql_type(column)


def default_sql(table, column):
    """Expression de la valeur par défaut, None s'il n'y en a pas."""
    if column["auto_increment"]:
        return f"nextval('{sequence_name(table, column)}')"
    if column["default"] is not None:
        return literal(column["default"])
    return None


def column_sql(table, column):
    parts = [quote(column["name"]), declared_type(column)]
    default = default_sql(table, column)
    if default is not None:
        parts.append(f"DEFAULT {default}")
    if not column["nullable"]:
        parts.append("NOT NULL")
    return " ".join(parts)


def create_table_sql(table, name=None):
    lines = [column_sql(table, column) for column in table["columns"]]
    if table["primary_key"]:
        lines.append("PRIMARY KEY (" + ", ".join(map(quote, table["primary_key"])) + ")")
    return f"CREATE TABLE {quote(name or table['name'])} (\n  " + ",\n  ".join(lines) + "\n)"


def create_index_sql(table, index):
    unique = "UNIQUE " if index["unique"] else ""
    return (f"CREATE {unique}INDEX {quote(index['name'])} ON {quote(table['name'])} ("
            + ", ".join(map(quote, index["columns"])) + ")")


def table_comment_sql(table):
    return f"COMMENT ON TABLE {quote(table['name'])} IS {literal(table['comment'] or None)}"


def column_comment_sql(table, column):
    return (f"COMMENT ON COLUMN {quote(table['name'])}.{quote(column['name'])} IS "
            f"{literal(column['comment'] or None)}")


def comment_statements(table):
    """Commentaires non vides d'une table qui vient d'être créée."""
    statements = [table_comment_sql(table)] if table["comment"] else []
    statements += [column_comment_sql(table, column)
                   for column in table["columns"] if column["comment"]]
    return statements


# --------------------------------------------------------------------------
# État de la base
# --------------------------------------------------------------------------

CATALOG_FILTER = ("database_name = current_database() AND schema_name = 'main' "
                  "AND NOT internal")


@dataclass
class Database:
    """Structure lue dans le catalogue de DuckDB."""
    tables: dict
    sequences: set

    @classmethod
    def empty(cls):
        return cls({}, set())

    @classmethod
    def read(cls, connection):
        tables = {}
        for name, comment in connection.execute(
                f"SELECT table_name, comment FROM duckdb_tables() WHERE {CATALOG_FILTER} "
                "AND NOT temporary ORDER BY table_name").fetchall():
            tables[name] = {"comment": comment or "", "columns": {}, "primary_key": [],
                            "indexes": {}}
        for table, name, data_type, nullable, default, comment in connection.execute(
                "SELECT table_name, column_name, data_type, is_nullable, column_default, comment "
                f"FROM duckdb_columns() WHERE {CATALOG_FILTER} "
                "ORDER BY table_name, column_index").fetchall():
            if table in tables:
                tables[table]["columns"][name] = {
                    "type": data_type, "nullable": nullable, "comment": comment or "",
                    "default": None if default is None or default.upper() == "NULL" else default}
        for table, columns in connection.execute(
                "SELECT table_name, constraint_column_names FROM duckdb_constraints() "
                f"WHERE database_name = current_database() AND schema_name = 'main' "
                "AND constraint_type = 'PRIMARY KEY'").fetchall():
            if table in tables:
                tables[table]["primary_key"] = list(columns)
        # « expressions » protège certains noms par des guillemets : ['"name"', n].
        # Un index sur une expression donne une liste différente de celle du
        # modèle : il sera remplacé.
        for name, table, unique, expressions in connection.execute(
                "SELECT index_name, table_name, is_unique, expressions FROM duckdb_indexes() "
                "WHERE database_name = current_database() AND schema_name = 'main' "
                "AND NOT is_primary").fetchall():
            if table in tables:
                tables[table]["indexes"][name] = {
                    "unique": unique, "columns": re.findall(r"[A-Za-z_][A-Za-z0-9_]*",
                                                            expressions or "")}
        sequences = {name for (name,) in connection.execute(
            "SELECT sequence_name FROM duckdb_sequences() "
            "WHERE database_name = current_database() AND schema_name = 'main' "
            "AND NOT temporary").fetchall()}
        return cls(tables, sequences)


# --------------------------------------------------------------------------
# Écarts entre le modèle et la base
# --------------------------------------------------------------------------

@dataclass
class Change:
    """Modification d'une table, avec les instructions qui la réalisent.

    needs_force : la modification peut perdre des données ou échouer sur les
    données présentes ; elle n'est faite qu'avec --force."""
    table: str
    description: str
    statements: list
    needs_force: bool = False


def same_default(actual, expected):
    """Compare la valeur par défaut du catalogue à celle du modèle."""
    if actual is None or expected is None:
        return actual is None and expected is None
    if actual == expected:
        return True
    try:  # 1.0 et 1, (-1) et -1
        return float(actual.strip("() ")) == float(expected)
    except ValueError:
        return False


class Planner:
    """Calcule les modifications qui amènent la base au modèle."""

    def __init__(self, model, database, connection=None):
        self.model = model
        self.database = database
        self.connection = connection
        # Séquences présentes, ou dont la création est déjà prévue
        self.sequences = set(database.sequences)

    def plan(self):
        """Retourne les modifications des tables, puis les suppressions de
        séquences devenues inutiles."""
        changes = []
        for name, table in self.model.items():
            changes += self.table_changes(table, self.database.tables.get(name))
        for name in self.database.tables:
            if name not in self.model:
                changes.append(Change(name, "table supprimée (absente du modèle de données)",
                                      [f"DROP TABLE IF EXISTS {quote(name)}"], needs_force=True))
        expected = {sequence_name(table, column) for table in self.model.values()
                    for column in table["columns"] if column["auto_increment"]}
        cleanup = [Change(name, "séquence supprimée (inutilisée)",
                          [f"DROP SEQUENCE IF EXISTS {quote(name)}"])
                   for name in sorted(self.database.sequences - expected)]
        return changes, cleanup

    def sequence_statements(self, table, column, current):
        """Création de la séquence d'une colonne auto-incrémentée, si elle
        manque. Elle démarre après le plus grand identifiant présent."""
        name = sequence_name(table, column)
        if name in self.sequences:
            return []
        self.sequences.add(name)
        start = 1
        if (self.connection is not None and current is not None
                and column["name"] in current["columns"]):
            highest = self.connection.execute(
                f"SELECT max(TRY_CAST({quote(column['name'])} AS BIGINT)) "
                f"FROM {quote(table['name'])}").fetchone()[0]
            start = max(1, (highest or 0) + 1)
        return [f"CREATE SEQUENCE {quote(name)} START {start}"]

    def table_changes(self, table, current):
        name = table["name"]
        if current is None:
            statements = []
            for column in table["columns"]:
                if column["auto_increment"]:
                    statements += self.sequence_statements(table, column, None)
            statements.append(create_table_sql(table))
            statements += [create_index_sql(table, index) for index in table["indexes"]]
            statements += comment_statements(table)
            return [Change(name, "table créée", statements)]

        reasons = self.rebuild_reasons(table, current)
        if reasons:
            description = "table reconstruite : " + " ; ".join(text for text, _ in reasons)
            return [Change(name, description, self.rebuild_statements(table, current),
                           needs_force=any(force for _, force in reasons))]
        return self.in_place_changes(table, current)

    @staticmethod
    def rebuild_reasons(table, current):
        """Écarts qu'ALTER TABLE ne sait pas traiter dans DuckDB dès que la
        table porte un index : couples (description, --force nécessaire)."""
        reasons = []
        names = {column["name"] for column in table["columns"]}
        for column in current["columns"]:
            if column not in names:
                reasons.append((f"colonne {column} en trop", True))
        for column in table["columns"]:
            existing = current["columns"].get(column["name"])
            if existing is None:
                if not column["nullable"]:
                    reasons.append((f"nouvelle colonne {column['name']} NOT NULL", True))
                continue
            if existing["type"] != sql_type(column):
                reasons.append((f"type de {column['name']} {existing['type']} → "
                                f"{sql_type(column)}", True))
            if existing["nullable"] and not column["nullable"]:
                reasons.append((f"{column['name']} devient NOT NULL", True))
            elif column["nullable"] and not existing["nullable"]:
                reasons.append((f"{column['name']} accepte NULL", False))
        if current["primary_key"] != table["primary_key"]:
            before = ", ".join(current["primary_key"]) or "aucune"
            after = ", ".join(table["primary_key"]) or "aucune"
            reasons.append((f"clé primaire ({before}) → ({after})", True))
        return reasons

    def rebuild_statements(self, table, current):
        """Nouvelle table, copie des colonnes communes, remplacement de
        l'ancienne. Les index sont créés après le changement de nom, que DuckDB
        refuse sur une table indexée."""
        name = table["name"]
        temporary = name + REBUILD_SUFFIX
        statements = []
        for column in table["columns"]:
            if column["auto_increment"]:
                statements += self.sequence_statements(table, column, current)
        statements.append(f"DROP TABLE IF EXISTS {quote(temporary)}")
        statements.append(create_table_sql(table, temporary))
        common = [column for column in table["columns"] if column["name"] in current["columns"]]
        if common:
            targets = ", ".join(quote(column["name"]) for column in common)
            sources = ", ".join(
                quote(column["name"])
                if current["columns"][column["name"]]["type"] == sql_type(column)
                else f"CAST({quote(column['name'])} AS {sql_type(column)})"
                for column in common)
            statements.append(f"INSERT INTO {quote(temporary)} ({targets}) "
                              f"SELECT {sources} FROM {quote(name)}")
        statements.append(f"DROP TABLE {quote(name)}")
        statements.append(f"ALTER TABLE {quote(temporary)} RENAME TO {quote(name)}")
        statements += [create_index_sql(table, index) for index in table["indexes"]]
        statements += comment_statements(table)
        return statements

    def in_place_changes(self, table, current):
        name = table["name"]
        changes = []
        if current["comment"] != table["comment"]:
            changes.append(Change(name, "commentaire de la table modifié",
                                  [table_comment_sql(table)]))
        for column in table["columns"]:
            existing = current["columns"].get(column["name"])
            default = default_sql(table, column)
            if existing is None:
                statements = (self.sequence_statements(table, column, current)
                              if column["auto_increment"] else [])
                statements.append(f"ALTER TABLE {quote(name)} ADD COLUMN "
                                  + column_sql(table, column))
                if column["comment"]:
                    statements.append(column_comment_sql(table, column))
                changes.append(Change(name, f"colonne {column['name']} ajoutée", statements))
                continue
            if not same_default(existing["default"], default):
                alter = f"ALTER TABLE {quote(name)} ALTER COLUMN {quote(column['name'])} "
                if default is None:
                    statements = [alter + "DROP DEFAULT"]
                else:
                    statements = (self.sequence_statements(table, column, current)
                                  if column["auto_increment"] else [])
                    statements.append(alter + f"SET DEFAULT {default}")
                changes.append(Change(
                    name, f"valeur par défaut de {column['name']} : "
                          f"{existing['default'] or 'aucune'} → {default or 'aucune'}",
                    statements))
            if existing["comment"] != column["comment"]:
                changes.append(Change(name, f"commentaire de {column['name']} modifié",
                                      [column_comment_sql(table, column)]))

        wanted = {index["name"]: index for index in table["indexes"]}
        for index_name, existing in current["indexes"].items():
            if index_name not in wanted:
                changes.append(Change(name, f"index {index_name} supprimé",
                                      [f"DROP INDEX {quote(index_name)}"]))
        for index in table["indexes"]:
            existing = current["indexes"].get(index["name"])
            if existing is None:
                changes.append(Change(name, f"index {index['name']} créé",
                                      [create_index_sql(table, index)]))
            elif (existing["unique"], existing["columns"]) != (index["unique"], index["columns"]):
                changes.append(Change(name, f"index {index['name']} recréé",
                                      [f"DROP INDEX {quote(index['name'])}",
                                       create_index_sql(table, index)]))
        return changes


def select_changes(changes, cleanup, force):
    """Sépare les modifications à faire de celles qui attendent --force.

    Une séquence inutilisée ne peut être supprimée tant qu'une table en attente
    s'en sert encore : le nettoyage attend que tout le reste soit appliqué."""
    applied = [change for change in changes if force or not change.needs_force]
    pending = [change for change in changes if not force and change.needs_force]
    if pending:
        return applied, pending
    return applied + cleanup, []


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------

def import_duckdb():
    try:
        import duckdb
    except ImportError:
        raise CreateError(
            "module duckdb introuvable. Installer l'environnement décrit dans "
            "README.d/build.md :\n"
            "  python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt\n"
            "puis lancer : .venv/bin/python tools/create-db.py") from None
    return duckdb


def execute(duckdb, connection, changes):
    """Exécute les modifications dans une seule transaction."""
    statement = "BEGIN"
    try:
        connection.execute(statement)
        for change in changes:
            for statement in change.statements:
                connection.execute(statement)
        connection.execute("COMMIT")
    except duckdb.Error as error:
        try:
            connection.execute("ROLLBACK")
        except duckdb.Error:
            pass
        raise CreateError("instruction refusée par DuckDB ; la transaction est annulée, "
                          f"la base n'est pas modifiée :\n{statement}\n{error}") from None


def synchronize(model, path, force=False, dry_run=False):
    """Met la base au niveau du modèle ; retourne les modifications faites (ou
    simulées) et celles qui attendent --force."""
    duckdb = import_duckdb()
    exists = path.is_file()
    connection = None
    try:
        if exists or not dry_run:
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
            connection = duckdb.connect(str(path), read_only=dry_run)
        database = Database.read(connection) if connection else Database.empty()
        applied, pending = select_changes(*Planner(model, database, connection).plan(), force)

        for change in applied:
            print(f"{change.table} : {change.description}")
            if dry_run:
                for statement in change.statements:
                    print("    " + statement.replace("\n", "\n    ") + ";")
        if applied and not dry_run:
            execute(duckdb, connection, applied)
            # Contrôle : une seconde comparaison ne doit plus rien trouver à faire.
            remaining, _ = select_changes(
                *Planner(model, Database.read(connection), connection).plan(), force)
            if remaining:
                raise CreateError(
                    "la base diffère encore du modèle après la mise à jour :\n"
                    + "\n".join(f"  {c.table} : {c.description}" for c in remaining))
        return applied, pending
    except duckdb.Error as error:
        raise CreateError(f"accès à la base {path} impossible :\n{error}") from None
    finally:
        if connection is not None:
            connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Crée ou met à jour la base de données DuckDB du contrôleur local "
                    "à partir du modèle de données (un fichier JSON par table).")
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE, metavar="FICHIER",
                        help="fichier de la base DuckDB "
                             "(défaut : build/db/local-controller.duckdb)")
    parser.add_argument("--datamodel", type=Path, default=DEFAULT_DATAMODEL,
                        metavar="RÉPERTOIRE",
                        help="répertoire des fichiers JSON (défaut : datamodel/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="afficher les instructions SQL sans modifier la base")
    parser.add_argument("--force", action="store_true",
                        help="appliquer aussi les modifications qui peuvent perdre des données : "
                             "colonne ou table en trop, changement de type, de clé primaire, "
                             "passage à NOT NULL")
    args = parser.parse_args(argv)

    try:
        model = load_datamodel(args.datamodel)
        applied, pending = synchronize(model, args.db, force=args.force, dry_run=args.dry_run)
    except CreateError as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 2

    if pending:
        print("Modifications non appliquées, à relancer avec --force "
              "(des données peuvent être perdues) :", file=sys.stderr)
        for change in pending:
            print(f"  {change.table} : {change.description}", file=sys.stderr)
    verb = "à faire" if args.dry_run else "appliquées"
    if applied:
        print(f"{len(model)} tables dans le modèle, {len(applied)} modifications {verb} "
              f"dans {args.db}")
    elif not pending:
        print(f"Base conforme au modèle de données ({len(model)} tables) : {args.db}")
    return 1 if pending else 0


if __name__ == "__main__":
    sys.exit(main())
