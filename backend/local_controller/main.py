"""Application FastAPI du simulateur du contrôleur local.

Lancement, depuis la racine du dépôt :

    .venv/bin/uvicorn --app-dir backend local_controller.main:app --port 8000

Voir README.d/backend.md.
"""

import duckdb
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .configuration import importer
from .configuration.router import router as configuration_router
from .database import DatabaseUnavailable
from .settings import get_settings


def create_app():
    app = FastAPI(title="Contrôleur local", version="0.1.0")
    app.include_router(configuration_router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # Toutes les erreurs sortent sous la forme {"detail": message}, en français.
    @app.exception_handler(importer.ConfigurationError)
    def configuration_error(request, error):
        return JSONResponse({"detail": f"Import impossible : {error}."}, status_code=400)

    @app.exception_handler(DatabaseUnavailable)
    def database_unavailable(request, error):
        return JSONResponse({"detail": f"Base de données indisponible : {error}."},
                            status_code=503)

    @app.exception_handler(duckdb.Error)
    def database_error(request, error):
        return JSONResponse(
            {"detail": "La base de données ne correspond pas au modèle de données "
                       f"(la mettre à jour avec tools/create-db.py) : {error}"},
            status_code=503)

    # Le frontend construit est servi à la racine, après les routes /api.
    frontend = get_settings().frontend
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
