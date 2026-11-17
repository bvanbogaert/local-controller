#!/usr/bin/env python3.11
"""Tests de tools/export-oracle-db.py.

Deux familles :

* sans base : l'analyse de la sortie de sqlplus et la production des fichiers,
  à partir d'une sortie d'essai écrite dans ce fichier, et la lecture du fichier
  langue de kadlib de fixtures/kadlib/ (sautée si php est absent) ;
* avec la base RESASAT : l'outil est lancé comme le ferait un utilisateur. Ces
  tests sont sautés si la variable RESASAT_PASSWORD ou sqlplus sont absents.

Lancement, depuis la racine du dépôt :

    python3.11 -m unittest discover -s tests/tools -v
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOL = ROOT / "tools" / "export-oracle-db.py"
LANGUAGE_FILE = (Path(__file__).resolve().parent / "fixtures" / "kadlib" / "addons" / "Essai"
                 / "lang" / "fr.inc.php")


def load_tool(path=TOOL):
    """Charge un outil comme un module (son nom contient des tirets)."""
    loader = SourceFileLoader(path.stem.replace("-", "_"), str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    sys.modules[loader.name] = module  # les dataclasses y cherchent leur module
    loader.exec_module(module)
    return module


tool = load_tool()
# Le format json est celui que lit tools/create-db.py : sa validation sert de référence.
create_db = load_tool(ROOT / "tools" / "create-db.py")

SQLPLUS = Path(os.environ.get("ORACLE_HOME") or tool.DEFAULT_ORACLE_HOME) / "bin" / "sqlplus"
NO_DATABASE = [reason for reason, missing in (
    (f"variable {tool.PASSWORD_VARIABLE} absente", not os.environ.get(tool.PASSWORD_VARIABLE)),
    (f"{SQLPLUS} absent", not SQLPLUS.is_file())) if missing]

# Sortie de sqlplus pour un schéma d'essai : deux tables RESASAT_ et une clé
# étrangère vers USERS, table hors du préfixe.
SAMPLE_OUTPUT = '''\
@@@section tables

"RESASAT_CHANNEL","Canaux | satellite"
"RESASAT_STATION",
@@@section columns

"RESASAT_CHANNEL","RESASAT_CHANNEL_ID","NUMBER",22,8,0,0,,"N","Identifiant
sur deux lignes"
"RESASAT_CHANNEL","RESASAT_CHANNEL_NAME","VARCHAR2",400,,,100,"C","Y","L'intitulé"
"RESASAT_CHANNEL","RESASAT_CHANNEL_STATION_FK","NUMBER",22,8,0,0,,"Y",
"RESASAT_CHANNEL","RESASAT_CHANNEL_OWNER_FK","NUMBER",22,,,0,,"Y",
"RESASAT_STATION","RESASAT_STATION_ID","NUMBER",22,8,0,0,,"N",
"RESASAT_STATION","RESASAT_STATION_START","DATE",7,,,0,,"Y",
@@@section defaults

"RESASAT_CHANNEL","RESASAT_CHANNEL_NAME","'sans nom' "
@@@section constraints

"RESASAT_CHANNEL_PK","RESASAT_CHANNEL","P","ENABLED",,,,
"RESASAT_CHANNEL_NAME_UK","RESASAT_CHANNEL","U","ENABLED",,,,
"RESASAT_CHANNEL_STATION_FK","RESASAT_CHANNEL","R","ENABLED","RESAORA","RESASAT_STATION_PK","CASCADE",
"RESASAT_CHANNEL_OWNER_FK","RESASAT_CHANNEL","R","DISABLED","RESAORA","USERS_PK","NO ACTION",
"SYS_C001","RESASAT_CHANNEL","C","ENABLED",,,,"""RESASAT_CHANNEL_ID"" IS NOT NULL"
"RESASAT_CHANNEL_CK","RESASAT_CHANNEL","C","ENABLED",,,,"RESASAT_CHANNEL_ID > 0"
"RESASAT_STATION_PK","RESASAT_STATION","P","ENABLED",,,,
"USERS_PK","USERS","P","ENABLED",,,,
@@@section constraint_columns

"RESASAT_CHANNEL_CK","RESASAT_CHANNEL_ID"
"RESASAT_CHANNEL_NAME_UK","RESASAT_CHANNEL_NAME"
"RESASAT_CHANNEL_OWNER_FK","RESASAT_CHANNEL_OWNER_FK"
"RESASAT_CHANNEL_PK","RESASAT_CHANNEL_ID"
"RESASAT_CHANNEL_STATION_FK","RESASAT_CHANNEL_STATION_FK"
"RESASAT_STATION_PK","RESASAT_STATION_ID"
"SYS_C001","RESASAT_CHANNEL_ID"
"USERS_PK","ID"
@@@section indexes

"RESASAT_CHANNEL_NAME_IDX","RESASAT_CHANNEL","NONUNIQUE","NORMAL"
"RESASAT_CHANNEL_PK","RESASAT_CHANNEL","UNIQUE","NORMAL"
@@@section index_columns

"RESASAT_CHANNEL_NAME_IDX","RESASAT_CHANNEL_NAME","ASC"
"RESASAT_CHANNEL_NAME_IDX","RESASAT_CHANNEL_ID","DESC"
"RESASAT_CHANNEL_PK","RESASAT_CHANNEL_ID","ASC"
@@@section triggers

"RESASAT_CHANNEL_ID_TRIG","RESASAT_CHANNEL","BEFORE EACH ROW","INSERT","ENABLED"
@@@section sequences

"RESASAT_CHANNEL_ID_SEQ","1","9999","1","N","20","42"
@@@section ddl
@@@ddl TABLE RESASAT_CHANNEL RESASAT_CHANNEL

  CREATE TABLE "RESASAT_CHANNEL"
   (	"RESASAT_CHANNEL_ID" NUMBER(8,0) NOT NULL ENABLE
   ) ;

