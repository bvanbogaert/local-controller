"""Fichier de configuration en attente d'application.

Le fichier déposé est gardé côté serveur avec les filtres choisis : à
l'application, la comparaison est recalculée à partir de lui. Un seul import
est en attente à la fois ; un nouveau dépôt remplace le précédent.
"""

import json
import os
import secrets

CONTENT_NAME = "pending.json"
META_NAME = "pending.meta.json"


class UnknownImport(Exception):
    """Le jeton ne désigne pas l'import en attente."""


def write_private(path, content):
    """Écrit un fichier lisible par son seul propriétaire."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as file:
        file.write(content)


def save(directory, content, meta):
    """Stocke le fichier et ses filtres ; retourne le jeton de l'import."""
    discard(directory)
    directory.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(24)
    write_private(directory / CONTENT_NAME, content)
    write_private(directory / META_NAME,
                  json.dumps({**meta, "token": token}).encode("utf-8"))
    return token


def load(directory, token):
    """Retourne le contenu du fichier en attente et ses filtres."""
    try:
        meta = json.loads((directory / META_NAME).read_text(encoding="utf-8"))
        content = (directory / CONTENT_NAME).read_bytes()
    except (OSError, ValueError):
        raise UnknownImport() from None
    if not secrets.compare_digest(str(meta.get("token", "")), token):
        raise UnknownImport()
    return content, meta


def discard(directory):
    for name in (CONTENT_NAME, META_NAME):
        (directory / name).unlink(missing_ok=True)
