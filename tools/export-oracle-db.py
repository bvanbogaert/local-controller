#!/usr/bin/env python3.11
"""Exporte le schéma de la base de données Oracle de RESASAT.

Seules les tables dont le nom commence par RESASAT_ sont exportées, dans l'un
des deux formats :

* markdown : un fichier .md par table, plus index.md, dans build/doc/resasat-db/ ;
* sql      : un fichier .sql par table (DDL Oracle 19c produit par DBMS_METADATA),
             plus _sequences.sql, dans build/sql/resasat-db/.

En format markdown, l'option --lang enrichit les commentaires avec le fichier
langue de kadlib (noms présentés aux utilisateurs, valeurs des énumérations,
clés étrangères). Le fichier est évalué par PHP.

La base est interrogée avec sqlplus : seule la bibliothèque standard de Python
est utilisée. Voir README.d/build.md pour les prérequis et l'utilisation.
"""

import argparse
import csv
import datetime
import getpass
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = {"markdown": ROOT / "build" / "doc" / "resasat-db",
                  "sql": ROOT / "build" / "sql" / "resasat-db"}
EXTENSION = {"markdown": ".md", "sql": ".sql"}
DEFAULT_ORACLE_HOME = "/opt/oracle/product/19c/dbhome_1"
DEFAULT_USER = "resaora"
DEFAULT_DSN = "resasat-rhel96:1521/PDB1"
PASSWORD_VARIABLE = "RESASAT_PASSWORD"
TIMEOUT_S = 300

SECTION_MARK = "@@@section "
DDL_MARK = "@@@ddl "

# Filtres SQL sur le préfixe des objets exportés
TABLE_FILTER = r"table_name LIKE 'RESASAT\_%' ESCAPE '\'"
SEQUENCE_FILTER = r"sequence_name LIKE 'RESASAT\_%' ESCAPE '\'"

SQL_HEADER = """\
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE
SET PAGESIZE 0 FEEDBACK OFF HEADING OFF VERIFY OFF ECHO OFF TAB OFF DEFINE OFF
SET LONG 2000000 LONGCHUNKSIZE 32767 LINESIZE 32767 TRIMOUT ON
"""

# Requêtes sur le dictionnaire, sorties en CSV. L'ordre des colonnes est celui
# attendu par Schema.__init__.
DICTIONARY_QUERIES = {
    "tables": f"""
SELECT t.table_name, c.comments
  FROM user_tables t
  LEFT JOIN user_tab_comments c ON c.table_name = t.table_name
 WHERE t.{TABLE_FILTER}
 ORDER BY t.table_name;""",
    "columns": f"""
SELECT c.table_name, c.column_name, c.data_type, c.data_length, c.data_precision,
       c.data_scale, c.char_length, c.char_used, c.nullable,
       (SELECT m.comments FROM user_col_comments m
         WHERE m.table_name = c.table_name AND m.column_name = c.column_name)
  FROM user_tab_columns c
 WHERE c.{TABLE_FILTER}
 ORDER BY c.table_name, c.column_id;""",
    # DATA_DEFAULT est de type LONG, que le mode CSV de sqlplus ne sait pas
    # protéger : il est converti en VARCHAR2 par un passage en XML.
    "defaults": f"""
SELECT x.table_name, x.column_name, x.data_default
  FROM XMLTABLE('/ROWSET/ROW' PASSING DBMS_XMLGEN.GETXMLTYPE(q'[
         SELECT table_name, column_name, data_default
           FROM user_tab_columns
          WHERE {TABLE_FILTER} AND default_length IS NOT NULL]')
       COLUMNS table_name VARCHAR2(128), column_name VARCHAR2(128),
               data_default VARCHAR2(4000)) x;""",
    # Toutes les contraintes du schéma : une clé étrangère peut viser, ou venir
    # d'une table qui n'a pas le préfixe RESASAT_.
    "constraints": """
SELECT constraint_name, table_name, constraint_type, status, r_owner,
       r_constraint_name, delete_rule, search_condition_vc
  FROM user_constraints
 WHERE constraint_type IN ('P', 'U', 'R', 'C')
 ORDER BY table_name, constraint_name;""",
    "constraint_columns": """
SELECT constraint_name, column_name
  FROM user_cons_columns
 ORDER BY constraint_name, position;""",
    "indexes": f"""
SELECT index_name, table_name, uniqueness, index_type
  FROM user_indexes
 WHERE {TABLE_FILTER} AND index_type <> 'LOB'
 ORDER BY table_name, index_name;""",
    "index_columns": f"""
SELECT index_name, column_name, descend
  FROM user_ind_columns
 WHERE {TABLE_FILTER}
 ORDER BY index_name, column_position;""",
    "triggers": f"""
SELECT trigger_name, table_name, trigger_type, triggering_event, status
  FROM user_triggers
 WHERE {TABLE_FILTER}
 ORDER BY table_name, trigger_name;""",
    "sequences": f"""
SELECT sequence_name, TO_CHAR(min_value), TO_CHAR(max_value), TO_CHAR(increment_by),
       cycle_flag, TO_CHAR(cache_size), TO_CHAR(last_number)
  FROM user_sequences
 WHERE {SEQUENCE_FILTER}
 ORDER BY sequence_name;""",
}

