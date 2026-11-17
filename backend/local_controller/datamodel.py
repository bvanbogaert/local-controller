"""Lecture du modèle de données (datamodel/, décrit dans README.d/database.md).

Les fichiers sont validés par tools/create-db.py, qui crée la base à partir
d'eux : ils sont lus ici sans nouveau contrôle.
"""

import json


def load_datamodel(directory):
    """Retourne les tables par nom ; les colonnes de chaque table sont indexées
    par nom, dans l'ordre du fichier."""
    model = {}
    for path in sorted(directory.glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        table["columns"] = {column["name"]: column for column in table["columns"]}
        model[table["name"]] = table
    return model


def primary_key(table):
    """Colonne de la clé primaire, None si la clé n'est pas simple."""
    return table["primary_key"][0] if len(table["primary_key"]) == 1 else None