@@@ddl TABLE RESASAT_STATION RESASAT_STATION

  CREATE TABLE "RESASAT_STATION"
   (	"RESASAT_STATION_ID" NUMBER(8,0) NOT NULL ENABLE
   ) ;

@@@ddl INDEX RESASAT_CHANNEL RESASAT_CHANNEL_NAME_IDX

  CREATE INDEX "RESASAT_CHANNEL_NAME_IDX" ON "RESASAT_CHANNEL" ("RESASAT_CHANNEL_NAME") ;

@@@ddl REF_CONSTRAINT RESASAT_CHANNEL RESASAT_CHANNEL_STATION_FK

  ALTER TABLE "RESASAT_CHANNEL" ADD CONSTRAINT "RESASAT_CHANNEL_STATION_FK" FOREIGN KEY ("RESASAT_CHANNEL_STATION_FK")
	  REFERENCES "RESASAT_STATION" ("RESASAT_STATION_ID") ON DELETE CASCADE ENABLE;

@@@ddl TRIGGER RESASAT_CHANNEL RESASAT_CHANNEL_ID_TRIG

  CREATE OR REPLACE TRIGGER "RESASAT_CHANNEL_ID_TRIG" before insert on resasat_channel for each row
begin
  null;
end;
/

@@@ddl SEQUENCE - RESASAT_CHANNEL_ID_SEQ

   CREATE SEQUENCE  "RESASAT_CHANNEL_ID_SEQ"  MINVALUE 1 MAXVALUE 9999 INCREMENT BY 1 START WITH 42 ;
