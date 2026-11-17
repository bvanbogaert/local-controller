# Backend

## Description

Le backend du simulateur est une application FastAPI en Python 3.11 qui lit et écrit la base DuckDB du contrôleur local. Il sert aussi le [frontend](frontend.md) construit. Le prototype n'a pas d'authentification.

L'installation et le lancement sont décrits dans [build](build.md).

## Organisation du code

Le code est dans *backend/local_controller/* :

| Fichier | Rôle |
| --- | --- |
| *main.py* | Application FastAPI : routes `/api`, forme des erreurs, service du frontend |
| *settings.py* | Emplacements de la base, du modèle de données, du fichier en attente et du frontend |
| *datamodel.py* | Lecture du modèle de données ([database](database.md)) |
| *database.py* | Connexion à la base DuckDB |
| *configuration/tables.py* | Tables importées de RESASAT, tables de liens, tables exclues |
| *configuration/importer.py* | Import : lecture du fichier, filtres, comparaison, application. Sans HTTP |
| *configuration/display.py* | Libellés et valeurs en français |
| *configuration/storage.py* | Fichier en attente d'application |
| *configuration/router.py* | Routes de l'import |

Le backend ne crée ni ne modifie la structure de la base : c'est le rôle de *tools/create-db.py*. Les noms de tables et de colonnes placés dans les requêtes SQL viennent toujours du modèle de données ; les valeurs passent par des paramètres.

## Emplacements

Chaque emplacement a une valeur par défaut et se remplace par une variable d'environnement :

| Variable | Défaut | Contenu |
| --- | --- | --- |
| `LOCAL_CONTROLLER_DATABASE` | *build/db/local-controller.duckdb* | Base DuckDB |
| `LOCAL_CONTROLLER_DATAMODEL` | *datamodel/* | Modèle de données |
| `LOCAL_CONTROLLER_IMPORT_DIR` | *build/import/* | Fichier de configuration en attente |
| `LOCAL_CONTROLLER_FRONTEND` | *build/frontend/* | Frontend construit |

## Routes

Toutes les routes sont sous `/api`. La documentation interactive produite par FastAPI est à l'adresse `/docs`.

Une erreur est toujours un objet JSON `{"detail": "message"}`, avec un message en français destiné à l'utilisateur.

| Route | Effet |
| --- | --- |
| `GET /api/health` | Répond `{"status": "ok"}` |
| `POST /api/configuration/import` | Dépose un fichier, retourne la comparaison |
| `GET /api/configuration/import/{token}` | Recalcule la comparaison de l'import en attente |
| `POST /api/configuration/import/{token}/apply` | Applique les modifications choisies |
| `DELETE /api/configuration/import/{token}` | Abandonne l'import en attente |

Les règles de l'import sont décrites dans [configuration-import](configuration-import.md).

### Dépôt d'un fichier

`POST /api/configuration/import`, en `multipart/form-data` :

| Champ | Valeurs | Défaut |
| --- | --- | --- |
| `file` | Fichier exporté par RESASAT | obligatoire |
| `period` | `active` (actifs et futurs), `all` | `active` |
| `origin` | `resasat` (RESASAT seul), `all` | `resasat` |

La réponse est la comparaison :

```json
{
  "token": "…",
  "period": "active",
  "origin": "resasat",
  "reference_time": 1794860000,
  "file_date": 1794853110,
  "total": 3,
  "ignored_tables": [
    {"name": "users", "label": "", "reason": "données personnelles, non importées"}
  ],
  "tables": [
    {
      "name": "resasat_channel",
      "label": "Slot",
      "in_file": true,
      "ignored_columns": [],
      "discarded": 1079,
      "invalid": [],
      "inserts": [
        {"key": "resasat_channel|i|13", "id": 13, "label": "Occasionnel",
         "fields": [{"label": "Nom", "value": "Occasionnel"}]}
      ],
      "updates": [
        {"id": 10, "label": "Perm 1",
         "fields": [{"key": "resasat_channel|u|10|resasat_channel_polarisation",
                     "label": "Polarisation Tx",
                     "old": "Horizontale (X)", "new": "Verticale (Y)"}]}
      ],
      "deletes": [
        {"key": "resasat_channel|d|11", "id": 11, "label": "Ancien slot", "fields": []}
      ]
    }
  ]
}
```

* `token` désigne l'import en attente dans les routes suivantes.
* `tables` contient les huit tables importées, dans l'ordre ; `in_file` vaut `false` pour une table absente du fichier.
* `discarded` est le nombre d'enregistrements écartés par les filtres ; `invalid` liste les enregistrements illisibles avec le motif.
* Chaque case à cocher de l'écran correspond à une clé `key` : `table|i|identifiant` pour un ajout, `table|d|identifiant` pour une suppression, `table|u|identifiant|colonne` pour un champ modifié.
* `total` est le nombre d'enregistrements ajoutés, modifiés ou supprimés.

Erreurs : 400 si le fichier est refusé, 413 au-delà de 64 Mo, 422 pour un filtre inconnu, 503 si la base est absente ou n'a pas la structure du modèle de données.

### Application

`POST /api/configuration/import/{token}/apply`, en JSON :

```json
{"selection": ["resasat_channel|i|13", "resasat_channel|u|10|resasat_channel_polarisation"]}
```

Seules les clés sont lues ; tout autre champ de la requête est ignoré. La réponse est le compte rendu :

```json
{
  "tables": [
    {"name": "resasat_channel", "label": "Slot", "insert": 1, "update": 1, "delete": 0}
  ],
  "ignored": 0
}
```

`ignored` compte les clés qui ne correspondaient à aucun écart de la comparaison recalculée.

Erreurs : 404 si le jeton ne désigne pas l'import en attente, 409 si la base refuse une modification. Dans ce dernier cas rien n'est appliqué et l'import reste en attente.

## Fichier en attente

Entre le dépôt et l'application, le fichier est gardé dans le répertoire d'import avec les filtres choisis et l'instant de référence du filtre de période :
* *pending.json* : le fichier déposé, tel quel ;
* *pending.meta.json* : le jeton, les filtres et l'instant de référence.

Les deux fichiers ne sont lisibles que par le compte qui exécute le backend. Un fichier refusé n'est pas gardé. Il n'y a qu'un import en attente : un nouveau dépôt remplace le précédent, dont le jeton cesse d'être valable. Les fichiers sont supprimés après une application réussie ou un abandon.

Le fichier exporté par RESASAT contient la table `users`, avec les empreintes des mots de passe. Le backend ne l'importe pas, mais le fichier en attente la contient tant qu'il n'est pas supprimé.

## Tests

```
.venv/bin/python -m unittest discover -s tests/backend -v
```

Les tests de *tests/backend/test_configuration_import.py* créent une base temporaire à partir du modèle de données du dépôt et déposent par l'API un petit fichier d'essai. Ils sont sautés si `duckdb` ou `fastapi` sont absents. Ils vérifient :
* les fichiers refusés, les tables exclues ou inconnues, les colonnes inconnues, les enregistrements illisibles et la conversion des valeurs ;
* les filtres : valeurs par défaut, période seule, origine seule (0, NULL, 1, 2), aucun filtre, enregistrement gardé parce que référencé, lien vers un enregistrement absent, suppressions proposées, mêmes filtres à l'application ;
* la comparaison : absence de différence, égalité typée, modification champ par champ avec la présentation des valeurs (date, oui/non, énumération, enregistrement lié, vide, introuvable), valeurs brutes ajoutées, ajout et suppression, noms des enregistrements liés, enregistrement sans nom, recalcul ;
* l'application : premier import, séquence avancée, sélection partielle, clés forgées ou périmées ignorées, annulation complète quand la base refuse une modification, jeton inconnu, abandon, droits du fichier en attente, base absente ;
* la cohérence de la liste des tables importées avec le modèle de données.
