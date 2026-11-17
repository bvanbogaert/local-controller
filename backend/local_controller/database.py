"""Connexion à la base DuckDB."""

import duckdb


class DatabaseUnavailable(Exception):
    """La base n'existe pas ou ne s'ouvre pas."""


def connect(path):
    """Ouvre la base. Elle n'est jamais créée ici : c'est le rôle de
    tools/create-db.py, qui lui donne aussi sa structure."""
    if not path.is_file():
        raise DatabaseUnavailable(
            f"base de données absente ({path}) : la créer avec tools/create-db.py")
    try:
        return duckdb.connect(str(path))
    except duckdb.Error as error:
        raise DatabaseUnavailable(f"base de données inaccessible ({path}) : {error}") from None