# DDL natif. Chaque ligne de résultat commence par un repère
# « @@@ddl TYPE TABLE NOM », suivi du texte produit par DBMS_METADATA.
DDL_QUERIES = f"""
SELECT '{DDL_MARK}TABLE ' || table_name || ' ' || table_name || CHR(10)
       || DBMS_METADATA.GET_DDL('TABLE', table_name)
  FROM user_tables
 WHERE {TABLE_FILTER}
 ORDER BY table_name;

SELECT '{DDL_MARK}INDEX ' || i.table_name || ' ' || i.index_name || CHR(10)
       || DBMS_METADATA.GET_DDL('INDEX', i.index_name)
  FROM user_indexes i
 WHERE i.{TABLE_FILTER} AND i.index_type <> 'LOB'
   AND NOT EXISTS (SELECT 1 FROM user_constraints c
                    WHERE c.index_name = i.index_name
                      AND c.constraint_type IN ('P', 'U'))
 ORDER BY i.table_name, i.index_name;

SELECT '{DDL_MARK}REF_CONSTRAINT ' || table_name || ' ' || constraint_name || CHR(10)
       || DBMS_METADATA.GET_DDL('REF_CONSTRAINT', constraint_name)
  FROM user_constraints
 WHERE {TABLE_FILTER} AND constraint_type = 'R'
 ORDER BY table_name, constraint_name;

SELECT '{DDL_MARK}TRIGGER ' || table_name || ' ' || trigger_name || CHR(10)
       || DBMS_METADATA.GET_DDL('TRIGGER', trigger_name)
  FROM user_triggers
 WHERE {TABLE_FILTER}
 ORDER BY table_name, trigger_name;

SELECT '{DDL_MARK}SEQUENCE - ' || sequence_name || CHR(10)
       || DBMS_METADATA.GET_DDL('SEQUENCE', sequence_name)
  FROM user_sequences
 WHERE {SEQUENCE_FILTER}
 ORDER BY sequence_name;
"""

# Au-delà de ce nombre de valeurs, une énumération quitte la cellule du tableau
# des colonnes pour une section à part.
ENUM_INLINE_MAX = 10

