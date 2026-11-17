# Fabrication

## Environnement de développement

### Prérequis

* Python 3.11 et son environnement virtuel *.venv/*, pour le backend et les outils :

```
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

* Node.js 24 et `npm`, pour construire le frontend :

```
sudo dnf module install nodejs:24
```

*requirements.txt* fixe les versions de `duckdb`, `fastapi`, `uvicorn`, `python-multipart` et `httpx2` (ce dernier pour les tests). Les versions des paquets du frontend sont fixées par *frontend/package-lock.json*. Les deux installations demandent un accès à PyPI et au registre npm.

### Construction et lancement

```
.venv/bin/python tools/create-db.py
cd frontend && npm install && npm run build && cd ..
.venv/bin/uvicorn --app-dir backend local_controller.main:app --host 0.0.0.0 --port 8000
```

* *tools/create-db.py* crée ou met à jour la base (voir « Création de la base de données »).
* `npm install` installe les paquets du frontend dans *frontend/node_modules/*, hors gestion de configuration.
* `npm run build` vérifie les types TypeScript, puis construit le frontend dans *build/frontend/*.
* `uvicorn` lance le [backend](backend.md), qui sert aussi le frontend construit : l'application est à l'adresse `http://<machine>:8000/`. Depuis une autre machine, le port 8000 doit être ouvert dans le pare-feu.

Pendant le développement du frontend, `npm run dev` (dans *frontend/*) le sert sur le port 5173 avec rechargement à chaud et renvoie les appels `/api` vers le backend lancé sur le port 8000.

### Tests

```
.venv/bin/python -m unittest discover -s tests/tools -v
.venv/bin/python -m unittest discover -s tests/backend -v
```

Les tests des outils sont décrits plus bas, ceux du backend dans [backend](backend.md). Le frontend est vérifié par `npm run build` (voir [frontend](frontend.md)).

## Export en PDF

L'outil en python *tools/export-to-pdf.py*, basé sur Pandoc, exporte la documentation en PDF:
* L'option *--global* produit un document global (servant pour le dossier technique final) reprenant tous les sous documents référencés dans *README.md*
  * La première section contient *README.md*
  * Les sections suivantes contiennent les sous documents.
  * Les liens vers les documents sont remplacés par le nom de la section et, si possible, cliquable. 
* L'option *--file myfile.md* convertit le document nommé. Par exemple, *README.d/interface-resasat-local-controllerv2.md* pour les cycles de revue du Lot 1.

### Prérequis

Pandoc convertit le Markdown en HTML, Chromium (sans affichage) imprime le HTML en PDF. Les deux paquets viennent du dépôt EPEL :

```
sudo dnf install pandoc chromium
```

L'outil n'utilise que la bibliothèque standard de Python 3.11.

Les schémas Mermaid sont dessinés par Chromium avec *tools/vendor/mermaid.min.js* (version 11.4.1), conservé dans le dépôt pour que l'export fonctionne sans accès à internet. Pour changer de version :

```
curl -L -o tools/vendor/mermaid.min.js https://cdn.jsdelivr.net/npm/mermaid@VERSION/dist/mermaid.min.js
```

### Utilisation

```
tools/export-to-pdf.py --global
tools/export-to-pdf.py --file README.d/interface-resasat-local-controllerv2.md
```

Les PDF sont écrits dans *build/doc/*, sauf si l'option *--output* donne un autre fichier. L'option *--keep-html* conserve le fichier HTML intermédiaire à côté du PDF, pour chercher l'origine d'un défaut de mise en page.

L'outil signale, sans s'arrêter :
* un document de *README.d/* qui n'est pas référencé dans *README.md* (il est absent du document global) ;
* un document qui n'a pas exactement un titre H1 ;
* une image introuvable.

Si Chromium n'est pas dans le `PATH`, son chemin est donné par la variable d'environnement `CHROMIUM`.

### Tests

Les tests lancent l'outil sur les documents d'essai de *tests/tools/fixtures/* et sur la documentation du dépôt, puis relisent le texte des PDF produits. Ils demandent en plus le paquet *poppler-utils* (`pdftotext`, `pdfinfo`, `pdftohtml`).

```
python3.11 -m unittest discover -s tests/tools -v
```

Ils vérifient :
* le dessin des schémas Mermaid et drawio.svg, et la conversion des formules ;
* l'arrêt sans PDF quand un schéma Mermaid contient une erreur ;
* les avertissements (image introuvable, nombre de titres H1) ;
* le document global : table des matières, une section par document, aucun document de *README.d/* oublié dans *README.md*.

Les tests ne jugent pas la mise en page : après une modification de la feuille de style, il faut relire un PDF.

## Export du schéma de la base RESASAT

L'outil en python *tools/export-oracle-db.py* extrait le schéma de la base de données Oracle de RESASAT. Les tables dont le nom commence par `resasat_` sont exportées, ainsi que la table `users` de PHProjekt, que beaucoup d'entre elles référencent. L'option *--format* choisit la sortie :
* *markdown* : un fichier *.md* par table dans *build/doc/resasat-db/*, plus *index.md* qui liste les tables et les séquences. Chaque fichier décrit les colonnes, les clés, les contraintes, les index et les déclencheurs ; les clés étrangères renvoient vers le fichier de la table référencée.
* *sql* : un fichier *.sql* par table dans *build/sql/resasat-db/*, en DDL natif Oracle 19c produit par `DBMS_METADATA`, plus *_sequences.sql* pour les séquences. Chaque fichier contient la table, ses index, ses clés étrangères, ses déclencheurs et ses commentaires.
* *json* : un fichier *.json* par table dans *build/json/resasat-db/*, au format du modèle de données décrit dans [database](database.md). Il sert à créer, puis à resynchroniser, les fichiers de *datamodel/* (voir « Format json et resynchronisation du modèle de données »).

### Prérequis

L'outil n'utilise que la bibliothèque standard de Python 3.11 et interroge la base avec `sqlplus`, cherché dans `$ORACLE_HOME/bin` (par défaut */opt/oracle/product/19c/dbhome_1*).

