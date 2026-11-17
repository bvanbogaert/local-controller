"""Emplacements utilisés par le backend.

Chaque chemin a une valeur par défaut dans le dépôt et se remplace par une
variable d'environnement, lue à chaque appel : les tests s'en servent.
"""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database: Path     # base DuckDB, créée par tools/create-db.py
    datamodel: Path    # modèle de données, un fichier JSON par table
    import_dir: Path   # fichier de configuration en attente d'application
    frontend: Path     # frontend construit par « npm run build »


def get_settings():
    def path(variable, default):
        return Path(os.environ.get(variable) or default)

    return Settings(
        database=path("LOCAL_CONTROLLER_DATABASE", ROOT / "build" / "db" / "local-controller.duckdb"),
        datamodel=path("LOCAL_CONTROLLER_DATAMODEL", ROOT / "datamodel"),
        import_dir=path("LOCAL_CONTROLLER_IMPORT_DIR", ROOT / "build" / "import"),
        frontend=path("LOCAL_CONTROLLER_FRONTEND", ROOT / "build" / "frontend"))