# Chargeur PHP du fichier langue de kadlib. Le fichier est du code PHP qui
# utilise les constantes de l'application : il est évalué plutôt qu'analysé.
# Les fichiers *defines.inc.php de l'application et des modules voisins sont
# chargés avant lui ; une constante encore inconnue prend son nom pour valeur.
# Sortie en JSON : les variables chaîne (libellés) et, pour chaque variable
# « <colonne>_mask », ses quatre premiers éléments.
PHP_LANGUAGE_LOADER = r"""
error_reporting(E_ERROR);
ini_set('display_errors', '0');
$__lang = realpath($argv[1]);
if ($__lang === false) { fwrite(STDERR, "fichier introuvable\n"); exit(1); }
$__app = dirname($__lang, 2);
chdir($__app);
ob_start();
foreach (array_unique(array_merge(glob($__app . '/*defines.inc.php'),
                                  glob(dirname($__app) . '/*/*defines.inc.php'))) as $__file) {
    include_once $__file;
}
$__unknown = [];
while (true) {
    try {
        include $__lang;
        break;
    } catch (Error $__error) {
        if (count($__unknown) < 1000
            && preg_match('/^Undefined constant "([^"]+)"/', $__error->getMessage(), $__match)) {
            define($__match[1], $__match[1]);
            $__unknown[] = $__match[1];
            continue;
        }
        ob_end_clean();
        fwrite(STDERR, $__error->getMessage() . "\n");
        exit(1);
    }
}
ob_end_clean();
$__labels = [];
$__masks = [];
foreach (get_defined_vars() as $__name => $__value) {
    if (str_starts_with($__name, '_') || $__name === 'argv' || $__name === 'argc' || $__name === 'GLOBALS') {
        continue;
    }
    if (is_string($__value)) {
        $__labels[$__name] = $__value;
    } elseif (is_array($__value) && str_ends_with($__name, '_mask')) {
        $__mask = [];
        for ($__i = 0; $__i < 4 && array_key_exists($__i, $__value); $__i++) {
            $__item = $__value[$__i];
            if (is_array($__item)) {
                $__pairs = [];
                foreach ($__item as $__key => $__text) {
                    $__pairs[] = [(string)$__key, is_scalar($__text) ? (string)$__text : ''];
                }
                $__item = $__pairs;
            } elseif (!is_scalar($__item)) {
                $__item = null;
            }
            $__mask[] = $__item;
        }
        $__masks[substr($__name, 0, -5)] = $__mask;
    }
}
echo json_encode(['labels' => $__labels, 'masks' => $__masks, 'unknown_constants' => $__unknown],
                 JSON_INVALID_UTF8_SUBSTITUTE);
"""

NOT_NULL_CHECK = re.compile(r'^"[^"]+" IS NOT NULL$')
ORACLE_ERROR = re.compile(r"^(ORA-\d{5}|SP2-\d{4}):", re.MULTILINE)


class ExportError(Exception):
    """Erreur présentée à l'utilisateur sans trace d'exécution."""


# --------------------------------------------------------------------------
# Dialogue avec sqlplus
# --------------------------------------------------------------------------

def build_script(with_ddl, with_storage):
    """Construit le script SQL*Plus : dictionnaire en CSV, puis DDL éventuel."""
    parts = [SQL_HEADER, "SET MARKUP CSV ON QUOTE ON"]
    for name, query in DICTIONARY_QUERIES.items():
        parts.append(f"PROMPT {SECTION_MARK}{name}")
        parts.append(query.strip())
    parts.append("SET MARKUP CSV OFF")
    if with_ddl:
        params = {"SQLTERMINATOR": True, "PRETTY": True, "CONSTRAINTS": True,
                  "REF_CONSTRAINTS": False, "EMIT_SCHEMA": False,
                  "SEGMENT_ATTRIBUTES": with_storage}
        parts.append("BEGIN")
        for param, value in params.items():
            parts.append("  DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, "
                         f"'{param}', {'TRUE' if value else 'FALSE'});")
        parts.append("END;\n/")
        parts.append(f"PROMPT {SECTION_MARK}ddl")
        parts.append(DDL_QUERIES.strip())
    parts.append("EXIT")
    return "\n".join(parts) + "\n"