Le mot de passe Oracle est lu dans la variable d'environnement `RESASAT_PASSWORD` ; si elle est absente, il est demandé au clavier.

L'option *--lang* demande en plus `php` dans le `PATH`.

### Utilisation

```
tools/export-oracle-db.py --format markdown
tools/export-oracle-db.py --format markdown --lang /chemin/vers/addons/Resasat/lang/fr.inc.php
tools/export-oracle-db.py --format sql
tools/export-oracle-db.py --format json --lang /chemin/vers/addons/Resasat/lang/fr.inc.php
```

Options :
* *--output RÉPERTOIRE* : autre répertoire de sortie.
* *--user* et *--dsn* : autre compte ou autre base (par défaut `resaora` et `resasat-rhel96:1521/PDB1`).
* *--with-storage* : en format *sql*, conserve les tablespaces et les attributs de stockage, retirés par défaut.
* *--lang FICHIER.php* : en formats *markdown* et *json*, enrichit les commentaires avec le fichier langue de kadlib (voir ci-dessous). Sans cette option, les fichiers ne contiennent que ce que dit la base.

À chaque exécution, les fichiers du même format qui ne correspondent plus à une table sont supprimés du répertoire de sortie.

En format *sql*, les clés étrangères sont dans le fichier de leur table : l'ordre de chargement des fichiers compte. L'en-tête de chaque fichier liste les tables à créer avant.

### Fichier langue de kadlib

RESASAT utilise la bibliothèque PHP kadlib, qui décrit dans un fichier langue (*addons/Resasat/lang/fr.inc.php*) ce que la base ne dit pas : le nom des tables et des colonnes tel qu'il est présenté aux utilisateurs, la signification des valeurs énumérées et les clés étrangères, dont la plupart ne sont pas des contraintes dans la base.

