#!/usr/bin/env python3.11
"""Tests de l'import de la configuration (backend/local_controller/configuration/).

Chaque test part d'une base DuckDB temporaire créée à partir du modèle de
données du dépôt, et dépose par l'API un petit fichier d'essai au format de
l'export de RESASAT. Les tests sont sautés si duckdb ou fastapi sont absents.

Lancement, depuis la racine du dépôt :

    .venv/bin/python -m unittest discover -s tests -v
"""

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

try:
    import duckdb
    from fastapi.testclient import TestClient
    from local_controller.configuration import importer
    from local_controller.datamodel import load_datamodel
    from local_controller.main import create_app
except ImportError:
    duckdb = None

DATAMODEL = ROOT / "datamodel"
PAST = 1_000_000_000      # 2001
FUTURE = 4_102_444_800    # 2100
URL = "/api/configuration/import"


def load_create_db():
    """Charge tools/create-db.py comme un module (son nom contient un tiret)."""
    loader = SourceFileLoader("create_db", str(ROOT / "tools" / "create-db.py"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def sample():
    """Configuration d'essai : enregistrements par table, valeurs en chaînes
    comme dans l'export de RESASAT."""
    return {
        "resasat_region": [
            {"resasat_region_id": "1", "resasat_region_name": "Nord"},
            {"resasat_region_id": "2", "resasat_region_name": "Sud"}],
        "resasat_operator": [
            {"resasat_operator_id": "1", "resasat_operator_name": "Eutelsat"}],
        "resasat_satelite": [
            {"resasat_satelite_id": "1", "resasat_satelite_name": "E8WB",
             "resasat_satelite_position": "-8", "resasat_satelite_end": str(FUTURE)},
            {"resasat_satelite_id": "2", "resasat_satelite_name": "Ancien",
             "resasat_satelite_position": "7.5", "resasat_satelite_end": str(PAST)}],
        "resasat_profile": [
            {"resasat_profile_id": "1", "resasat_profile_name": "P-actif",
             "resasat_profile_end": str(FUTURE), "resasat_profile_is_foreign": "0"},
            # Expiré, mais utilisé par le slot 10 : gardé par la fermeture
            {"resasat_profile_id": "2", "resasat_profile_name": "P-expiré",
             "resasat_profile_end": str(PAST), "resasat_profile_is_foreign": None},
            {"resasat_profile_id": "3", "resasat_profile_name": "P-rainbow",
             "resasat_profile_end": str(FUTURE), "resasat_profile_is_foreign": "2"}],
        "resasat_station_type": [
            {"resasat_station_type_id": "1", "resasat_station_type_name": "DSNG"}],
        "resasat_station": [
            {"resasat_station_id": "1", "resasat_station_name": "Amiens",
             "resasat_station_type_fk": "1", "resasat_station_region_fk": "1",
             "resasat_station_station_fk": "4", "resasat_station_receiver": "1",
             "resasat_station_is_foreign": "0", "resasat_station_end": None},
            {"resasat_station_id": "2", "resasat_station_name": "Fermée",
             "resasat_station_is_foreign": "0", "resasat_station_end": str(PAST)},
            {"resasat_station_id": "3", "resasat_station_name": "Globecast",
             "resasat_station_is_foreign": "1", "resasat_station_end": str(FUTURE)},
            # Expirée, mais station de réception d'Amiens : gardée par la fermeture
            {"resasat_station_id": "4", "resasat_station_name": "Relais",
             "resasat_station_is_foreign": None, "resasat_station_end": str(PAST)}],
        "resasat_channel": [
            {"resasat_channel_id": "10", "resasat_channel_name": "Perm 1",
             "resasat_channel_start": "63064800", "resasat_channel_end": str(FUTURE),
             "resasat_channel_permanent": "1", "resasat_channel_satelite_fk": "1",
             "resasat_channel_polarisation": "H", "resasat_channel_video_rx_frequ": "12700.30",
             "resasat_channel_user_fk": "346", "resasat_channel_profile_fk": "2",
             "resasat_channel_is_foreign": None},
            {"resasat_channel_id": "11", "resasat_channel_name": "Ancien slot",
             "resasat_channel_end": str(PAST), "resasat_channel_satelite_fk": "2",
             "resasat_channel_is_foreign": "0"},
            {"resasat_channel_id": "12", "resasat_channel_name": "Rainbow",
             "resasat_channel_end": str(FUTURE), "resasat_channel_profile_fk": "3",
             "resasat_channel_is_foreign": "2"}],
        "resasat_st2c": [
            {"resasat_st2c_id": "100", "resasat_st2c_station_type_fk": "1",
             "resasat_st2c_channel_fk": "10"},
            {"resasat_st2c_id": "101", "resasat_st2c_station_type_fk": "1",
             "resasat_st2c_channel_fk": "11"},
            {"resasat_st2c_id": "102", "resasat_st2c_station_type_fk": "1",
             "resasat_st2c_channel_fk": "12"}],
        # Jamais importées
        "users": [{"id": "346", "loginname": "dupont", "pw": "empreinte"}],
        "resasat_s2c": [{"resasat_s2c_id": "1", "resasat_s2c_station_fk": "1",
                         "resasat_s2c_channel_fk": "10"}],
    }


def export(tables, **header):
    """Fichier au format de l'export de RESASAT : colonnes, puis lignes en tableaux."""
    content = {"format": "resasat-configuration", "version": 1, "date": 1794853110, "tables": {}}
    content.update(header)
    for name, records in tables.items():
        columns = list(dict.fromkeys(column for record in records for column in record))
        content["tables"][name] = {
            "columns": columns,
            "rows": [[record.get(column) for column in columns] for record in records]}
    return json.dumps(content, ensure_ascii=False).encode("utf-8")


@unittest.skipUnless(duckdb, "modules duckdb ou fastapi absents")
class ImportTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # La base vide est créée une fois, puis copiée pour chaque test.
        cls._class_tmp = tempfile.TemporaryDirectory(prefix="test-configuration-import-")
        cls.addClassCleanup(cls._class_tmp.cleanup)
        cls.template = Path(cls._class_tmp.name) / "vide.duckdb"
        create_db = load_create_db()
        with contextlib.redirect_stdout(io.StringIO()):
            create_db.synchronize(create_db.load_datamodel(DATAMODEL), cls.template)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="test-configuration-import-")
        self.addCleanup(self._tmp.cleanup)
        directory = Path(self._tmp.name)
        self.database = directory / "essai.duckdb"
        self.database.write_bytes(self.template.read_bytes())
        self.import_dir = directory / "import"
        environment = {"LOCAL_CONTROLLER_DATABASE": str(self.database),
                       "LOCAL_CONTROLLER_DATAMODEL": str(DATAMODEL),
                       "LOCAL_CONTROLLER_IMPORT_DIR": str(self.import_dir),
                       "LOCAL_CONTROLLER_FRONTEND": str(directory / "absent")}
        for name, value in environment.items():
            self.addCleanup(os.environ.pop, name, None)
            os.environ[name] = value
        self.client = TestClient(create_app())

    def upload(self, tables=None, period="all", origin="all", content=None, fields=None):
        """Dépose un fichier ; sans filtre par défaut, pour comparer tout le fichier."""
        data = {"period": period, "origin": origin} if fields is None else fields
        return self.client.post(
            URL, data=data,
            files={"file": ("configuration.json",
                            export(sample() if tables is None else tables)
                            if content is None else content, "application/json")})

    def comparison(self, *args, **kwargs):
        response = self.upload(*args, **kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    @staticmethod
    def table(comparison, name):
        return next(table for table in comparison["tables"] if table["name"] == name)

    def ids(self, comparison, action="inserts"):
        return {table["name"].replace("resasat_", ""): [item["id"] for item in table[action]]
                for table in comparison["tables"] if table[action]}

    @staticmethod
    def keys(comparison, *actions):
        """Clés des cases à cocher des actions données."""
        keys = []
        for table in comparison["tables"]:
            for action in actions:
                for item in table[action]:
                    keys += ([field["key"] for field in item["fields"]] if action == "updates"
                             else [item["key"]])
        return keys

    def apply(self, comparison, selection):
        return self.client.post(f"{URL}/{comparison['token']}/apply",
                                json={"selection": selection})

    def import_all(self, tables=None):
        """Importe tous les ajouts et modifications d'un fichier, sans filtre."""
        comparison = self.comparison(tables)
        response = self.apply(comparison, self.keys(comparison, "inserts", "updates"))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def query(self, sql, parameters=()):
        connection = duckdb.connect(str(self.database))
        try:
            return connection.execute(sql, parameters).fetchall()
        finally:
            connection.close()


class FileTest(ImportTestCase):

    def assert_refused(self, content, message, status=400):
        response = self.upload(content=content)
        self.assertEqual(response.status_code, status, response.text)
        self.assertIn(message, response.json()["detail"])
        # Un fichier refusé n'est pas gardé
        self.assertFalse((self.import_dir / "pending.json").exists())

    def test_not_json(self):
        self.assert_refused(b"{ pas du json", "n'est pas un fichier JSON")
        self.assert_refused("é".encode("latin-1"), "n'est pas un fichier JSON")

    def test_not_a_configuration_export(self):
        self.assert_refused(b"[]", "n'est pas un export de configuration de RESASAT")
        self.assert_refused(export({}, format="autre"), "n'est pas un export de configuration")
        self.assert_refused(json.dumps({"format": "resasat-configuration", "version": 1,
                                        "tables": []}).encode(), "n'est pas un export")

    def test_version(self):
        self.assert_refused(export({}, version=2), "version plus récente de RESASAT")
        self.assert_refused(export({}, version="1"), "n'indique pas sa version")

    def test_structure(self):
        region = {"format": "resasat-configuration", "version": 1, "tables": {
            "resasat_region": {"columns": ["resasat_region_id", "resasat_region_name"],
                               "rows": [["1", "Nord"]]}}}
        cases = [
            (lambda t: t.update(rows="x"), "« columns » et « rows » sont attendus"),
            (lambda t: t.update(columns=["resasat_region_id", "nom; DROP TABLE x"]),
             "nom de colonne incorrect"),
            (lambda t: t.update(columns=["resasat_region_name", "resasat_region_name"]),
             "nom de colonne incorrect"),
            (lambda t: t.update(columns=["a", "resasat_region_name"]),
             "la colonne resasat_region_id est absente"),
            (lambda t: t.update(rows=[["1"]]), "une ligne n'a pas le nombre de valeurs attendu"),
            (lambda t: t.update(rows=[["un", "Nord"]]), "identifiant incorrect"),
            (lambda t: t.update(rows=[[None, "Nord"]]), "identifiant incorrect"),
            (lambda t: t.update(rows=[["1", "Nord"], ["1", "Sud"]]),
             "identifiant 1 présent deux fois"),
        ]
        for change, message in cases:
            with self.subTest(message=message):
                content = json.loads(json.dumps(region))
                change(content["tables"]["resasat_region"])
                self.assert_refused(json.dumps(content).encode(),
                                    f"table resasat_region : {message}")

    def test_unknown_filter(self):
        self.assertEqual(self.upload(period="demain").status_code, 422)
        self.assertEqual(self.upload(origin="ailleurs").status_code, 422)

    def test_excluded_and_unknown_tables(self):
        tables = sample()
        tables["resasat_option"] = [{"resasat_option_id": "1"}]
        comparison = self.comparison(tables)
        self.assertEqual(
            {table["name"]: table["reason"] for table in comparison["ignored_tables"]},
            {"users": "données personnelles, non importées",
             "resasat_s2c": "non importée : la compatibilité passe par les types de station",
             "resasat_option": "table inconnue"})
        self.assertNotIn("users", [table["name"] for table in comparison["tables"]])
        # Même tout sélectionné, rien n'arrive dans les tables exclues
        self.apply(comparison, self.keys(comparison, "inserts") + ["users|i|346",
                                                                    "resasat_s2c|i|1"])
        self.assertEqual(self.query("SELECT count(*) FROM users"), [(0,)])
        self.assertEqual(self.query("SELECT count(*) FROM resasat_s2c"), [(0,)])
        self.assertEqual(self.query("SELECT count(*) FROM resasat_region"), [(2,)])

    def test_missing_table_and_unknown_column(self):
        tables = {"resasat_region": [{"resasat_region_id": "1", "resasat_region_name": "Nord",
                                      "resasat_region_color": "bleu"}]}
        comparison = self.comparison(tables)
        region = self.table(comparison, "resasat_region")
        self.assertEqual(region["ignored_columns"], ["resasat_region_color"])
        self.assertEqual([item["id"] for item in region["inserts"]], [1])
        self.assertTrue(region["in_file"])
        # Une table absente du fichier n'est pas comparée : rien n'y est supprimé
        self.query("INSERT INTO resasat_operator (resasat_operator_id) VALUES (9)")
        comparison = self.comparison(tables)
        operator = self.table(comparison, "resasat_operator")
        self.assertFalse(operator["in_file"])
        self.assertEqual(operator["deletes"], [])

    def test_invalid_value(self):
        tables = sample()
        tables["resasat_satelite"][0]["resasat_satelite_position"] = "ouest"
        self.query("INSERT INTO resasat_satelite (resasat_satelite_id) VALUES (1)")
        satelite = self.table(self.comparison(tables), "resasat_satelite")
        self.assertEqual(satelite["invalid"],
                         [{"id": 1, "reason": "valeur incorrecte pour "
                                              "resasat_satelite_position : 'ouest'"}])
        # Ni importé, ni proposé à la suppression
        self.assertEqual([item["id"] for item in satelite["inserts"]], [2])
        self.assertEqual(satelite["updates"] + satelite["deletes"], [])

    def test_conversion(self):
        column = {"int": {"type": "int"}, "double": {"type": "double"},
                  "varchar": {"type": "varchar"}}
        self.assertEqual(importer.convert("5", column["int"]), 5)
        self.assertEqual(importer.convert(" 5.0 ", column["int"]), 5)
        self.assertEqual(importer.convert(True, column["int"]), 1)
        self.assertEqual(importer.convert(".5", column["double"]), 0.5)
        self.assertEqual(importer.convert("1.2700299999999999E+004", column["double"]), 12700.3)
        self.assertEqual(importer.convert(" x ", column["varchar"]), " x ")
        for kind in column:
            self.assertIsNone(importer.convert("", column[kind]))
            self.assertIsNone(importer.convert(None, column[kind]))
        for value, kind in (("5.5", "int"), ("abc", "int"), ("nan", "double"), ([], "varchar")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                importer.convert(value, column[kind])


class FilterTest(ImportTestCase):

    def test_defaults_are_active_and_resasat(self):
        comparison = self.comparison(fields={})
        self.assertEqual((comparison["period"], comparison["origin"]), ("active", "resasat"))
        self.assertEqual(self.ids(comparison), {
            "region": [1, 2], "operator": [1], "satelite": [1],
            "profile": [1, 2],          # 2 : expiré, gardé pour le slot 10
            "station_type": [1],
            "station": [1, 4],          # 4 : expirée, gardée pour la station 1
            "channel": [10], "st2c": [100]})
        discarded = {table["name"].replace("resasat_", ""): table["discarded"]
                     for table in comparison["tables"] if table["discarded"]}
        self.assertEqual(discarded, {"satelite": 1, "profile": 1, "station": 2, "channel": 2,
                                     "st2c": 2})

    def test_period_only(self):
        ids = self.ids(self.comparison(period="active", origin="all"))
        self.assertEqual((ids["satelite"], ids["profile"], ids["station"], ids["channel"],
                          ids["st2c"]),
                         ([1], [1, 2, 3], [1, 3, 4], [10, 12], [100, 102]))

    def test_origin_only(self):
        # 0 et NULL sont de RESASAT ; 1 (Globecast) et 2 (Rainbow) sont écartés
        ids = self.ids(self.comparison(period="all", origin="resasat"))
        self.assertEqual((ids["satelite"], ids["profile"], ids["station"], ids["channel"],
                          ids["st2c"]),
                         ([1, 2], [1, 2], [1, 2, 4], [10, 11], [100, 101]))

    def test_no_filter(self):
        comparison = self.comparison()
        ids = self.ids(comparison)
        self.assertEqual((ids["profile"], ids["station"], ids["channel"], ids["st2c"]),
                         ([1, 2, 3], [1, 2, 3, 4], [10, 11, 12], [100, 101, 102]))
        self.assertFalse(any(table["discarded"] for table in comparison["tables"]))

    def test_foreign_record_kept_when_referenced(self):
        tables = sample()
        tables["resasat_channel"][0]["resasat_channel_profile_fk"] = "3"   # profil Rainbow
        ids = self.ids(self.comparison(tables, period="active", origin="resasat"))
        self.assertEqual(ids["profile"], [1, 3])

    def test_link_to_missing_record_is_discarded(self):
        tables = sample()
        tables["resasat_st2c"].append({"resasat_st2c_id": "103",
                                       "resasat_st2c_station_type_fk": "1",
                                       "resasat_st2c_channel_fk": "999"})
        st2c = self.table(self.comparison(tables), "resasat_st2c")
        self.assertEqual([item["id"] for item in st2c["inserts"]], [100, 101, 102])
        self.assertEqual(st2c["discarded"], 1)

    def test_filtered_out_record_is_proposed_for_deletion(self):
        self.import_all()
        comparison = self.comparison(period="active", origin="resasat")
        self.assertEqual(self.ids(comparison, "deletes"),
                         {"satelite": [2], "profile": [3], "station": [2, 3],
                          "channel": [11, 12], "st2c": [101, 102]})
        self.assertEqual(self.ids(comparison), {})

    def test_same_filters_at_application(self):
        comparison = self.comparison(period="active", origin="resasat")
        # Une clé d'un enregistrement écarté par les filtres n'est pas appliquée
        response = self.apply(comparison, self.keys(comparison, "inserts")
                              + ["resasat_channel|i|11"])
        self.assertEqual(response.json()["ignored"], 1)
        self.assertEqual(self.query("SELECT resasat_channel_id FROM resasat_channel"), [(10,)])


class ComparisonTest(ImportTestCase):

    def setUp(self):
        super().setUp()
        self.import_all()

    def test_no_difference(self):
        comparison = self.comparison()
        self.assertEqual(comparison["total"], 0)
        self.assertEqual(self.keys(comparison, "inserts", "updates", "deletes"), [])

    def test_typed_equality(self):
        tables = sample()
        tables["resasat_channel"][0].update(resasat_channel_video_rx_frequ="1.27003E+4",
                                            resasat_channel_permanent="1.0",
                                            resasat_channel_start=63064800)
        self.assertEqual(self.comparison(tables)["total"], 0)

    def test_update_field_by_field(self):
        tables = sample()
        tables["resasat_channel"][0].update(
            resasat_channel_name="Perm 1 bis", resasat_channel_permanent="0",
            resasat_channel_polarisation="V", resasat_channel_start="1173135540",
            resasat_channel_satelite_fk="2", resasat_channel_video_rx_frequ=None,
            resasat_channel_validation="7")
        channel = self.table(self.comparison(tables), "resasat_channel")
        self.assertEqual(channel["inserts"] + channel["deletes"], [])
        (update,) = channel["updates"]
        self.assertEqual((update["id"], update["label"]), (10, "Perm 1"))
        fields = {field["label"]: (field["old"], field["new"], field["key"])
                  for field in update["fields"]}
        self.assertEqual(fields, {
            "Nom": ("Perm 1", "Perm 1 bis", "resasat_channel|u|10|resasat_channel_name"),
            "Début": ("31/12/1971 23:00", "05/03/2007 23:59",
                      "resasat_channel|u|10|resasat_channel_start"),
            "Permanent": ("Oui", "Non", "resasat_channel|u|10|resasat_channel_permanent"),
            "Satellite": ("E8WB", "Ancien", "resasat_channel|u|10|resasat_channel_satelite_fk"),
            "Polarisation Tx": ("Horizontale (X)", "Verticale (Y)",
                                "resasat_channel|u|10|resasat_channel_polarisation"),
            "Down Freq (mHz)": ("12700,3", "(vide)",
                                "resasat_channel|u|10|resasat_channel_video_rx_frequ"),
            "Validation": ("(vide)", "introuvable (7)",
                           "resasat_channel|u|10|resasat_channel_validation")})

    def test_same_display_shows_raw_values(self):
        tables = sample()
        tables["resasat_channel"][0]["resasat_channel_start"] = "63064830"   # 30 s plus tard
        # Heure de Paris : 63064800 est le 31/12/1971 à 22:00 UTC
        (update,) = self.table(self.comparison(tables), "resasat_channel")["updates"]
        self.assertEqual((update["fields"][0]["old"], update["fields"][0]["new"]),
                         ("31/12/1971 23:00 (63064800)", "31/12/1971 23:00 (63064830)"))

    def test_insert_and_delete(self):
        tables = sample()
        del tables["resasat_region"][1]
        tables["resasat_station"].append(
            {"resasat_station_id": "5", "resasat_station_name": "Bastia",
             "resasat_station_region_fk": "1", "resasat_station_type_fk": "9",
             "resasat_station_receiver": "0", "resasat_station_is_foreign": "0"})
        comparison = self.comparison(tables)
        (insert,) = self.table(comparison, "resasat_station")["inserts"]
        self.assertEqual((insert["key"], insert["label"]), ("resasat_station|i|5", "Bastia"))
        # Seuls les champs renseignés sont listés, sans l'identifiant
        self.assertEqual(insert["fields"], [
            {"label": "Nom", "value": "Bastia"},
            {"label": "Type", "value": "introuvable (#9)"},
            {"label": "Région", "value": "Nord"},
            {"label": "Récepteur", "value": "Non"},
            {"label": "Source étrangère", "value": "Non"}])
        (delete,) = self.table(comparison, "resasat_region")["deletes"]
        self.assertEqual((delete["key"], delete["label"], delete["fields"]),
                         ("resasat_region|d|2", "Sud", [{"label": "Nom", "value": "Sud"}]))
        self.assertEqual(comparison["total"], 2)

    def test_linked_names(self):
        channel = sample()["resasat_channel"][0]
        tables = sample()
        tables["resasat_channel"].append(dict(channel, resasat_channel_id="13",
                                              resasat_channel_name="Occasionnel"))
        tables["resasat_st2c"].append({"resasat_st2c_id": "104",
                                       "resasat_st2c_station_type_fk": "1",
                                       "resasat_st2c_channel_fk": "13"})
        comparison = self.comparison(tables)
        (channel_insert,) = self.table(comparison, "resasat_channel")["inserts"]
        values = {field["label"]: field["value"] for field in channel_insert["fields"]}
        self.assertEqual(values["Profil"], "P-expiré")
        # users n'est pas importée : seul l'identifiant est connu
        self.assertEqual(values["Utilisateur"], "#346")
        # Un lien se nomme par les enregistrements reliés ; le slot 13 n'est que dans le fichier
        (link,) = self.table(comparison, "resasat_st2c")["inserts"]
        self.assertEqual(link["label"], "DSNG → Occasionnel")

    def test_record_without_name(self):
        tables = sample()
        tables["resasat_channel"].append({"resasat_channel_id": "14",
                                          "resasat_channel_satelite_fk": "1"})
        tables["resasat_st2c"].append({"resasat_st2c_id": "105"})
        comparison = self.comparison(tables)
        (channel,) = self.table(comparison, "resasat_channel")["inserts"]
        (link,) = self.table(comparison, "resasat_st2c")["inserts"]
        self.assertEqual((channel["label"], link["label"]), ("(sans nom)", "(sans nom)"))

    def test_comparison_is_recomputed(self):
        comparison = self.comparison(sample())
        token = comparison["token"]
        self.query("UPDATE resasat_region SET resasat_region_name = 'Midi' "
                   "WHERE resasat_region_id = 2")
        response = self.client.get(f"{URL}/{token}")
        self.assertEqual(response.status_code, 200)
        (update,) = self.table(response.json(), "resasat_region")["updates"]
        self.assertEqual((update["fields"][0]["old"], update["fields"][0]["new"]),
                         ("Midi", "Sud"))


class ApplyTest(ImportTestCase):

    def test_first_import(self):
        report = self.import_all()
        counts = {table["name"].replace("resasat_", ""): table["insert"]
                  for table in report["tables"]}
        self.assertEqual(counts, {"region": 2, "operator": 1, "satelite": 2, "profile": 3,
                                  "station_type": 1, "station": 4, "channel": 3, "st2c": 3})
        self.assertEqual(report["ignored"], 0)
        self.assertEqual(
            self.query("SELECT resasat_channel_name, resasat_channel_permanent, "
                       "resasat_channel_video_rx_frequ, resasat_channel_end, "
                       "resasat_channel_is_foreign FROM resasat_channel "
                       "WHERE resasat_channel_id = 10"),
            [("Perm 1", 1, 12700.3, FUTURE, None)])
        # Le fichier en attente est supprimé après l'application
        self.assertEqual(list(self.import_dir.iterdir()), [])

    def test_sequence_follows_imported_ids(self):
        self.import_all()
        self.query("INSERT INTO resasat_channel (resasat_channel_name) VALUES ('local')")
        self.assertEqual(self.query("SELECT resasat_channel_id FROM resasat_channel "
                                    "WHERE resasat_channel_name = 'local'"), [(13,)])
        # Sans nouvel ajout, la séquence ne bouge plus
        self.import_all()
        self.query("INSERT INTO resasat_region (resasat_region_name) VALUES ('local')")
        self.assertEqual(self.query("SELECT max(resasat_region_id) FROM resasat_region"), [(3,)])

    def test_partial_selection(self):
        self.import_all()
        tables = sample()
        tables["resasat_region"][0]["resasat_region_name"] = "Hauts-de-France"
        tables["resasat_region"].append({"resasat_region_id": "3",
                                         "resasat_region_name": "Corse"})
        tables["resasat_channel"][0].update(resasat_channel_name="Perm 1 bis",
                                            resasat_channel_polarisation="V")
        del tables["resasat_st2c"][2]
        comparison = self.comparison(tables)
        self.assertEqual(comparison["total"], 4)
        # Un seul des deux champs du slot, la suppression, mais pas la région
        response = self.apply(comparison, ["resasat_channel|u|10|resasat_channel_polarisation",
                                           "resasat_st2c|d|102"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ignored": 0, "tables": [
            {"name": "resasat_channel", "label": "Slot", "insert": 0, "update": 1, "delete": 0},
            {"name": "resasat_st2c", "label": "Slots supportés par type de station",
             "insert": 0, "update": 0, "delete": 1}]})
        self.assertEqual(self.query("SELECT resasat_channel_name, resasat_channel_polarisation "
                                    "FROM resasat_channel WHERE resasat_channel_id = 10"),
                         [("Perm 1", "V")])
        self.assertEqual(self.query("SELECT resasat_region_name FROM resasat_region ORDER BY 1"),
                         [("Nord",), ("Sud",)])
        self.assertEqual(self.query("SELECT count(*) FROM resasat_st2c"), [(2,)])

    def test_values_come_from_the_stored_file(self):
        comparison = self.comparison({"resasat_region": [
            {"resasat_region_id": "1", "resasat_region_name": "Nord"}]})
        # Clés forgées, inconnues, en double, ou d'une forme inattendue
        response = self.client.post(
            f"{URL}/{comparison['token']}/apply",
            json={"selection": ["resasat_region|i|1", "resasat_region|i|1", "resasat_region|i|2",
                                "resasat_region|d|1", "resasat_region|u|1|resasat_region_name",
                                "resasat_reservation|i|1", "users|i|1", "resasat_region|i|x",
                                "resasat_region", "resasat_region|i|1|Pirate", ""],
                  "values": {"resasat_region_name": "Pirate"}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["ignored"], 10)
        self.assertEqual(self.query("SELECT * FROM resasat_region"), [(1, "Nord", None)])

    def test_stale_selection_is_ignored(self):
        self.import_all()
        tables = sample()
        tables["resasat_region"][0]["resasat_region_name"] = "Hauts-de-France"
        tables["resasat_region"].append({"resasat_region_id": "3",
                                         "resasat_region_name": "Corse"})
        comparison = self.comparison(tables)
        keys = self.keys(comparison, "inserts", "updates")
        # Entre la comparaison et l'application, la base rejoint le fichier
        self.query("UPDATE resasat_region SET resasat_region_name = 'Hauts-de-France' "
                   "WHERE resasat_region_id = 1")
        self.query("INSERT INTO resasat_region (resasat_region_id, resasat_region_name) "
                   "VALUES (3, 'Autre')")
        response = self.apply(comparison, keys)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"tables": [], "ignored": 2})
        self.assertEqual(self.query("SELECT resasat_region_name FROM resasat_region "
                                    "WHERE resasat_region_id = 3"), [("Autre",)])

    def test_failure_rolls_everything_back(self):
        self.import_all()
        tables = sample()
        tables["resasat_region"].append({"resasat_region_id": "3",
                                         "resasat_region_name": "Corse"})
        tables["resasat_operator"][0]["resasat_operator_name"] = "SES"
        comparison = self.comparison(tables)
        # La table des opérateurs disparaît avant l'application : DuckDB refusera
        self.query("ALTER TABLE resasat_operator RENAME TO resasat_operator_x")
        self.query("CREATE TABLE resasat_operator (resasat_operator_id INTEGER PRIMARY KEY, "
                   "resasat_operator_name INTEGER, resasat_operator_description VARCHAR, "
                   "resasat_operator_phone VARCHAR)")
        self.query("INSERT INTO resasat_operator (resasat_operator_id) VALUES (1)")
        response = self.apply(comparison, self.keys(comparison, "inserts", "updates"))
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertIn("aucune modification n'est conservée", detail)
        self.assertIn("modification refusé pour Opérateur", detail)
        # La région, ajoutée avant l'erreur, n'est pas restée
        self.assertEqual(self.query("SELECT count(*) FROM resasat_region"), [(2,)])
        # Le fichier reste en attente pour une nouvelle sélection
        self.assertEqual(self.client.get(f"{URL}/{comparison['token']}").status_code, 200)

    def test_unknown_token(self):
        comparison = self.comparison()
        for response in (self.client.get(f"{URL}/inconnu"),
                         self.client.post(f"{URL}/inconnu/apply", json={"selection": []}),
                         self.client.delete(f"{URL}/inconnu")):
            self.assertEqual(response.status_code, 404)
            self.assertIn("n'est plus disponible", response.json()["detail"])
        # Un nouveau dépôt remplace le précédent
        second = self.comparison()
        self.assertEqual(self.client.get(f"{URL}/{comparison['token']}").status_code, 404)
        self.assertEqual(self.client.get(f"{URL}/{second['token']}").status_code, 200)

    def test_cancel(self):
        comparison = self.comparison()
        self.assertEqual(self.client.delete(f"{URL}/{comparison['token']}").status_code, 204)
        self.assertEqual(list(self.import_dir.iterdir()), [])
        self.assertEqual(self.apply(comparison, []).status_code, 404)

    def test_stored_file_is_private(self):
        self.comparison()
        for path in self.import_dir.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, path.name)

    def test_missing_database(self):
        self.database.unlink()
        response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertIn("tools/create-db.py", response.json()["detail"])


@unittest.skipUnless(duckdb, "modules duckdb ou fastapi absents")
class DatamodelTest(unittest.TestCase):

    def test_imported_tables(self):
        from local_controller.configuration.tables import (EXCLUDED_TABLES, IMPORTED_TABLES,
                                                           LINK_TABLES)
        model = load_datamodel(DATAMODEL)
        for name in IMPORTED_TABLES:
            with self.subTest(table=name):
                self.assertEqual(len(model[name]["primary_key"]), 1)
                # Une table ne référence que des tables importées avant elle, ou elle-même
                earlier = IMPORTED_TABLES[:IMPORTED_TABLES.index(name) + 1]
                for _, target in importer.references_of(name, model):
                    self.assertIn(target, earlier)
        self.assertFalse(set(EXCLUDED_TABLES) & set(IMPORTED_TABLES))
        self.assertLessEqual(set(LINK_TABLES), set(IMPORTED_TABLES))


if __name__ == "__main__":
    unittest.main()