def run_sqlplus(user, dsn, password, script):
    """Exécute le script et retourne la sortie standard de sqlplus."""
    oracle_home = Path(os.environ.get("ORACLE_HOME") or DEFAULT_ORACLE_HOME)
    sqlplus = oracle_home / "bin" / "sqlplus"
    if not sqlplus.is_file():
        raise ExportError(f"sqlplus introuvable : {sqlplus} (vérifier ORACLE_HOME)")
    env = dict(os.environ)
    env["ORACLE_HOME"] = str(oracle_home)
    library_path = [str(oracle_home / "lib")]
    if env.get("LD_LIBRARY_PATH"):
        library_path.append(env["LD_LIBRARY_PATH"])
    env["LD_LIBRARY_PATH"] = ":".join(library_path)
    env["NLS_LANG"] = "AMERICAN_AMERICA.AL32UTF8"

    # Le mot de passe passe par l'entrée standard (commande CONNECT) : il
    # n'apparaît pas dans « ps ». Les guillemets protègent les caractères
    # spéciaux du mot de passe et du DSN « hôte:port/service ».
    if '"' in password or '"' in dsn or '"' in user:
        raise ExportError("guillemet double non accepté dans l'utilisateur, "
                          "le mot de passe ou le DSN")
    connect = f'CONNECT {user}/"{password}"@"{dsn}"\n'
    try:
        result = subprocess.run(
            [str(sqlplus), "-S", "/nolog"],
            input=(connect + script).encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise ExportError(f"sqlplus ne répond pas après {TIMEOUT_S} s") from None
    output = result.stdout.decode("utf-8", errors="replace")
    error = ORACLE_ERROR.search(output)
    if result.returncode != 0 or error:
        # Après un échec de connexion, chaque commande répète « SP2-0640: Not
        # connected » : seules les premières lignes distinctes sont utiles.
        start = error.start() if error else 0
        lines = []
        for line in output[start:].splitlines():
            if line.strip() and not line.startswith("@@@") and line not in lines:
                lines.append(line)
        detail = "\n".join(lines[:5]) or f"code de retour {result.returncode}"
        raise ExportError(f"sqlplus a échoué ({user}@{dsn}) :\n{detail}")
    return output


def split_sections(output):
    """Découpe la sortie de sqlplus selon les repères de section."""
    sections = {}
    current = None
    for line in output.splitlines():
        if line.startswith(SECTION_MARK):
            current = sections.setdefault(line[len(SECTION_MARK):].strip(), [])
        elif current is not None:
            current.append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


def parse_csv(text):
    """Lit une section CSV ; les lignes vides entre enregistrements sont ignorées."""
    return [row for row in csv.reader(io.StringIO(text)) if row]


def parse_ddl(text):
    """Retourne la liste (type, table, nom, DDL) de la section DDL."""
    items = []
    for line in text.splitlines():
        if line.startswith(DDL_MARK):
            kind, table, name = line[len(DDL_MARK):].split(" ", 2)
            items.append((kind, table, name, []))
        elif items:
            items[-1][3].append(line.rstrip())
    return [(kind, table, name, "\n".join(lines).strip())
            for kind, table, name, lines in items]


# --------------------------------------------------------------------------
# Modèle du schéma
# --------------------------------------------------------------------------

def column_type(data_type, length, precision, scale, char_length, char_used):
    """Reconstitue le type d'une colonne tel qu'il s'écrit en DDL."""
    if data_type in ("VARCHAR2", "CHAR"):
        unit = {"C": " CHAR", "B": " BYTE"}.get(char_used, "")
        return f"{data_type}({char_length}{unit})"
    if data_type in ("NVARCHAR2", "NCHAR"):
        return f"{data_type}({char_length})"
    if data_type == "NUMBER":
        if not precision and not scale:
            return "NUMBER" if scale == "" else "NUMBER(*,0)"
        if not precision:
            return f"NUMBER(*,{scale})"
        return f"NUMBER({precision})" if scale in ("", "0") else f"NUMBER({precision},{scale})"
    if data_type == "FLOAT" and precision:
        return f"FLOAT({precision})"
    if data_type == "RAW":
        return f"RAW({length})"
    return data_type


class Schema:
    """Tables RESASAT_ et objets associés, lus dans les sections CSV."""

    def __init__(self, sections):
        rows = {name: parse_csv(sections.get(name, "")) for name in DICTIONARY_QUERIES}

        self.tables = {name: {"comment": comment.strip(), "columns": [], "indexes": [],
                              "triggers": []}
                       for name, comment in rows["tables"]}

        defaults = {(table, column): default.strip()
                    for table, column, default in rows["defaults"]}
        for (table, name, data_type, length, precision, scale, char_length, char_used,
             nullable, comment) in rows["columns"]:
            self.tables[table]["columns"].append({
                "name": name,
                "type": column_type(data_type, length, precision, scale, char_length, char_used),
                "nullable": nullable == "Y",
                "comment": comment.strip(),
                "default": defaults.get((table, name), "")})

        self.constraints = {}
        for name, table, kind, status, r_owner, r_name, delete_rule, condition in rows["constraints"]:
            self.constraints[name] = {
                "name": name, "table": table, "type": kind, "enabled": status == "ENABLED",
                "r_owner": r_owner, "r_name": r_name, "delete_rule": delete_rule,
                "condition": condition.strip(), "columns": []}
        for name, column in rows["constraint_columns"]:
            if name in self.constraints:
                self.constraints[name]["columns"].append(column)

        indexes = {}
        for name, table, uniqueness, index_type in rows["indexes"]:
            indexes[name] = {"name": name, "unique": uniqueness == "UNIQUE",
                             "type": index_type, "columns": []}
            self.tables[table]["indexes"].append(indexes[name])
        for name, column, descend in rows["index_columns"]:
            if name in indexes:
                indexes[name]["columns"].append((column, descend == "DESC"))

        for name, table, trigger_type, event, status in rows["triggers"]:
            self.tables[table]["triggers"].append({
                "name": name, "type": trigger_type, "event": event,
                "enabled": status == "ENABLED"})

        self.sequences = [dict(zip(("name", "min", "max", "increment", "cycle", "cache", "last"),
                                   row)) for row in rows["sequences"]]

    def constraints_of(self, table, kind):
        return [c for c in self.constraints.values() if c["table"] == table and c["type"] == kind]

    def checks_of(self, table):
        """Contraintes de vérification, hors NOT NULL (déjà visibles sur la colonne)."""
        return [c for c in self.constraints_of(table, "C")
                if not NOT_NULL_CHECK.match(c["condition"])]

    def target_of(self, foreign_key):
        """Contrainte visée par une clé étrangère, None si hors du schéma."""
        return self.constraints.get(foreign_key["r_name"])

    def referencing(self, table):
        """Clés étrangères des autres tables qui visent cette table."""
        return [c for c in self.constraints.values()
                if c["type"] == "R" and (self.target_of(c) or {}).get("table") == table]


# --------------------------------------------------------------------------
# Fichier langue de kadlib
# --------------------------------------------------------------------------

def plain_label(text):
    """Libellé sans HTML : entités décodées, balises retirées."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


class Language:
    """Libellés et masques du fichier langue, indexés par nom en minuscules.

    Un libellé est le nom présenté aux utilisateurs d'une table ou d'une
    colonne. Un masque décrit la nature d'une colonne, par exemple
    ["ENUM", [[valeur, signification], ...]] ou ["FK", table, colonne, colonne affichée].
    """

    ENUM_KINDS = ("ENUM", "ENUMORNULL")
    FOREIGN_KEY_KINDS = ("FK", "FKORNULL", "FKNOLIST")

    def __init__(self, labels, masks, unknown_constants=()):
        self.labels = {name.lower(): plain_label(text) for name, text in labels.items()}
        self.masks = {name.lower(): mask for name, mask in masks.items() if mask}
        self.unknown_constants = list(unknown_constants)

    @classmethod
    def load(cls, path):
        """Évalue le fichier langue avec PHP."""
        if not path.is_file():
            raise ExportError(f"fichier langue introuvable : {path}")
        php = shutil.which("php")
        if not php:
            raise ExportError("php introuvable : il est nécessaire à l'option --lang")
        try:
            result = subprocess.run([php, "-r", PHP_LANGUAGE_LOADER, "--", str(path)],
                                    capture_output=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise ExportError(f"php ne répond pas après {TIMEOUT_S} s") from None
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise ExportError(f"lecture du fichier langue {path} impossible :\n{detail}")
        try:
            data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            raise ExportError(f"réponse de php illisible pour {path}") from None
        # PHP rend [] et non {} pour un tableau vide
        return cls(data["labels"] or {}, data["masks"] or {}, data["unknown_constants"])

    def label(self, name):
        return self.labels.get(name.lower(), "")

    def table_label(self, table):
        """Nom d'une table ; à défaut, le fichier langue n'a souvent que son pluriel."""
        return self.label(table) or self.label(table + "s")

    def enum_values(self, column):
        """Liste (valeur, signification) d'une colonne énumérée, sinon None."""
        mask = self.masks.get(column.lower())
        if mask and mask[0] in self.ENUM_KINDS and len(mask) > 1 and isinstance(mask[1], list):
            return [(value, plain_label(text)) for value, text in mask[1]]
        return None

    def foreign_key(self, column):
        """Couple (table, colonne) visé par une colonne clé étrangère, sinon None."""
        mask = self.masks.get(column.lower())
        if (mask and mask[0] in self.FOREIGN_KEY_KINDS and len(mask) > 2
                and isinstance(mask[1], str) and isinstance(mask[2], str)):
            return mask[1], mask[2]
        return None


# --------------------------------------------------------------------------
# Format Markdown
# --------------------------------------------------------------------------

def label(identifier):
    """Nom affiché : en minuscules, comme dans le code de RESASAT."""
    return identifier.lower() if identifier == identifier.upper() else identifier


def file_stem(table):
    return table.lower()


def cell(text):
    """Texte utilisable dans une cellule de tableau Markdown."""
    return " ".join(text.split()).replace("|", "\\|")


def code(text):
    text = cell(text)
    if not text:
        return ""
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def markdown_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(" --- " for _ in headers) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def names(columns):
    return ", ".join(code(label(column)) for column in columns)


def table_link(schema, table):
    """Lien vers la page d'une table, texte simple si elle n'est pas exportée."""
    if table in schema.tables:
        return f"[{label(table)}]({file_stem(table)}.md)"
    return label(table)


def yes_no(value):
    return "oui" if value else "non"


def find_table(schema, name):
    """Nom dans le schéma d'une table citée par le fichier langue, sinon le nom cité."""
    return next((table for table in schema.tables if table.lower() == name.lower()), name)


def enum_title(column):
    return f"Valeurs de {label(column)}"


def column_comment(schema, language, column):
    """Cellule « Commentaire » : nom présenté aux utilisateurs, valeurs de
    l'énumération, cible de la clé étrangère, puis commentaire de la base."""
    parts = []
    if language:
        name = column["name"]
        if language.label(name):
            parts.append(f"**{cell(language.label(name))}**")
        values = language.enum_values(name)
        if values and len(values) > ENUM_INLINE_MAX:
            parts.append(f"Valeurs : voir « {enum_title(name)} »")
        elif values:
            parts.append("Valeurs : " + ", ".join(f"{code(value)} = {cell(text)}"
                                                  for value, text in values))
        target = language.foreign_key(name)
        if target:
            parts.append(f"Clé étrangère vers {code(label(target[1]))} de "
                         f"{table_link(schema, find_table(schema, target[0]))}")
    if column["comment"]:
        parts.append(cell(column["comment"]))
    return " — ".join(parts)


def render_markdown_table(schema, table, language=None):
    info = schema.tables[table]
    parts = [f"# {label(table)}"]
    if language and language.table_label(table):
        parts.append(f"Nom présenté aux utilisateurs : **{language.table_label(table)}**")
    if info["comment"]:
        parts.append(info["comment"])

    parts.append("## Colonnes")
    parts.append(markdown_table(
        ["N°", "Colonne", "Type", "Nul autorisé", "Valeur par défaut", "Commentaire"],
        [[str(position), code(label(column["name"])), code(column["type"]),
          yes_no(column["nullable"]), code(column["default"]),
          column_comment(schema, language, column)]
         for position, column in enumerate(info["columns"], start=1)]))

    # Énumérations trop longues pour la cellule du tableau des colonnes
    for column in info["columns"]:
        values = language.enum_values(column["name"]) if language else None
        if values and len(values) > ENUM_INLINE_MAX:
            parts.append(f"## {enum_title(column['name'])}")
            parts.append(markdown_table(["Valeur", "Signification"],
                                        [[code(value), cell(text)] for value, text in values]))

    for primary in schema.constraints_of(table, "P"):
        parts.append("## Clé primaire")
        parts.append(f"{code(label(primary['name']))} : {names(primary['columns'])}")

    unique = schema.constraints_of(table, "U")
    if unique:
        parts.append("## Contraintes d'unicité")
        parts.append("\n".join(f"* {code(label(c['name']))} : {names(c['columns'])}"
                               for c in unique))

    checks = schema.checks_of(table)
    if checks:
        parts.append("## Contraintes de vérification")
        parts.append("\n".join(f"* {code(label(c['name']))} : {code(c['condition'])}"
                               for c in checks))

    foreign_keys = schema.constraints_of(table, "R")
    if foreign_keys:
        rows = []
        for foreign_key in foreign_keys:
            target = schema.target_of(foreign_key)
            if target:
                target_table = table_link(schema, target["table"])
                target_columns = names(target["columns"])
            else:
                target_table = code(f"{foreign_key['r_owner']}.{foreign_key['r_name']}")
                target_columns = ""
            rows.append([code(label(foreign_key["name"])), names(foreign_key["columns"]),
                         target_table, target_columns, code(foreign_key["delete_rule"]),
                         yes_no(foreign_key["enabled"])])
        parts.append("## Clés étrangères")
        parts.append(markdown_table(
            ["Contrainte", "Colonnes", "Table référencée", "Colonnes référencées",
             "À la suppression", "Active"], rows))

    referencing = schema.referencing(table)
    if referencing:
        parts.append("## Référencée par")
        parts.append(markdown_table(
            ["Table", "Contrainte", "Colonnes"],
            [[table_link(schema, c["table"]), code(label(c["name"])), names(c["columns"])]
             for c in referencing]))

    if info["indexes"]:
        parts.append("## Index")
        parts.append(markdown_table(
            ["Index", "Colonnes", "Unique", "Type"],
            [[code(label(index["name"])),
              ", ".join(code(label(column) + (" DESC" if descending else ""))
                        for column, descending in index["columns"]),
              yes_no(index["unique"]),
              cell(index["type"])] for index in info["indexes"]]))

    if info["triggers"]:
        parts.append("## Déclencheurs")
        parts.append(markdown_table(
            ["Déclencheur", "Type", "Événement", "Actif"],
            [[code(label(trigger["name"])), cell(trigger["type"]), cell(trigger["event"]),
              yes_no(trigger["enabled"])] for trigger in info["triggers"]]))

    return "\n\n".join(parts) + "\n"


def table_comment(language, table, info):
    """Cellule « Commentaire » de l'index : nom présenté aux utilisateurs, puis
    commentaire de la base."""
    parts = []
    if language and language.table_label(table):
        parts.append(f"**{cell(language.table_label(table))}**")
    if info["comment"]:
        parts.append(cell(info["comment"]))
    return " — ".join(parts)


def render_markdown_index(schema, origin, language=None, language_file=None):
    introduction = (f"Schéma extrait de `{origin}` le {datetime.date.today().isoformat()} "
                    "par *tools/export-oracle-db.py*. Seules les tables dont le nom commence "
                    "par `resasat_` sont décrites.")
    if language:
        introduction += (" Les noms présentés aux utilisateurs (en gras), les valeurs des "
                         "énumérations et les clés étrangères des commentaires viennent du "
                         f"fichier langue `{language_file}`.")
    parts = ["# Schéma de la base de données RESASAT",
             introduction,
             "## Tables",
             markdown_table(
                 ["Table", "Colonnes", "Commentaire"],
                 [[table_link(schema, table), str(len(info["columns"])),
                   table_comment(language, table, info)]
                  for table, info in schema.tables.items()])]
    if schema.sequences:
        parts.append("## Séquences")
        parts.append(markdown_table(
            ["Séquence", "Minimum", "Maximum", "Incrément", "Cyclique", "Cache",
             "Prochaine valeur"],
            [[code(label(s["name"])), s["min"], s["max"], s["increment"],
              yes_no(s["cycle"] == "Y"), s["cache"], s["last"]] for s in schema.sequences]))
    return "\n\n".join(parts) + "\n"


def render_markdown(schema, origin, language=None, language_file=None):
    """Sans fichier langue, les fichiers ne contiennent que ce que dit la base."""
    files = {"index.md": render_markdown_index(schema, origin, language, language_file)}
    for table in schema.tables:
        files[file_stem(table) + ".md"] = render_markdown_table(schema, table, language)
    return files


# --------------------------------------------------------------------------
# Format SQL
# --------------------------------------------------------------------------

def sql_string(text):
    return "'" + text.replace("'", "''") + "'"


def comment_statements(table, info):
    statements = []
    if info["comment"]:
        statements.append(f'COMMENT ON TABLE "{table}" IS {sql_string(info["comment"])};')
    for column in info["columns"]:
        if column["comment"]:
            statements.append(f'COMMENT ON COLUMN "{table}"."{column["name"]}" IS '
                              f'{sql_string(column["comment"])};')
    return statements


def render_sql(schema, ddl_items, origin):
    today = datetime.date.today().isoformat()
    by_table = {table: {} for table in schema.tables}
    sequences = []
    for kind, table, name, ddl in ddl_items:
        if kind == "SEQUENCE":
            sequences.append(ddl)
        elif table in by_table:
            by_table[table].setdefault(kind, []).append(ddl)

    files = {}
    for table, info in schema.tables.items():
        ddl = by_table[table]
        if "TABLE" not in ddl:
            raise ExportError(f"DDL absent pour la table {table}")
        referenced = sorted({target["table"]
                             for target in map(schema.target_of, schema.constraints_of(table, "R"))
                             if target and target["table"] != table})
        parts = [f"-- Table {table}\n"
                 f"-- Extrait de {origin} le {today} par tools/export-oracle-db.py\n"
                 f"-- Tables référencées (à créer avant) : {', '.join(referenced) or 'aucune'}"]
        parts += ddl["TABLE"]
        for kind, title in (("INDEX", "Index"), ("REF_CONSTRAINT", "Clés étrangères"),
                            ("TRIGGER", "Déclencheurs")):
            if kind in ddl:
                parts.append(f"-- {title}")
                parts += ddl[kind]
        comments = comment_statements(table, info)
        if comments:
            parts.append("-- Commentaires")
            parts.append("\n".join(comments))
        files[file_stem(table) + ".sql"] = "\n\n".join(parts) + "\n"

    if sequences:
        header = (f"-- Séquences RESASAT_\n"
                  f"-- Extrait de {origin} le {today} par tools/export-oracle-db.py\n"
                  "-- START WITH reprend la valeur courante de la séquence au moment de l'export")
        files["_sequences.sql"] = "\n\n".join([header] + sequences) + "\n"
    return files


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------

def write_files(directory, files, extension):
    """Remplace les fichiers du format dans le répertoire de sortie."""
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob(f"*{extension}"):
        if stale.is_file() and stale.name not in files:
            stale.unlink()
    for name, content in files.items():
        (directory / name).write_text(content, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Exporte le schéma des tables RESASAT_ de la base Oracle de RESASAT.")
    parser.add_argument("--format", choices=("markdown", "sql"), required=True,
                        help="markdown : un fichier .md par table ; "
                             "sql : un fichier .sql (DDL Oracle) par table")
    parser.add_argument("--output", type=Path, metavar="RÉPERTOIRE",
                        help="répertoire de sortie (défaut : build/doc/resasat-db/ "
                             "ou build/sql/resasat-db/)")
    parser.add_argument("--user", default=DEFAULT_USER,
                        help=f"utilisateur Oracle (défaut : {DEFAULT_USER})")
    parser.add_argument("--dsn", default=DEFAULT_DSN,
                        help=f"hôte:port/service (défaut : {DEFAULT_DSN})")
    parser.add_argument("--with-storage", action="store_true",
                        help="format sql : conserver tablespaces et attributs de stockage")
    parser.add_argument("--lang", type=Path, metavar="FICHIER.php",
                        help="format markdown : fichier langue de kadlib (lang/fr.inc.php) "
                             "qui enrichit les commentaires des tables et des colonnes")
    args = parser.parse_args()
    if args.lang and args.format != "markdown":
        parser.error("--lang ne s'applique qu'au format markdown")

    password = os.environ.get(PASSWORD_VARIABLE) or getpass.getpass(
        f"Mot de passe de {args.user}@{args.dsn} : ")
    if not password:
        print("Erreur : mot de passe vide.", file=sys.stderr)
        return 1

    origin = f"{args.user}@{args.dsn}"
    output = args.output or DEFAULT_OUTPUT[args.format]
    try:
        # Le fichier langue est lu en premier : une erreur évite d'interroger la base.
        language = Language.load(args.lang) if args.lang else None
        if language and language.unknown_constants:
            print("Avertissement : constantes PHP inconnues dans le fichier langue : "
                  + ", ".join(language.unknown_constants), file=sys.stderr)
        script = build_script(with_ddl=args.format == "sql", with_storage=args.with_storage)
        sections = split_sections(run_sqlplus(args.user, args.dsn, password, script))
        schema = Schema(sections)
        if not schema.tables:
            raise ExportError(f"aucune table RESASAT_ dans le schéma {origin}")
        if args.format == "markdown":
            files = render_markdown(schema, origin, language,
                                    args.lang.name if args.lang else None)
        else:
            files = render_sql(schema, parse_ddl(sections.get("ddl", "")), origin)
        write_files(output, files, EXTENSION[args.format])
    except ExportError as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1

    print(f"{len(schema.tables)} tables, {len(files)} fichiers écrits dans {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
