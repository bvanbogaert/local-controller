#!/usr/bin/env python3.11
"""Tests de tools/create-db.py.

Chaque test écrit un modèle de données d'essai dans un répertoire temporaire et
lance l'outil sur une base DuckDB temporaire. Les tests qui ouvrent une base
sont sautés si le module duckdb est absent.

Lancement, depuis la racine du dépôt :

    .venv/bin/python -m unittest discover -s tests/tools -v
"""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

try:
    import duckdb
except ImportError:
    duckdb = None

ROOT = Path(__file__).resolve().parent.parent.parent
TOOL = ROOT / "tools" / "create-db.py"
DATAMODEL = ROOT / "datamodel"


def load_tool():
    """Charge l'outil comme un module (son nom contient un tiret)."""
    loader = SourceFileLoader("create_db", str(TOOL))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    # Les dataclasses cherchent leur module dans sys.modules
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


tool = load_tool()


def column(name, kind="int", nullable=True, **fields):
    result = {"name": name, "comment": "", "type": kind, "nullable": nullable,
              "default": None, "auto_increment": False}
    if kind == "varchar":
        result["length"] = 20
    result.update(fields)
    return result


def station():
    """Table d'essai : clé auto-incrémentée, valeurs par défaut, deux index."""
    return {
        "name": "station",
        "comment": "Station d'essai",
        "columns": [
            column("station_id", nullable=False, auto_increment=True, comment="Index"),
            column("station_name", "varchar", comment="Nom de l'antenne"),
            column("station_start", "bigint", default=0),
            column("station_gain", "double", default=1.5),
            column("station_kind", "varchar", default="fixe",
                   values={"fixe": "Fixe", "dsng": "Mobile"}),
            column("station_region_fk",
                   references={"table": "region", "column": "region_id"}),
        ],
        "primary_key": ["station_id"],
        "indexes": [
            {"name": "idx_station_name", "unique": True, "columns": ["station_name"]},
            {"name": "idx_station_start", "unique": False,
             "columns": ["station_start", "station_region_fk"]},
        ],
    }


def region():
    """Table d'essai sans index, à clé primaire composée."""
    return {
        "name": "region",
        "comment": "",
        "columns": [column("region_id", nullable=False), column("region_zone", nullable=False),
                    column("region_name", "varchar")],
        "primary_key": ["region_id", "region_zone"],
        "indexes": [],
    }


class ToolTestCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="test-create-db-")
        self.addCleanup(self._tmp.cleanup)
        self.datamodel = Path(self._tmp.name) / "datamodel"
        self.datamodel.mkdir()
        self.database = Path(self._tmp.name) / "db" / "essai.duckdb"

    def write(self, *tables):
        """Remplace le modèle de données par les tables données."""
        for path in self.datamodel.glob("*.json"):
            path.unlink()
        for table in tables:
            (self.datamodel / f"{table['name']}.json").write_text(
                json.dumps(table, ensure_ascii=False), encoding="utf-8")

    def run_tool(self, *args):
        """Lance l'outil ; retourne (code de retour, sortie standard, sortie d'erreur)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tool.main(["--db", str(self.database), "--datamodel", str(self.datamodel),
                              *args])
        return code, out.getvalue(), err.getvalue()

    def query(self, sql, parameters=()):
        connection = duckdb.connect(str(self.database), read_only=True)
        try:
            return connection.execute(sql, parameters).fetchall()
        finally:
            connection.close()

    def execute(self, *statements):
        connection = duckdb.connect(str(self.database))
        try:
            for statement in statements:
                connection.execute(statement)
        finally:
            connection.close()

    def columns(self, table):
        return self.query("SELECT column_name, data_type, is_nullable, column_default "
                          "FROM duckdb_columns() WHERE table_name = ? ORDER BY column_index",
                          [table])

    def assert_conform(self):
        """Une nouvelle exécution ne trouve plus rien à faire."""
        code, out, err = self.run_tool()
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Base conforme", out)


class ValidationTest(ToolTestCase):
    """Le modèle est validé avant d'ouvrir la base : duckdb n'est pas nécessaire."""

    def assert_invalid(self, table, *messages, stem=None):
        self.write()
        (self.datamodel / f"{stem or table['name']}.json").write_text(json.dumps(table))
        code, out, err = self.run_tool()
        self.assertEqual(code, 2, err)
        self.assertIn("modèle de données invalide", err)
        for message in messages:
            self.assertIn(message, err)
        self.assertFalse(self.database.exists())

    def test_valid_tables(self):
        self.assertEqual(tool.validate_table(station(), "station"), [])
        self.assertEqual(tool.validate_table(region(), "region"), [])

    def test_optional_fields(self):
        table = {"name": "t", "columns": [{"name": "a", "type": "int", "nullable": True}],
                 "primary_key": [], "indexes": []}
        self.assertEqual(tool.validate_table(table, "t"), [])
        normalized = tool.normalize(table)
        self.assertEqual(normalized["comment"], "")
        self.assertEqual(normalized["columns"][0],
                         {"name": "a", "comment": "", "type": "int", "length": None,
                          "nullable": True, "default": None, "auto_increment": False})

    def test_unreadable_json(self):
        (self.datamodel / "station.json").write_text("{ pas du json")
        code, _, err = self.run_tool()
        self.assertEqual(code, 2)
        self.assertIn("station.json : fichier illisible", err)

    def test_missing_directory_and_empty_directory(self):
        code, _, err = self.run_tool()
        self.assertEqual(code, 2)
        self.assertIn("aucun fichier .json", err)
        self.datamodel.rmdir()
        code, _, err = self.run_tool()
        self.assertEqual(code, 2)
        self.assertIn("introuvable", err)

    def test_file_name_is_the_table_name(self):
        self.assert_invalid(station(), "il doit être le nom du fichier, « stations »",
                            stem="stations")

    def test_unknown_type(self):
        table = station()
        table["columns"][1]["type"] = "VARCHAR2(20 CHAR)"
        self.assert_invalid(table, "colonne station_name : type 'VARCHAR2(20 CHAR)' inconnu")

    def test_varchar_needs_a_length(self):
        table = station()
        del table["columns"][1]["length"]
        self.assert_invalid(table, "colonne station_name : « length »")
        table = station()
        table["columns"][2]["length"] = 10
        self.assert_invalid(table, "« length » ne s'applique pas au type bigint")

    def test_primary_key(self):
        table = station()
        table["primary_key"] = ["station_uid"]
        self.assert_invalid(table, "clé primaire : colonne station_uid inconnue")
        table = station()
        table["primary_key"] = ["station_name"]
        self.assert_invalid(table, "la colonne station_name doit avoir « nullable » à false")

    def test_index(self):
        table = station()
        table["indexes"][0]["columns"] = ["station_nam"]
        del table["indexes"][1]["unique"]
        self.assert_invalid(table, "index idx_station_name : colonne station_nam inconnue",
                            "index idx_station_start : « unique »")

    def test_format(self):
        table = station()
        table["columns"][2]["format"] = "datetime"
        table["columns"][5]["format"] = "yes_no"
        self.assertEqual(tool.validate_table(table, "station"), [])
        table["columns"][1]["format"] = "yes_no"
        table["columns"][2]["format"] = "date"
        self.assert_invalid(table, "colonne station_name : « format » demande un type entier",
                            "colonne station_start : « format » 'date' inconnu")

    def test_default_and_auto_increment(self):
        table = station()
        table["columns"][2]["default"] = "zéro"
        table["columns"][1]["auto_increment"] = True
        table["columns"][0]["default"] = 1
        self.assert_invalid(
            table, "colonne station_start : la valeur par défaut 'zéro' n'est pas du type bigint",
            "colonne station_name : « auto_increment » demande un type entier",
            "colonne station_id : « auto_increment » et « default » sont incompatibles")

    def test_all_errors_are_listed(self):
        table = station()
        table["columns"].append(column("station_name", "varchar"))
        table["columns"].append(column("Station-X"))
        table["columns"][0]["nullabel"] = False
        table["extra"] = 1
        self.assert_invalid(table, "colonne station_name : colonne déclarée deux fois",
                            "colonne n° 8 : « name » doit être un identifiant",
                            "colonne station_id : champ inconnu « nullabel »",
                            "champ inconnu « extra »")

    def test_names_are_unique_across_tables(self):
        first, second = station(), region()
        second["indexes"] = [{"name": "idx_station_name", "unique": False,
                              "columns": ["region_name"]}]
        self.write(first, second)
        code, _, err = self.run_tool()
        self.assertEqual(code, 2)
        self.assertIn("le nom idx_station_name (index de station) est déjà pris", err)

    def test_sequence_name(self):
        table = tool.normalize(station())
        self.assertEqual(tool.sequence_name(table, table["columns"][0]), "station_id_seq")
        users = {"name": "users"}
        self.assertEqual(tool.sequence_name(users, {"name": "id"}), "users_id_seq")


@unittest.skipUnless(duckdb, "module duckdb absent")
class CreationTest(ToolTestCase):

    def setUp(self):
        super().setUp()
        self.write(station(), region())
        self.result = self.run_tool()

    def test_report(self):
        code, out, err = self.result
        self.assertEqual((code, err), (0, ""))
        self.assertIn("region : table créée\nstation : table créée\n", out)
        self.assertIn("2 tables dans le modèle, 2 modifications appliquées", out)

    def test_columns(self):
        self.assertEqual(self.columns("station"), [
            ("station_id", "INTEGER", False, "nextval('station_id_seq')"),
            ("station_name", "VARCHAR", True, None),
            ("station_start", "BIGINT", True, "0"),
            ("station_gain", "DOUBLE", True, "1.5"),
            ("station_kind", "VARCHAR", True, "'fixe'"),
            ("station_region_fk", "INTEGER", True, None)])

    def test_primary_keys(self):
        keys = dict(self.query("SELECT table_name, constraint_column_names "
                               "FROM duckdb_constraints() WHERE constraint_type = 'PRIMARY KEY'"))
        self.assertEqual(keys, {"station": ["station_id"],
                                "region": ["region_id", "region_zone"]})

    def test_indexes(self):
        indexes = self.query("SELECT index_name, table_name, is_unique FROM duckdb_indexes() "
                             "ORDER BY index_name")
        self.assertEqual(indexes, [("idx_station_name", "station", True),
                                   ("idx_station_start", "station", False)])
        self.execute("INSERT INTO station (station_name) VALUES ('Amiens')")
        with self.assertRaises(duckdb.ConstraintException):
            self.execute("INSERT INTO station (station_name) VALUES ('Amiens')")

    def test_comments(self):
        self.assertEqual(self.query("SELECT table_name, comment FROM duckdb_tables() ORDER BY 1"),
                         [("region", None), ("station", "Station d'essai")])
        comments = dict(self.query("SELECT column_name, comment FROM duckdb_columns() "
                                   "WHERE table_name = 'station'"))
        self.assertEqual(comments["station_name"], "Nom de l'antenne")
        self.assertIsNone(comments["station_start"])

    def test_auto_increment_and_defaults(self):
        self.execute("INSERT INTO station (station_name) VALUES ('Amiens')",
                     "INSERT INTO station (station_name) VALUES ('Bastia')")
        self.assertEqual(self.query("SELECT station_id, station_name, station_start, station_gain,"
                                    " station_kind FROM station ORDER BY 1"),
                         [(1, "Amiens", 0, 1.5, "fixe"), (2, "Bastia", 0, 1.5, "fixe")])

    def test_second_run_changes_nothing(self):
        before = self.database.read_bytes()
        self.assert_conform()
        self.assertEqual(self.database.read_bytes(), before)

    def test_varchar_length_is_not_tracked(self):
        # Limite connue : DuckDB ne conserve pas la largeur d'un VARCHAR
        table = station()
        table["columns"][1]["length"] = 99
        self.write(table, region())
        self.assert_conform()


@unittest.skipUnless(duckdb, "module duckdb absent")
class UpdateTest(ToolTestCase):

    def setUp(self):
        super().setUp()
        self.table = station()
        self.write(self.table, region())
        self.run_tool()
        self.execute("INSERT INTO station (station_name, station_start, station_gain) "
                     "VALUES ('Amiens', 10, 2.5), ('Bastia', 20, 3.7)")

    def update(self, *args):
        self.write(self.table, region())
        return self.run_tool(*args)

    def names(self):
        return self.query("SELECT station_id, station_name FROM station ORDER BY 1")

    # --- Sans --force : ajouts, valeurs par défaut, commentaires, index

    def test_added_column(self):
        self.table["columns"].append(column("station_ip", "varchar", default="0.0.0.0",
                                            comment="Adresse IP"))
        self.table["columns"].append(column("station_seq", "bigint"))
        code, out, err = self.update()
        self.assertEqual((code, err), (0, ""))
        self.assertIn("station : colonne station_ip ajoutée", out)
        self.assertEqual(self.query("SELECT station_name, station_ip, station_seq FROM station "
                                    "ORDER BY station_id"),
                         [("Amiens", "0.0.0.0", None), ("Bastia", "0.0.0.0", None)])
        self.assertEqual(self.query("SELECT comment FROM duckdb_columns() "
                                    "WHERE column_name = 'station_ip'"), [("Adresse IP",)])
        self.assert_conform()

    def test_new_table(self):
        extra = region()
        extra["name"] = "zone"
        self.write(self.table, region(), extra)
        code, out, _ = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "zone : table créée")
        self.assertEqual(self.names(), [(1, "Amiens"), (2, "Bastia")])

    def test_defaults(self):
        self.table["columns"][2]["default"] = 5        # modifiée
        self.table["columns"][3]["default"] = None     # retirée
        self.table["columns"][1]["default"] = "x'y"    # ajoutée
        code, out, err = self.update()
        self.assertEqual((code, err), (0, ""))
        self.assertIn("valeur par défaut de station_start : 0 → 5", out)
        self.assertIn("valeur par défaut de station_gain : 1.5 → aucune", out)
        defaults = {name: default for name, _, _, default in self.columns("station")}
        self.assertEqual((defaults["station_start"], defaults["station_gain"],
                          defaults["station_name"]), ("5", None, "'x''y'"))
        self.assert_conform()

    def test_comments(self):
        self.table["comment"] = "Antenne"
        self.table["columns"][1]["comment"] = ""
        self.table["columns"][2]["comment"] = "Début"
        code, out, _ = self.update()
        self.assertEqual(code, 0)
        self.assertIn("commentaire de la table modifié", out)
        self.assertEqual(self.query("SELECT comment FROM duckdb_tables() "
                                    "WHERE table_name = 'station'"), [("Antenne",)])
        comments = dict(self.query("SELECT column_name, comment FROM duckdb_columns() "
                                   "WHERE table_name = 'station'"))
        self.assertEqual((comments["station_name"], comments["station_start"]), (None, "Début"))
        self.assert_conform()

    def test_indexes(self):
        self.table["indexes"] = [
            {"name": "idx_station_name", "unique": False, "columns": ["station_name"]},
            {"name": "idx_station_kind", "unique": False, "columns": ["station_kind"]}]
        code, out, err = self.update()
        self.assertEqual((code, err), (0, ""))
        for line in ("index idx_station_start supprimé", "index idx_station_name recréé",
                     "index idx_station_kind créé"):
            self.assertIn(line, out)
        self.assertEqual(self.query("SELECT index_name, is_unique FROM duckdb_indexes() "
                                    "ORDER BY 1"),
                         [("idx_station_kind", False), ("idx_station_name", False)])
        self.assert_conform()

    def test_auto_increment_added_in_place(self):
        other = region()
        other["columns"].append(column("region_seq", auto_increment=True))
        self.execute("INSERT INTO region VALUES (1, 1, 'Nord')")
        self.write(self.table, other)
        code, out, err = self.run_tool()
        self.assertEqual((code, err), (0, ""))
        self.assertIn("region : colonne region_seq ajoutée", out)
        self.execute("INSERT INTO region (region_id, region_zone) VALUES (2, 1)")
        # La ligne présente est numérotée à l'ajout de la colonne, la suivante continue
        self.assertEqual(self.query("SELECT region_id, region_seq FROM region ORDER BY 1"),
                         [(1, 1), (2, 2)])
        self.assert_conform()

    def test_nullable_again_needs_no_force(self):
        # La reconstruction qui rend NULL à une colonne ne perd rien : pas de --force
        other = region()
        other["columns"][1]["nullable"] = True
        other["primary_key"] = ["region_id"]
        self.assertEqual(
            tool.Planner.rebuild_reasons(
                tool.normalize(other),
                {"columns": {"region_id": {"type": "INTEGER", "nullable": False},
                             "region_zone": {"type": "INTEGER", "nullable": False},
                             "region_name": {"type": "VARCHAR", "nullable": True}},
                 "primary_key": ["region_id"]}),
            [("region_zone accepte NULL", False)])

    # --- Modifications qui demandent --force

    def test_without_force_nothing_is_lost(self):
        del self.table["columns"][3]                    # station_gain
        self.table["columns"][1]["comment"] = "Nom"     # en attente avec le reste de la table
        before = self.columns("station")
        code, out, err = self.update()
        self.assertEqual(code, 1)
        self.assertIn("à relancer avec --force", err)
        self.assertIn("station : table reconstruite : colonne station_gain en trop", err)
        self.assertNotIn("station", out)
        self.assertEqual(self.columns("station"), before)
        self.assertEqual(self.query("SELECT station_gain FROM station ORDER BY station_id"),
                         [(2.5,), (3.7,)])

    def test_dropped_column(self):
        del self.table["columns"][3]
        code, out, err = self.update("--force")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("station : table reconstruite : colonne station_gain en trop", out)
        self.assertNotIn("station_gain", [name for name, *_ in self.columns("station")])
        self.assertEqual(self.names(), [(1, "Amiens"), (2, "Bastia")])
        # Index et commentaires sont recréés, la séquence continue
        self.assertEqual(len(self.query("SELECT 1 FROM duckdb_indexes()")), 2)
        self.assertEqual(self.query("SELECT comment FROM duckdb_tables() "
                                    "WHERE table_name = 'station'"), [("Station d'essai",)])
        self.execute("INSERT INTO station (station_name) VALUES ('Caen')")
        self.assertEqual(self.names()[-1], (3, "Caen"))
        self.assert_conform()

    def test_changed_type(self):
        self.table["columns"][2] = column("station_start", "varchar", length=20)
        self.table["columns"][3] = column("station_gain", "int")
        code, out, _ = self.update("--force")
        self.assertEqual(code, 0)
        self.assertIn("type de station_start BIGINT → VARCHAR", out)
        self.assertEqual(self.query("SELECT station_start, station_gain FROM station "
                                    "ORDER BY station_id"), [("10", 2), ("20", 4)])
        self.assert_conform()

    def test_changed_primary_key_and_not_null(self):
        self.table["columns"][1]["nullable"] = False
        self.table["primary_key"] = ["station_id", "station_name"]
        code, out, _ = self.update("--force")
        self.assertEqual(code, 0)
        self.assertIn("station_name devient NOT NULL", out)
        self.assertIn("clé primaire (station_id) → (station_id, station_name)", out)
        self.assertEqual(self.query("SELECT constraint_column_names FROM duckdb_constraints() "
                                    "WHERE table_name = 'station' "
                                    "AND constraint_type = 'PRIMARY KEY'"),
                         [(["station_id", "station_name"],)])
        self.assertEqual(self.names(), [(1, "Amiens"), (2, "Bastia")])
        self.assert_conform()

    def test_new_not_null_column(self):
        self.table["columns"].append(column("station_rank", nullable=False, default=7))
        code, _, err = self.update()
        self.assertEqual(code, 1)
        self.assertIn("nouvelle colonne station_rank NOT NULL", err)
        code, _, _ = self.update("--force")
        self.assertEqual(code, 0)
        self.assertEqual(self.query("SELECT DISTINCT station_rank FROM station"), [(7,)])

    def test_auto_increment_removed(self):
        self.table["columns"][0]["auto_increment"] = False
        code, out, err = self.update()
        self.assertEqual((code, err), (0, ""))
        self.assertIn("station_id_seq : séquence supprimée", out)
        self.assertEqual(self.query("SELECT count(*) FROM duckdb_sequences()"), [(0,)])
        self.assert_conform()
        # Rétablie, la séquence reprend après le plus grand identifiant
        self.table["columns"][0]["auto_increment"] = True
        self.assertEqual(self.update()[0], 0)
        self.execute("INSERT INTO station (station_name) VALUES ('Caen')")
        self.assertEqual(self.names()[-1], (3, "Caen"))

    def test_extra_table(self):
        self.write(self.table)
        code, _, err = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("region : table supprimée (absente du modèle de données)", err)
        self.assertEqual(len(self.query("SELECT 1 FROM duckdb_tables()")), 2)
        code, _, _ = self.run_tool("--force")
        self.assertEqual(code, 0)
        self.assertEqual(self.query("SELECT table_name FROM duckdb_tables()"), [("station",)])

    def test_pending_change_does_not_block_other_tables(self):
        del self.table["columns"][3]
        other = region()
        other["columns"].append(column("region_code", "varchar"))
        self.write(self.table, other)
        code, out, err = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("region : colonne region_code ajoutée", out)
        self.assertIn("colonne station_gain en trop", err)
        self.assertIn("region_code", [name for name, *_ in self.columns("region")])

    def test_failed_update_is_rolled_back(self):
        # « Amiens » ne se convertit pas en entier : rien ne doit rester de la tentative
        other = region()
        other["columns"].append(column("region_code", "varchar"))
        self.table["columns"][1] = column("station_name", "int")
        self.table["indexes"] = self.table["indexes"][1:]
        self.write(self.table, other)
        before = self.columns("station"), self.columns("region")
        code, _, err = self.run_tool("--force")
        self.assertEqual(code, 2)
        self.assertIn("la transaction est annulée", err)
        self.assertIn("Amiens", err)
        self.assertEqual((self.columns("station"), self.columns("region")), before)
        self.assertEqual(self.names(), [(1, "Amiens"), (2, "Bastia")])
        self.assertEqual(self.query("SELECT table_name FROM duckdb_tables() ORDER BY 1"),
                         [("region",), ("station",)])


@unittest.skipUnless(duckdb, "module duckdb absent")
class DryRunTest(ToolTestCase):

    def test_database_is_not_created(self):
        self.write(station())
        code, out, err = self.run_tool("--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertIn('    CREATE SEQUENCE "station_id_seq" START 1;', out)
        self.assertIn('    CREATE TABLE "station" (\n      "station_id" INTEGER DEFAULT '
                      "nextval('station_id_seq') NOT NULL,", out)
        self.assertIn('      "station_name" VARCHAR(20),', out)
        self.assertIn('    CREATE UNIQUE INDEX "idx_station_name" ON "station" ("station_name");',
                      out)
        self.assertIn("""    COMMENT ON TABLE "station" IS 'Station d''essai';""", out)
        self.assertIn("1 modifications à faire", out)
        self.assertFalse(self.database.parent.exists())

    def test_database_is_not_modified(self):
        table = station()
        self.write(table)
        self.run_tool()
        before = self.database.read_bytes()
        del table["columns"][3]
        table["columns"].append(column("station_ip", "varchar"))
        self.write(table)
        code, out, _ = self.run_tool("--dry-run", "--force")
        self.assertEqual(code, 0)
        self.assertIn('ALTER TABLE "station__new" RENAME TO "station";', out)
        self.assertEqual(self.database.read_bytes(), before)


@unittest.skipUnless(DATAMODEL.is_dir(), "datamodel/ absent")
class DatamodelTest(ToolTestCase):
    """Les fichiers livrés dans datamodel/."""

    def test_files_are_valid(self):
        model = tool.load_datamodel(DATAMODEL)
        self.assertEqual(len(model), 15)
        for name in ("resasat_station", "resasat_station_type", "resasat_reservation", "users"):
            self.assertIn(name, model)
        # Fichiers tels que les écrit tools/export-oracle-db.py --format json
        for path in DATAMODEL.glob("*.json"):
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertEqual(text, json.dumps(json.loads(text), ensure_ascii=False,
                                                  indent=2) + "\n")

    @unittest.skipUnless(duckdb, "module duckdb absent")
    def test_database_is_created(self):
        self.datamodel = DATAMODEL
        code, _, err = self.run_tool()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.query("SELECT count(*) FROM duckdb_tables()"), [(15,)])
        model = tool.load_datamodel(DATAMODEL)
        counts = dict(self.query("SELECT table_name, column_count FROM duckdb_tables()"))
        self.assertEqual(counts, {name: len(table["columns"]) for name, table in model.items()})
        self.assert_conform()


if __name__ == "__main__":
    unittest.main()
