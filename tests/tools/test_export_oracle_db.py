#!/usr/bin/env python3.11
"""Tests de tools/export-oracle-db.py.

Deux familles :

* sans base : l'analyse de la sortie de sqlplus et la production des fichiers,
  à partir d'une sortie d'essai écrite dans ce fichier ;
* avec la base RESASAT : l'outil est lancé comme le ferait un utilisateur. Ces
  tests sont sautés si la variable RESASAT_PASSWORD ou sqlplus sont absents.

Lancement, depuis la racine du dépôt :

    python3.11 -m unittest discover -s tests/tools -v
"""

import importlib.util
import os
import re
import subprocess
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOL = ROOT / "tools" / "export-oracle-db.py"


def load_tool():
    """Charge l'outil comme un module (son nom contient des tirets)."""
    loader = SourceFileLoader("export_oracle_db", str(TOOL))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


tool = load_tool()

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

    def test_only_prefixed_objects(self):
        script = tool.build_script(with_ddl=True, with_storage=False)
        self.assertIn(r"LIKE 'RESASAT\_%' ESCAPE '\'", script)


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
        result = subprocess.run([str(TOOL), "--format", "json"],
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
        pages = [name for name in files if name != "index.md"]
        index = (self.output / "index.md").read_text(encoding="utf-8")
        for name in pages:
            with self.subTest(file=name):
                self.assertRegex(name, r"^resasat_[a-z0-9_$#]+\.md$")
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

    def test_sql_with_storage(self):
        self.assert_exported(self.export("--format", "sql", "--with-storage"))
        contents = "".join(p.read_text(encoding="utf-8") for p in self.output.glob("resasat_*.sql"))
        self.assertIn("TABLESPACE", contents)

    def test_same_tables_in_both_formats(self):
        self.assert_exported(self.export("--format", "markdown"))
        self.assert_exported(self.export("--format", "sql"))
        markdown = {p.stem for p in self.output.glob("resasat_*.md")}
        sql = {p.stem for p in self.output.glob("resasat_*.sql")}
        self.assertEqual(markdown, sql)

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


if __name__ == "__main__":
    unittest.main()