'''


class ColumnTypeTest(unittest.TestCase):

    def test_types(self):
        cases = [
            (("VARCHAR2", "400", "", "", "100", "C"), "VARCHAR2(100 CHAR)"),
            (("VARCHAR2", "40", "", "", "40", "B"), "VARCHAR2(40 BYTE)"),
            (("CHAR", "1", "", "", "1", "B"), "CHAR(1 BYTE)"),
            (("NVARCHAR2", "80", "", "", "40", "C"), "NVARCHAR2(40)"),
            (("NUMBER", "22", "8", "0", "0", ""), "NUMBER(8)"),
            (("NUMBER", "22", "10", "2", "0", ""), "NUMBER(10,2)"),
            (("NUMBER", "22", "", "", "0", ""), "NUMBER"),
            (("NUMBER", "22", "", "0", "0", ""), "NUMBER(*,0)"),
            (("FLOAT", "22", "126", "", "0", ""), "FLOAT(126)"),
            (("RAW", "16", "", "", "0", ""), "RAW(16)"),
            (("DATE", "7", "", "", "0", ""), "DATE"),
            (("TIMESTAMP(6)", "11", "", "6", "0", ""), "TIMESTAMP(6)"),
            (("CLOB", "4000", "", "", "0", ""), "CLOB"),
        ]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(tool.column_type(*arguments), expected)


class ScriptTest(unittest.TestCase):

    def test_dictionary_only(self):
        script = tool.build_script(with_ddl=False, with_storage=False)
        self.assertIn("WHENEVER SQLERROR EXIT FAILURE", script)
        self.assertNotIn("DBMS_METADATA", script)
        self.assertTrue(script.rstrip().endswith("EXIT"))
        for name in tool.DICTIONARY_QUERIES:
            self.assertIn(f"PROMPT @@@section {name}\n", script)

    def test_ddl_without_storage(self):
        script = tool.build_script(with_ddl=True, with_storage=False)
        self.assertIn("'SEGMENT_ATTRIBUTES', FALSE", script)
        self.assertIn("'EMIT_SCHEMA', FALSE", script)
        self.assertIn("'REF_CONSTRAINTS', FALSE", script)
        self.assertIn("PROMPT @@@section ddl\n", script)

    def test_ddl_with_storage(self):
        script = tool.build_script(with_ddl=True, with_storage=True)
        self.assertIn("'SEGMENT_ATTRIBUTES', TRUE", script)

    def test_exported_tables(self):
        script = tool.build_script(with_ddl=True, with_storage=False)
        # Préfixe RESASAT_, plus la table USERS
        self.assertIn(r"(table_name LIKE 'RESASAT\_%' ESCAPE '\' OR table_name IN ('USERS'))",
                      script)
        self.assertIn(r"(t.table_name LIKE 'RESASAT\_%' ESCAPE '\' OR t.table_name IN ('USERS'))",
                      script)
        # Chaque requête sur les tables porte le filtre complet
        self.assertEqual(script.count("LIKE 'RESASAT"), script.count("IN ('USERS')")
                         + script.count("sequence_name LIKE"))


class ParsingTest(unittest.TestCase):

    def setUp(self):
        self.sections = tool.split_sections(SAMPLE_OUTPUT)
        self.schema = tool.Schema(self.sections)

    def test_sections(self):
        self.assertEqual(set(self.sections), set(tool.DICTIONARY_QUERIES) | {"ddl"})

    def test_tables_and_columns(self):
        self.assertEqual(list(self.schema.tables), ["RESASAT_CHANNEL", "RESASAT_STATION"])
        columns = self.schema.tables["RESASAT_CHANNEL"]["columns"]
        self.assertEqual([c["name"] for c in columns],
                         ["RESASAT_CHANNEL_ID", "RESASAT_CHANNEL_NAME",
                          "RESASAT_CHANNEL_STATION_FK", "RESASAT_CHANNEL_OWNER_FK"])
        self.assertEqual(columns[0]["type"], "NUMBER(8)")
        self.assertFalse(columns[0]["nullable"])
        # Champ CSV sur deux lignes
        self.assertEqual(columns[0]["comment"], "Identifiant\nsur deux lignes")
        self.assertEqual(columns[1]["type"], "VARCHAR2(100 CHAR)")
        self.assertEqual(columns[1]["default"], "'sans nom'")
        self.assertEqual(columns[2]["default"], "")

    def test_constraints(self):
        primary = self.schema.constraints_of("RESASAT_CHANNEL", "P")
        self.assertEqual([c["columns"] for c in primary], [["RESASAT_CHANNEL_ID"]])
        # La contrainte NOT NULL générée n'est pas une contrainte de vérification à montrer
        self.assertEqual([c["name"] for c in self.schema.checks_of("RESASAT_CHANNEL")],
                         ["RESASAT_CHANNEL_CK"])
        self.assertEqual([c["name"] for c in self.schema.referencing("RESASAT_STATION")],
                         ["RESASAT_CHANNEL_STATION_FK"])

    def test_indexes(self):
        indexes = {i["name"]: i for i in self.schema.tables["RESASAT_CHANNEL"]["indexes"]}
        self.assertEqual(indexes["RESASAT_CHANNEL_NAME_IDX"]["columns"],
                         [("RESASAT_CHANNEL_NAME", False), ("RESASAT_CHANNEL_ID", True)])
        self.assertTrue(indexes["RESASAT_CHANNEL_PK"]["unique"])
        self.assertFalse(indexes["RESASAT_CHANNEL_NAME_IDX"]["unique"])

    def test_ddl_items(self):
        items = tool.parse_ddl(self.sections["ddl"])
        self.assertEqual([(kind, table, name) for kind, table, name, _ in items], [
            ("TABLE", "RESASAT_CHANNEL", "RESASAT_CHANNEL"),
            ("TABLE", "RESASAT_STATION", "RESASAT_STATION"),
            ("INDEX", "RESASAT_CHANNEL", "RESASAT_CHANNEL_NAME_IDX"),
            ("REF_CONSTRAINT", "RESASAT_CHANNEL", "RESASAT_CHANNEL_STATION_FK"),
            ("TRIGGER", "RESASAT_CHANNEL", "RESASAT_CHANNEL_ID_TRIG"),
            ("SEQUENCE", "-", "RESASAT_CHANNEL_ID_SEQ")])
        self.assertTrue(items[0][3].startswith('CREATE TABLE "RESASAT_CHANNEL"'))
        self.assertTrue(items[0][3].endswith(") ;"))


class MarkdownTest(unittest.TestCase):

    def setUp(self):
        schema = tool.Schema(tool.split_sections(SAMPLE_OUTPUT))
        self.files = tool.render_markdown(schema, "resaora@essai")

    def test_files(self):
        self.assertEqual(set(self.files),
                         {"index.md", "resasat_channel.md", "resasat_station.md"})

    def test_single_h1(self):
        for name, content in self.files.items():
            with self.subTest(file=name):
                self.assertEqual(len(re.findall(r"^# ", content, re.MULTILINE)), 1)
                self.assertNotRegex(content, r"<[a-zA-Z/]")  # pas de HTML brut

    def test_index(self):
        index = self.files["index.md"]
        self.assertIn("resaora@essai", index)
        # Le « | » du commentaire est protégé pour ne pas couper la cellule
        self.assertIn("| [resasat_channel](resasat_channel.md) | 4 | Canaux \\| satellite |", index)
        self.assertIn("| [resasat_station](resasat_station.md) | 2 |  |", index)
        self.assertIn("| `resasat_channel_id_seq` | 1 | 9999 | 1 | non | 20 | 42 |", index)

    def test_table(self):
        page = self.files["resasat_channel.md"]
        self.assertTrue(page.startswith("# resasat_channel\n\nCanaux | satellite\n"))
        # Le commentaire sur deux lignes tient dans une cellule
        self.assertIn("| 1 | `resasat_channel_id` | `NUMBER(8)` | non |  | "
                      "Identifiant sur deux lignes |", page)
        self.assertIn("| 2 | `resasat_channel_name` | `VARCHAR2(100 CHAR)` | oui | "
                      "`'sans nom'` | L'intitulé |", page)
        self.assertIn("## Clé primaire\n\n`resasat_channel_pk` : `resasat_channel_id`", page)
        self.assertIn("* `resasat_channel_name_uk` : `resasat_channel_name`", page)
        self.assertIn("* `resasat_channel_ck` : `RESASAT_CHANNEL_ID > 0`", page)
        self.assertNotIn("IS NOT NULL", page)
        # Clé étrangère vers une table exportée : lien ; vers une autre table : texte
        self.assertIn("| `resasat_channel_station_fk` | `resasat_channel_station_fk` | "
                      "[resasat_station](resasat_station.md) | `resasat_station_id` | "
                      "`CASCADE` | oui |", page)
        self.assertIn("| `resasat_channel_owner_fk` | `resasat_channel_owner_fk` | "
                      "users | `id` | `NO ACTION` | non |", page)
        self.assertIn("| `resasat_channel_name_idx` | `resasat_channel_name`, "
                      "`resasat_channel_id DESC` | non | NORMAL |", page)
        self.assertIn("| `resasat_channel_id_trig` | BEFORE EACH ROW | INSERT | oui |", page)

    def test_empty_sections_are_omitted(self):
        page = self.files["resasat_station.md"]
        self.assertIn("## Colonnes", page)
        self.assertIn("## Clé primaire", page)
        self.assertIn("## Référencée par", page)
        self.assertIn("| [resasat_channel](resasat_channel.md) | `resasat_channel_station_fk` | "
                      "`resasat_channel_station_fk` |", page)
        for title in ("Contraintes d'unicité", "Contraintes de vérification",
                      "Clés étrangères", "Index", "Déclencheurs"):
            self.assertNotIn(f"## {title}", page)


class SqlTest(unittest.TestCase):

    def setUp(self):
        sections = tool.split_sections(SAMPLE_OUTPUT)
        self.schema = tool.Schema(sections)
        self.items = tool.parse_ddl(sections["ddl"])
        self.files = tool.render_sql(self.schema, self.items, "resaora@essai")

    def test_files(self):
        self.assertEqual(set(self.files),
                         {"_sequences.sql", "resasat_channel.sql", "resasat_station.sql"})

    def test_table_file(self):
        content = self.files["resasat_channel.sql"]
        self.assertIn("-- Tables référencées (à créer avant) : RESASAT_STATION, USERS", content)
        # Ordre : table, index, clés étrangères, déclencheurs, commentaires
        positions = [content.index(text) for text in (
            'CREATE TABLE "RESASAT_CHANNEL"', 'CREATE INDEX "RESASAT_CHANNEL_NAME_IDX"',
            'ADD CONSTRAINT "RESASAT_CHANNEL_STATION_FK"',
            'CREATE OR REPLACE TRIGGER "RESASAT_CHANNEL_ID_TRIG"', "COMMENT ON TABLE")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("""COMMENT ON TABLE "RESASAT_CHANNEL" IS 'Canaux | satellite';""", content)
        # L'apostrophe du commentaire est doublée
        self.assertIn('COMMENT ON COLUMN "RESASAT_CHANNEL"."RESASAT_CHANNEL_NAME" IS '
                      "'L''intitulé';", content)
        self.assertNotIn("RESASAT_STATION_ID\" NUMBER", content)

    def test_table_without_dependencies(self):
        content = self.files["resasat_station.sql"]
        self.assertIn("-- Tables référencées (à créer avant) : aucune", content)
        self.assertNotIn("-- Index", content)
        self.assertNotIn("COMMENT ON", content)

    def test_sequences(self):
        self.assertIn('CREATE SEQUENCE  "RESASAT_CHANNEL_ID_SEQ"', self.files["_sequences.sql"])

    def test_missing_table_ddl(self):
        items = [item for item in self.items if item[2] != "RESASAT_STATION"]
        with self.assertRaises(tool.ExportError):
            tool.render_sql(self.schema, items, "resaora@essai")


class JsonTest(unittest.TestCase):

    def setUp(self):
        self.schema = tool.Schema(tool.split_sections(SAMPLE_OUTPUT))
        files, self.warnings = tool.render_json(self.schema)
        self.texts = files
        self.tables = {name: json.loads(text) for name, text in files.items()}

    @staticmethod
    def oracle_column(data_type, precision="", scale="", char_length="0"):
        return {"data_type": data_type, "precision": precision, "scale": scale,
                "char_length": char_length}

    def test_types(self):
        cases = [
            (("NUMBER", "1", "0"), ("int", None)),
            (("NUMBER", "9", "0"), ("int", None)),
            # Dix chiffres (dates Unix) ne tiennent plus sur 32 bits
            (("NUMBER", "10", "0"), ("bigint", None)),
            (("NUMBER", "18", ""), ("bigint", None)),
            (("NUMBER", "19", "0"), None),
            (("NUMBER", "10", "2"), None),
            (("NUMBER", "", ""), None),
            (("BINARY_DOUBLE",), ("double", None)),
            (("FLOAT", "126"), ("double", None)),
            (("VARCHAR2", "", "", "255"), ("varchar", 255)),
            (("CHAR", "", "", "1"), ("varchar", 1)),
            (("DATE",), None),
            (("CLOB",), None),
        ]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(tool.json_type(self.oracle_column(*arguments)), expected)

    def test_defaults(self):
        cases = [("", (None, True)), ("NULL ", (None, True)), ("0", (0, True)),
                 ("(-1)", (-1, True)), ("1.5", (1.5, True)), ("'sans nom' ", ("sans nom", True)),
                 ("'l''un'", ("l'un", True)), ("''", ("", True)),
                 ("SYSDATE", (None, False)), ("'a' || 'b'", (None, False))]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(tool.json_default(text), expected)

    def test_files(self):
        self.assertEqual(set(self.tables), {"resasat_channel.json", "resasat_station.json"})
        for name, text in self.texts.items():
            with self.subTest(file=name):
                self.assertEqual(self.tables[name]["name"], name[:-5])
                self.assertTrue(text.endswith("}\n"))
        self.assertIn('"comment": "L\'intitulé"', self.texts["resasat_channel.json"])

    def test_table(self):
        table = self.tables["resasat_channel.json"]
        self.assertEqual(table["comment"], "Canaux | satellite")
        self.assertEqual(table["primary_key"], ["resasat_channel_id"])
        self.assertEqual(table["columns"][0],
                         {"name": "resasat_channel_id", "comment": "Identifiant sur deux lignes",
                          "type": "int", "nullable": False, "default": None,
                          "auto_increment": False})
        self.assertEqual(table["columns"][1],
                         {"name": "resasat_channel_name", "comment": "L'intitulé",
                          "type": "varchar", "length": 100, "nullable": True,
                          "default": "sans nom", "auto_increment": False})

    def test_references_from_database_constraints(self):
        columns = {c["name"]: c for c in self.tables["resasat_channel.json"]["columns"]}
        self.assertEqual(columns["resasat_channel_station_fk"]["references"],
                         {"table": "resasat_station", "column": "resasat_station_id"})
        self.assertEqual(columns["resasat_channel_owner_fk"]["references"],
                         {"table": "users", "column": "id"})
        self.assertNotIn("references", columns["resasat_channel_id"])

    def test_indexes(self):
        # L'index de la clé primaire n'est pas repris ; la contrainte d'unicité
        # sans index devient un index unique ; l'index décroissant est signalé.
        self.assertEqual(self.tables["resasat_channel.json"]["indexes"],
                         [{"name": "resasat_channel_name_uk", "unique": True,
                           "columns": ["resasat_channel_name"]}])
        self.assertIn("resasat_channel : index resasat_channel_name_idx ignoré "
                      "(ordre décroissant ou expression)", self.warnings)
        self.assertEqual(self.tables["resasat_station.json"]["indexes"], [])

    def test_unmapped_types_are_kept_and_reported(self):
        columns = {c["name"]: c for c in self.tables["resasat_station.json"]["columns"]}
        self.assertEqual(columns["resasat_station_start"]["type"], "DATE")
        self.assertIn("resasat_station.resasat_station_start : type DATE sans correspondance "
                      "dans le modèle de données", self.warnings)
        self.assertEqual(len(self.warnings), 3)  # DATE, NUMBER sans précision, index

    def test_auto_increment(self):
        self.assertIsNone(tool.auto_increment_column(self.schema, "RESASAT_CHANNEL"))
        sample = SAMPLE_OUTPUT.replace("RESASAT_CHANNEL_ID_TRIG", "RESASAT_CHANNEL_AUTO_INC")
        schema = tool.Schema(tool.split_sections(sample))
        self.assertEqual(tool.auto_increment_column(schema, "RESASAT_CHANNEL"),
                         "RESASAT_CHANNEL_ID")
        table = json.loads(tool.render_json(schema)[0]["resasat_channel.json"])
        self.assertEqual([c["auto_increment"] for c in table["columns"]],
                         [True, False, False, False])
        # Déclencheur désactivé : pas d'auto-incrément
        disabled = sample.replace('"INSERT","ENABLED"', '"INSERT","DISABLED"')
        self.assertIsNone(tool.auto_increment_column(
            tool.Schema(tool.split_sections(disabled)), "RESASAT_CHANNEL"))

    def test_language_file(self):
        language = tool.Language(
            labels={"resasat_channel": "Slot", "resasat_channel_id": "Index",
                    "resasat_channel_name": "Nom"},
            masks={"resasat_channel_id": ["FKNOLIST", "RESASAT_STATION", "RESASAT_STATION_ID",
                                          "resasat_station_name"],
                   "resasat_channel_name": ["ENUM", [["H", "Horizontale (X)"],
                                                     ["V", "Verticale (Y)"]]]})
        table = json.loads(tool.render_json(self.schema, language)[0]["resasat_channel.json"])
        self.assertEqual(table["comment"], "Slot — Canaux | satellite")
        self.assertEqual(table["columns"][0]["comment"], "Index — Identifiant sur deux lignes")
        self.assertEqual(table["columns"][0]["references"],
                         {"table": "resasat_station", "column": "resasat_station_id",
                          "label": "resasat_station_name"})
        self.assertEqual(table["columns"][1]["values"],
                         {"H": "Horizontale (X)", "V": "Verticale (Y)"})

    def test_format_and_reference_label(self):
        language = tool.Language(
            labels={},
            masks={"resasat_channel_id": ["DATETIME"],
                   "resasat_channel_name": ["YESNO"],      # varchar : pas de format
                   "resasat_channel_station_fk": ["FKORNULL", "resasat_station",
                                                  "resasat_station_id", "RESASAT_STATION_NAME"],
                   "resasat_channel_owner_fk": ["FK", "users", "ID",
                                                "concat(vorname, nachname)"],
                   "resasat_station_id": ["YESNO"]})
        files = tool.render_json(self.schema, language)[0]
        columns = {c["name"]: c for c in json.loads(files["resasat_channel.json"])["columns"]}
        self.assertEqual(columns["resasat_channel_id"]["format"], "datetime")
        self.assertNotIn("format", columns["resasat_channel_name"])
        # Le nom de l'enregistrement lié complète la contrainte de la base
        self.assertEqual(columns["resasat_channel_station_fk"]["references"],
                         {"table": "resasat_station", "column": "resasat_station_id",
                          "label": "resasat_station_name"})
        # Une expression n'est pas un nom de colonne
        self.assertEqual(columns["resasat_channel_owner_fk"]["references"],
                         {"table": "users", "column": "id"})
        station = json.loads(files["resasat_station.json"])
        self.assertEqual(station["columns"][0]["format"], "yes_no")
        self.assertEqual(create_db.validate_table(station, "resasat_station")[:1],
                         ["colonne resasat_station_start : type 'DATE' inconnu "
                          "(types acceptés : int, bigint, double, varchar)"])

    def test_files_are_read_by_create_db(self):
        # Seuls les types sans correspondance sont refusés par tools/create-db.py
        self.assertEqual(
            create_db.validate_table(self.tables["resasat_channel.json"], "resasat_channel"),
            ["colonne resasat_channel_owner_fk : type 'NUMBER' inconnu "
             "(types acceptés : int, bigint, double, varchar)"])
        self.assertEqual(
            create_db.validate_table(self.tables["resasat_station.json"], "resasat_station"),
            ["colonne resasat_station_start : type 'DATE' inconnu "
             "(types acceptés : int, bigint, double, varchar)"])


class WriteFilesTest(unittest.TestCase):

    def test_stale_files_are_removed(self):
        with tempfile.TemporaryDirectory(prefix="test-export-oracle-db-") as tmp:
            directory = Path(tmp) / "a" / "b"
            directory.mkdir(parents=True)
            (directory / "resasat_old.md").write_text("ancien")
            (directory / "resasat_kept.md").write_text("ancien")
            (directory / "notes.txt").write_text("autre format")
            tool.write_files(directory, {"resasat_kept.md": "nouveau", "index.md": "é"}, ".md")
            self.assertEqual(sorted(p.name for p in directory.iterdir()),
                             ["index.md", "notes.txt", "resasat_kept.md"])
            self.assertEqual((directory / "resasat_kept.md").read_text(), "nouveau")
            self.assertEqual((directory / "index.md").read_bytes(), "é".encode("utf-8"))

    def test_directory_is_created(self):
        with tempfile.TemporaryDirectory(prefix="test-export-oracle-db-") as tmp:
            directory = Path(tmp) / "a" / "b"
            tool.write_files(directory, {"index.md": "x"}, ".md")
            self.assertTrue((directory / "index.md").is_file())


class CommandLineTest(unittest.TestCase):

    def test_format_is_required(self):
        result = subprocess.run([str(TOOL)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--format", result.stderr)

    def test_unknown_format(self):
        result = subprocess.run([str(TOOL), "--format", "xml"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)

    def test_sqlplus_not_found(self):
        with tempfile.TemporaryDirectory(prefix="test-export-oracle-db-") as tmp:
            env = dict(os.environ, ORACLE_HOME=tmp, RESASAT_PASSWORD="sans-objet")
            result = subprocess.run(
                [str(TOOL), "--format", "sql", "--output", str(Path(tmp) / "out")],
                capture_output=True, text=True, timeout=30, env=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn("sqlplus introuvable", result.stderr)
            self.assertFalse((Path(tmp) / "out").exists())


@unittest.skipIf(NO_DATABASE, "base RESASAT non disponible : " + ", ".join(NO_DATABASE))
class DatabaseTest(unittest.TestCase):

    @unittest.skipUnless(shutil.which("php"), "php absent")
    def test_markdown_with_language_file(self):
        result = self.export("--format", "markdown", "--lang", str(LANGUAGE_FILE))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CHANNEL_UNKNOWN", result.stderr)  # avertissement, sans arrêt
        index = (self.output / "index.md").read_text(encoding="utf-8")
        self.assertIn("fichier langue `fr.inc.php`", index)
        self.assertIn("| [resasat_channel](resasat_channel.md) |", index)
        self.assertIn("**Slot**", index)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="test-export-oracle-db-")
        self.addCleanup(self._tmp.cleanup)
        self.output = Path(self._tmp.name) / "out"

    def export(self, *args, env=None):
        return subprocess.run([str(TOOL), *args, "--output", str(self.output)],
                              capture_output=True, text=True, timeout=300, env=env)

    def assert_exported(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        match = re.match(r"(\d+) tables, (\d+) fichiers", result.stdout)
        self.assertIsNotNone(match, result.stdout)
        tables, files = map(int, match.groups())
        self.assertGreater(tables, 0)
        self.assertEqual(files, tables + 1)  # index.md ou _sequences.sql en plus
        return tables

    def test_markdown(self):
        tables = self.assert_exported(self.export("--format", "markdown"))
        files = sorted(p.name for p in self.output.iterdir())
        self.assertEqual(len(files), tables + 1)
        self.assertIn("index.md", files)
        self.assertIn("users.md", files)
        pages = [name for name in files if name != "index.md"]
        index = (self.output / "index.md").read_text(encoding="utf-8")
        for name in pages:
            with self.subTest(file=name):
                self.assertRegex(name, r"^(resasat_[a-z0-9_$#]+|users)\.md$")
                self.assertIn(f"]({name})", index)
                content = (self.output / name).read_text(encoding="utf-8")
                self.assertTrue(content.startswith(f"# {name[:-3]}\n"))
                self.assertEqual(len(re.findall(r"^# ", content, re.MULTILINE)), 1)
                self.assertIn("## Colonnes", content)
                self.assertNotRegex(content, r"(ORA-\d{5}|SP2-\d{4})")
                # Tous les liens entre tables mènent à un fichier produit
                for target in re.findall(r"\]\(([^)]+\.md)\)", content):
                    self.assertIn(target, files)

    def test_sql(self):
        tables = self.assert_exported(self.export("--format", "sql"))
        files = sorted(p.name for p in self.output.iterdir())
        self.assertEqual(len(files), tables + 1)
        self.assertIn("CREATE SEQUENCE",
                      (self.output / "_sequences.sql").read_text(encoding="utf-8"))
        for name in files:
            if name == "_sequences.sql":
                continue
            with self.subTest(file=name):
                content = (self.output / name).read_text(encoding="utf-8")
                table = name[:-4].upper()
                self.assertEqual(content.count("CREATE TABLE "), 1)
                self.assertIn(f'CREATE TABLE "{table}"', content)
                # Ni schéma, ni attributs physiques, ni message d'erreur
                self.assertNotIn(f'"{tool.DEFAULT_USER.upper()}".', content)
                self.assertNotIn("TABLESPACE", content)
                self.assertNotRegex(content, r"(?m)^(ORA-\d{5}|SP2-\d{4}):")

    @unittest.skipUnless(shutil.which("php"), "php absent")
    def test_json(self):
        result = self.export("--format", "json", "--lang", str(LANGUAGE_FILE))
        self.assertEqual(result.returncode, 0, result.stderr)
        match = re.match(r"(\d+) tables, (\d+) fichiers", result.stdout)
        self.assertIsNotNone(match, result.stdout)
        self.assertEqual(match.group(1), match.group(2))  # un fichier par table, sans index
        files = sorted(self.output.glob("*.json"))
        self.assertEqual(len(files), int(match.group(1)))
        self.assertIn("users.json", [path.name for path in files])
        valid = 0
        for path in files:
            with self.subTest(file=path.name):
                table = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(table["name"], path.stem)
                errors = create_db.validate_table(table, path.stem)
                # Les seules erreurs admises sont les types signalés à l'export
                for error in errors:
                    self.assertIn("inconnu (types acceptés", error)
                    column = error.split()[1]
                    self.assertIn(f"{path.stem}.{column} : type", result.stderr)
                valid += not errors
        self.assertGreater(valid, 0)
        channel = json.loads((self.output / "resasat_channel.json").read_text(encoding="utf-8"))
        self.assertTrue(channel["comment"].startswith("Slot"))

    def test_sql_with_storage(self):
        self.assert_exported(self.export("--format", "sql", "--with-storage"))
        contents = "".join(p.read_text(encoding="utf-8") for p in self.output.glob("*.sql"))
        self.assertIn("TABLESPACE", contents)

    def test_same_tables_in_both_formats(self):
        self.assert_exported(self.export("--format", "markdown"))
        self.assert_exported(self.export("--format", "sql"))
        markdown = {p.stem for p in self.output.glob("*.md")} - {"index"}
        sql = {p.stem for p in self.output.glob("*.sql")} - {"_sequences"}
        self.assertEqual(markdown, sql)
        self.assertIn("users", sql)

    def test_wrong_password_keeps_existing_files(self):
        # Une seule tentative : le compte Oracle se verrouille après plusieurs échecs.
        self.output.mkdir()
        existing = self.output / "resasat_existing.sql"
        existing.write_text("-- à conserver")
        env = dict(os.environ, RESASAT_PASSWORD="mot-de-passe-errone")
        result = self.export("--format", "sql", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ORA-01017", result.stderr)
        self.assertNotIn("mot-de-passe-errone", result.stderr)
        self.assertLessEqual(len(result.stderr.splitlines()), 6)
        self.assertEqual([p.name for p in self.output.iterdir()], ["resasat_existing.sql"])


class LanguageTest(unittest.TestCase):
    """Enrichissement du Markdown, avec un fichier langue déjà lu."""

    def setUp(self):
        self.schema = tool.Schema(tool.split_sections(SAMPLE_OUTPUT))
        self.language = tool.Language(
            labels={"resasat_channel": "Slot", "resasat_stations": "Stations <b>fixes</b>",
                    "resasat_channel_id": "Index", "resasat_channel_name": "Nom abr&eacute;g&eacute;",
                    "resasat_channel_station_fk": "Station",
                    "resasat_channel_owner_fk": "Utilisateur",
                    "resasat_station_id": "&Eacute;tat | validation"},
            # RESASAT_CHANNEL_ID : clé étrangère du fichier langue, sans contrainte dans la base
            masks={"resasat_channel_id": ["FKNOLIST", "resasat_station", "resasat_station_id",
                                          "resasat_station_name"],
                   "resasat_channel_name": ["TEXT", "maxlength=15 size=15"],
                   "resasat_channel_station_fk": ["FKORNULL", "resasat_station",
                                                  "resasat_station_id", "resasat_station_name"],
                   "resasat_channel_owner_fk": ["FK", "users", "ID", "loginname"],
                   "resasat_station_id": ["ENUM", [["0", "Nouveau"], ["1", "Accept&eacute;"],
                                                   ["H", "Horizontale (X)"]]],
                   "resasat_station_start": ["ENUMORNULL",
                                             [[str(n), f"Valeur {n}"] for n in range(1, 12)]]})
        self.files = tool.render_markdown(self.schema, "resaora@essai", self.language, "fr.inc.php")

    def test_labels_are_plain_text(self):
        self.assertEqual(self.language.label("RESASAT_CHANNEL_NAME"), "Nom abrégé")
        self.assertEqual(self.language.label("resasat_unknown"), "")
        self.assertEqual(self.language.table_label("RESASAT_CHANNEL"), "Slot")
        # À défaut du nom de la table, son pluriel
        self.assertEqual(self.language.table_label("RESASAT_STATION"), "Stations fixes")

    def test_masks(self):
        self.assertEqual(self.language.enum_values("RESASAT_STATION_ID"),
                         [("0", "Nouveau"), ("1", "Accepté"), ("H", "Horizontale (X)")])
        self.assertIsNone(self.language.enum_values("RESASAT_CHANNEL_NAME"))
        self.assertEqual(self.language.foreign_key("RESASAT_CHANNEL_STATION_FK"),
                         ("resasat_station", "resasat_station_id"))
        self.assertIsNone(self.language.foreign_key("RESASAT_STATION_ID"))

    def test_table_name(self):
        self.assertTrue(self.files["resasat_channel.md"].startswith(
            "# resasat_channel\n\nNom présenté aux utilisateurs : **Slot**\n\n"
            "Canaux | satellite\n"))
        self.assertIn("Nom présenté aux utilisateurs : **Stations fixes**",
                      self.files["resasat_station.md"])

    def test_column_comments(self):
        page = self.files["resasat_channel.md"]
        # Nom présenté aux utilisateurs, puis commentaire de la base
        self.assertIn("| non |  | **Index** — Clé étrangère vers `resasat_station_id` de "
                      "[resasat_station](resasat_station.md) — Identifiant sur deux lignes |", page)
        self.assertIn("| `'sans nom'` | **Nom abrégé** — L'intitulé |", page)
        # Clé étrangère vers une table exportée : lien ; vers une autre table : texte
        self.assertIn("| **Station** — Clé étrangère vers `resasat_station_id` de "
                      "[resasat_station](resasat_station.md) |", page)
        self.assertIn("| **Utilisateur** — Clé étrangère vers `id` de users |", page)

    def test_short_enum_in_comment(self):
        page = self.files["resasat_station.md"]
        self.assertIn("| **État \\| validation** — Valeurs : `0` = Nouveau, `1` = Accepté, "
                      "`H` = Horizontale (X) |", page)
        self.assertNotIn("## Valeurs de resasat_station_id", page)

    def test_long_enum_in_section(self):
        page = self.files["resasat_station.md"]
        self.assertIn("| Valeurs : voir « Valeurs de resasat_station_start » |", page)
        self.assertIn("## Valeurs de resasat_station_start\n\n| Valeur | Signification |", page)
        self.assertIn("| `11` | Valeur 11 |", page)
        # La section suit le tableau des colonnes
        self.assertLess(page.index("## Valeurs de"), page.index("## Clé primaire"))
        self.assertEqual(len(re.findall(r"^# ", page, re.MULTILINE)), 1)

    def test_foreign_keys_section(self):
        page = self.files["resasat_channel.md"]
        self.assertIn("| Contrainte | Colonnes | Table référencée | Colonnes référencées | "
                      "À la suppression | Active | Origine |", page)
        # Contrainte de la base que le fichier langue déclare aussi : une seule ligne
        self.assertIn("| `resasat_channel_station_fk` | `resasat_channel_station_fk` | "
                      "[resasat_station](resasat_station.md) | `resasat_station_id` | "
                      "`CASCADE` | oui | base et fichier langue |", page)
        self.assertIn("| `resasat_channel_owner_fk` | `resasat_channel_owner_fk` | "
                      "users | `id` | `NO ACTION` | non | base et fichier langue |", page)
        # Clé étrangère connue du seul fichier langue
        self.assertIn("|  | `resasat_channel_id` | [resasat_station](resasat_station.md) | "
                      "`resasat_station_id` |  |  | fichier langue |", page)
        section = page[page.index("## Clés étrangères"):page.index("## Index")]
        self.assertEqual(section.count("resasat_station.md"), 2)

    def test_referenced_by_section(self):
        page = self.files["resasat_station.md"]
        self.assertIn("| Table | Contrainte | Colonnes | Origine |", page)
        self.assertIn("| [resasat_channel](resasat_channel.md) | `resasat_channel_station_fk` | "
                      "`resasat_channel_station_fk` | base et fichier langue |", page)
        self.assertIn("| [resasat_channel](resasat_channel.md) |  | `resasat_channel_id` | "
                      "fichier langue |", page)
        self.assertNotIn("## Clés étrangères", page)

    def test_database_only_foreign_key(self):
        language = tool.Language({}, {})
        page = tool.render_markdown(self.schema, "resaora@essai", language)["resasat_channel.md"]
        self.assertIn("`CASCADE` | oui | base |", page)
        self.assertNotIn("fichier langue |", page)

    def test_index(self):
        index = self.files["index.md"]
        self.assertIn("fichier langue `fr.inc.php`", index)
        self.assertIn("| [resasat_channel](resasat_channel.md) | 4 | "
                      "**Slot** — Canaux \\| satellite |", index)
        self.assertIn("| [resasat_station](resasat_station.md) | 2 | **Stations fixes** |", index)

    def test_without_language_file_nothing_changes(self):
        plain = tool.render_markdown(self.schema, "resaora@essai")
        for name, content in plain.items():
            with self.subTest(file=name):
                self.assertNotIn("**", content)
                self.assertNotIn("fichier langue", content)
                self.assertNotIn("Origine", content)


@unittest.skipUnless(shutil.which("php"), "php absent")
class LanguageFileTest(unittest.TestCase):
    """Lecture par PHP du fichier langue de fixtures/kadlib/."""

    @classmethod
    def setUpClass(cls):
        cls.language = tool.Language.load(LANGUAGE_FILE)

    def test_labels(self):
        self.assertEqual(self.language.label("resasat_channel"), "Slot")
        self.assertEqual(self.language.label("resasat_channel_name"), "Nom abrégé")
        self.assertEqual(self.language.table_label("RESASAT_STATION"), "Stations fixes")
        # Les variables internes du chargeur ne sortent pas
        self.assertFalse([name for name in self.language.labels if name.startswith("_")])

    def test_constants_and_variables_are_evaluated(self):
        # $snl vient de defines.inc.php, KADLIB_WHERE_CLAUSE de kadlib-defines.inc.php
        self.assertEqual(self.language.masks["resasat_channel_name"],
                         ["TEXT", "maxlength=15 size=15"])
        self.assertEqual(self.language.masks["resasat_channel_station_fk"],
                         ["FKORNULL", "resasat_station", "resasat_station_id",
                          "resasat_station_name"])
        self.assertEqual(self.language.foreign_key("RESASAT_CHANNEL_OWNER_FK"), ("users", "ID"))

    def test_enum_keys(self):
        # Constantes connues remplacées par leur valeur, constante inconnue gardée par son nom
        self.assertEqual(self.language.enum_values("RESASAT_STATION_ID"),
                         [("0", "Nouveau"), ("1", "Accepté"), ("CHANNEL_UNKNOWN", "Inconnu"),
                          ("H", "Horizontale (X)")])
        self.assertEqual(self.language.unknown_constants, ["CHANNEL_UNKNOWN"])
        self.assertEqual(len(self.language.enum_values("RESASAT_STATION_START")), 11)

    def test_missing_file(self):
        with self.assertRaises(tool.ExportError):
            tool.Language.load(LANGUAGE_FILE.with_name("absent.inc.php"))

    def test_php_error(self):
        with tempfile.TemporaryDirectory(prefix="test-export-oracle-db-") as tmp:
            broken = Path(tmp) / "app" / "lang" / "fr.inc.php"
            broken.parent.mkdir(parents=True)
            broken.write_text('<?php\n$resasat_x = undefined_function();\n')
            with self.assertRaises(tool.ExportError) as context:
                tool.Language.load(broken)
            self.assertIn("undefined_function", str(context.exception))


class LanguageCommandLineTest(unittest.TestCase):

    def test_lang_is_not_for_sql(self):
        result = subprocess.run([str(TOOL), "--format", "sql", "--lang", str(LANGUAGE_FILE)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--lang", result.stderr)

    def test_missing_language_file_stops_before_the_database(self):
        with tempfile.TemporaryDirectory(prefix="test-export-oracle-db-") as tmp:
            # ORACLE_HOME vide : une tentative de connexion donnerait une autre erreur
            env = dict(os.environ, ORACLE_HOME=tmp, RESASAT_PASSWORD="sans-objet")
            result = subprocess.run(
                [str(TOOL), "--format", "markdown", "--lang", str(Path(tmp) / "absent.php"),
                 "--output", str(Path(tmp) / "out")],
                capture_output=True, text=True, timeout=30, env=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn("fichier langue introuvable", result.stderr)
            self.assertFalse((Path(tmp) / "out").exists())


if __name__ == "__main__":
    unittest.main()