Avec l'option *--lang*, l'outil ajoute :
* au commentaire de la table, dans sa page et dans *index.md* : le nom présenté aux utilisateurs. Il vient de la variable qui porte le nom de la table (`$resasat_channel`) ou, à défaut, de son pluriel (`$resasat_amendments`) ;
* au commentaire de la colonne, en gras : le nom présenté aux utilisateurs (`$resasat_channel_name`) ;
* pour une colonne énumérée (masque `ENUM` ou `ENUMORNULL`) : les valeurs et leur signification. Au-delà de 10 valeurs, elles sont dans une section « Valeurs de … » à la suite du tableau des colonnes ;
* pour une clé étrangère (masque `FK`, `FKORNULL` ou `FKNOLIST`) : la colonne et la table visées, avec un lien si la table est exportée ;
* dans les sections « Clés étrangères » et « Référencée par » : les clés étrangères du fichier langue, à la suite des contraintes de la base. Une colonne « Origine » indique d'où vient chaque ligne : *base*, *fichier langue*, ou *base et fichier langue* quand les deux relient la même colonne à la même table.

Le commentaire enregistré dans la base, s'il existe, reste à la fin.

Le fichier langue est du code PHP : l'outil le fait évaluer par `php` après avoir chargé les fichiers *\*defines.inc.php* de l'application (le répertoire parent de *lang/*) et des modules voisins, qui définissent ses constantes. Une constante qui reste inconnue est signalée par un avertissement et garde son nom à la place de sa valeur.

### Format json et resynchronisation du modèle de données

Le format *json* traduit le schéma Oracle dans le format de *datamodel/* :
* le type vient du type Oracle, selon la correspondance donnée dans [database](database.md). Un type sans correspondance (`DATE`, `CLOB`, `NUMBER` à décimales…) est signalé par un avertissement et reste écrit tel quel dans le fichier : *tools/create-db.py* refusera ce fichier tant que la colonne n'est pas corrigée ou retirée ;
* `comment` reprend le commentaire de la base, précédé, avec *--lang*, du nom présenté aux utilisateurs ;
* `auto_increment` vaut `true` pour la clé primaire simple d'une table qui porte un déclencheur actif `<TABLE>_AUTO_INC` ;
* `default` reprend une valeur par défaut numérique ou chaîne ; une expression (`SYSDATE`…) est signalée par un avertissement et n'est pas reprise ;
* `indexes` reprend les index de la table, sauf celui de la clé primaire. Une contrainte d'unicité devient un index unique. Un index décroissant ou sur une expression est signalé et n'est pas repris ;
* `references` vient des clés étrangères de la base ou, avec *--lang*, du fichier langue, qui ajoute `label`, la colonne qui nomme l'enregistrement visé (masque `FK`) ; `values` vient des énumérations du fichier langue ;
* `format` vient, avec *--lang*, des masques `YESNO` (`yes_no`) et `DATETIME` (`datetime`) du fichier langue, pour une colonne entière.

L'export n'écrit jamais dans *datamodel/* : les fichiers de *datamodel/* sont la référence du contrôleur local et peuvent s'écarter du schéma de RESASAT. Quand la base RESASAT évolue, la reprise se fait à la main :

```
tools/export-oracle-db.py --format json --lang /chemin/vers/addons/Resasat/lang/fr.inc.php
diff -r build/json/resasat-db datamodel
```

`diff` liste les tables de RESASAT absentes de *datamodel/* (« Seulement dans build/json/resasat-db ») et les différences des tables communes. Après avoir reporté dans *datamodel/* les changements voulus, *tools/create-db.py* met la base DuckDB à jour (voir « Création de la base de données »).

### Tests

Les tests de *tests/tools/test_export_oracle_db.py* se lancent avec ceux des autres outils :

```
.venv/bin/python -m unittest discover -s tests/tools -v
```

Une première série se passe de la base : elle part d'une sortie de `sqlplus` écrite dans le fichier de test. Elle vérifie :
* la reconstitution du type des colonnes ;
* la lecture des tables, colonnes, valeurs par défaut, contraintes, index, déclencheurs et séquences ;
* le contenu des fichiers Markdown : un seul titre H1, liens entre tables, sections vides omises, caractères `|` et retours à la ligne dans les commentaires ;
* le contenu des fichiers SQL : ordre des objets, tables à créer avant, apostrophes des commentaires ;
* le contenu des fichiers JSON : correspondance des types, types sans correspondance, valeurs par défaut, clé primaire, index, auto-incrément, clés étrangères, enrichissement par le fichier langue, et leur lecture par la validation de *tools/create-db.py* ;
* la suppression des fichiers qui ne correspondent plus à une table ;
* les erreurs de la ligne de commande (format absent ou inconnu, `sqlplus` introuvable, *--lang* avec le format *sql*, fichier langue introuvable) ;
* l'enrichissement par le fichier langue : noms des tables et des colonnes, énumérations courtes et longues, clés étrangères dans les commentaires et dans les sections « Clés étrangères » et « Référencée par », et l'absence de changement sans l'option *--lang* ;
* la lecture par `php` du fichier langue d'essai de *tests/tools/fixtures/kadlib/* : constantes connues et inconnues, entités HTML. Ces tests sont sautés si `php` est absent.

Une seconde série lance l'outil sur la base RESASAT. Elle est sautée si la variable `RESASAT_PASSWORD` ou `sqlplus` sont absents. Elle vérifie :
* les deux formats : un fichier par table, les mêmes tables dans les deux, aucun lien Markdown vers un fichier absent ;
* le format *markdown* avec le fichier langue d'essai ;
* le format *json* avec le fichier langue d'essai : un fichier par table, lisible par *tools/create-db.py* sauf pour les types signalés ;
* le DDL sans nom de schéma ni tablespace, et avec tablespace pour l'option *--with-storage* ;
* un mot de passe erroné : message court, code de retour 1, fichiers existants conservés. Ce test fait une tentative de connexion refusée à chaque lancement.

Les tests ne rejouent pas le DDL produit sur une base.

## Création de la base de données

L'outil en python *tools/create-db.py* crée la base de données DuckDB du contrôleur local, puis la met à jour, à partir du modèle de données de *datamodel/* : un fichier JSON par table, dont le format est décrit dans [database](database.md).

La base est le fichier *build/db/local-controller.duckdb*. Seule la structure est gérée : l'outil ne charge aucune donnée et ne se connecte jamais à la base Oracle de RESASAT.

### Prérequis

L'outil demande le module Python `duckdb` (version 2.0.0), installé dans l'environnement virtuel *.venv/* décrit dans « Environnement de développement ».

### Utilisation

```
.venv/bin/python tools/create-db.py --dry-run
.venv/bin/python tools/create-db.py
.venv/bin/python tools/create-db.py --force
```

Options :
* *--db FICHIER* : autre fichier de base (par défaut *build/db/local-controller.duckdb*).
* *--datamodel RÉPERTOIRE* : autre répertoire de fichiers JSON (par défaut *datamodel/*).
* *--dry-run* : affiche les modifications et leurs instructions SQL sans toucher à la base. Si la base n'existe pas, elle n'est pas créée.
* *--force* : applique aussi les modifications qui peuvent perdre des données (voir ci-dessous).

L'outil lit et valide tous les fichiers JSON avant d'ouvrir la base ; toutes les erreurs du modèle sont listées en une fois. Il compare ensuite le modèle à la base et affiche une ligne par modification.

Code de retour :
* 0 : la base est conforme au modèle ;
* 1 : des modifications attendent l'option *--force* ; elles sont listées sur la sortie d'erreur ;
* 2 : erreur (modèle invalide, module `duckdb` absent, instruction refusée par DuckDB).

### Mise à jour d'une base existante

| Écart entre le modèle et la base | Action | *--force* |
| --- | --- | --- |
| Table absente de la base | création de la table, de ses index, de sa séquence et de ses commentaires | non |
| Colonne absente, qui accepte NULL | `ALTER TABLE … ADD COLUMN` | non |
| Valeur par défaut ou auto-incrément modifié | `ALTER COLUMN … SET DEFAULT` ou `DROP DEFAULT` | non |
| Commentaire modifié | `COMMENT ON` | non |
| Index absent, modifié ou en trop | `CREATE INDEX`, `DROP INDEX` | non |
| Colonne qui accepte de nouveau NULL | reconstruction de la table | non |
| Colonne en trop dans la base | reconstruction de la table | oui |
| Type d'une colonne modifié | reconstruction de la table | oui |
| Colonne qui devient NOT NULL, nouvelle colonne NOT NULL | reconstruction de la table | oui |
| Clé primaire modifiée | reconstruction de la table | oui |
| Table en trop dans la base | `DROP TABLE` | oui |

La reconstruction contourne les limites d'`ALTER TABLE` dans DuckDB, qui refuse la plupart des modifications dès que la table porte un index : une nouvelle table est créée, les colonnes communes y sont copiées (avec conversion si le type change), l'ancienne table est supprimée, la nouvelle prend son nom, puis les index et les commentaires sont recréés.

Sans *--force*, une table qui attend une reconstruction n'est pas modifiée du tout ; les autres tables sont mises à jour normalement.

Toutes les modifications d'une exécution sont faites dans une seule transaction. Si DuckDB refuse une instruction (par exemple une conversion de type impossible ou une valeur NULL dans une colonne qui devient NOT NULL), la transaction est annulée, la base reste dans son état d'avant et l'instruction refusée est affichée.

Points d'attention :
* avec *--force*, toute table de la base qui n'a pas de fichier dans *datamodel/* est supprimée avec ses données ;
* un changement de type peut arrondir ou tronquer des valeurs (`double` vers `int`) ;
* l'ordre des colonnes d'une table existante n'est pas comparé : une colonne ajoutée se place à la fin de la table, quelle que soit sa position dans le fichier JSON ;
* la largeur d'un `varchar` n'est pas appliquée par DuckDB : la modifier seule ne change rien dans la base (voir [database](database.md)).

### Tests

Les tests de *tests/tools/test_create_db.py* se lancent avec ceux des autres outils :

```
.venv/bin/python -m unittest discover -s tests/tools -v
```

Chaque test écrit un modèle d'essai et une base dans un répertoire temporaire. Ceux qui ouvrent une base sont sautés si le module `duckdb` est absent. Ils vérifient :
* la validation du modèle : JSON illisible, nom de fichier différent du nom de la table, type inconnu, `varchar` sans largeur, clé primaire ou index sur une colonne inconnue, valeur par défaut d'un autre type, champ inconnu, nom d'index pris deux fois ;
* la création : colonnes, types, NOT NULL, clés primaires simple et composée, index uniques ou non, commentaires, valeurs par défaut et auto-incrément ;
* une seconde exécution sans changement : la base n'est pas modifiée ;
* les mises à jour sans *--force* : nouvelle table, nouvelle colonne, valeurs par défaut, commentaires, index, auto-incrément ajouté ou retiré, données conservées ;
* les modifications qui demandent *--force* : sans l'option, rien n'est perdu et le code de retour vaut 1 ; avec l'option, suppression de colonne, changement de type, de clé primaire, passage à NOT NULL et suppression de table, les données des colonnes communes étant conservées et la séquence continuant après le dernier identifiant ;
* l'annulation complète d'une mise à jour refusée par DuckDB ;
* l'option *--dry-run* : base ni créée ni modifiée ;
* les fichiers de *datamodel/* : valides, et la base créée contient les 15 tables.
