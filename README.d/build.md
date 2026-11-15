# Fabrication

À compléter.

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

L'outil en python *tools/export-oracle-db.py* extrait le schéma de la base de données Oracle de RESASAT. Seules les tables dont le nom commence par `resasat_` sont exportées. L'option *--format* choisit la sortie :
* *markdown* : un fichier *.md* par table dans *build/doc/resasat-db/*, plus *index.md* qui liste les tables et les séquences. Chaque fichier décrit les colonnes, les clés, les contraintes, les index et les déclencheurs ; les clés étrangères renvoient vers le fichier de la table référencée.
* *sql* : un fichier *.sql* par table dans *build/sql/resasat-db/*, en DDL natif Oracle 19c produit par `DBMS_METADATA`, plus *_sequences.sql* pour les séquences. Chaque fichier contient la table, ses index, ses clés étrangères, ses déclencheurs et ses commentaires.

### Prérequis

L'outil n'utilise que la bibliothèque standard de Python 3.11 et interroge la base avec `sqlplus`, cherché dans `$ORACLE_HOME/bin` (par défaut */opt/oracle/product/19c/dbhome_1*).

Le mot de passe Oracle est lu dans la variable d'environnement `RESASAT_PASSWORD` ; si elle est absente, il est demandé au clavier.

### Utilisation

```
tools/export-oracle-db.py --format markdown
tools/export-oracle-db.py --format sql
```

Options :
* *--output RÉPERTOIRE* : autre répertoire de sortie.
* *--user* et *--dsn* : autre compte ou autre base (par défaut `resaora` et `resasat-rhel96:1521/PDB1`).
* *--with-storage* : en format *sql*, conserve les tablespaces et les attributs de stockage, retirés par défaut.

À chaque exécution, les fichiers du même format qui ne correspondent plus à une table sont supprimés du répertoire de sortie.

En format *sql*, les clés étrangères sont dans le fichier de leur table : l'ordre de chargement des fichiers compte. L'en-tête de chaque fichier liste les tables à créer avant.

### Tests

Les tests de *tests/tools/test_export_oracle_db.py* se lancent avec ceux de l'export en PDF :

```
python3.11 -m unittest discover -s tests/tools -v
```

Une première série se passe de la base : elle part d'une sortie de `sqlplus` écrite dans le fichier de test. Elle vérifie :
* la reconstitution du type des colonnes ;
* la lecture des tables, colonnes, valeurs par défaut, contraintes, index, déclencheurs et séquences ;
* le contenu des fichiers Markdown : un seul titre H1, liens entre tables, sections vides omises, caractères `|` et retours à la ligne dans les commentaires ;
* le contenu des fichiers SQL : ordre des objets, tables à créer avant, apostrophes des commentaires ;
* la suppression des fichiers qui ne correspondent plus à une table ;
* les erreurs de la ligne de commande (format absent ou inconnu, `sqlplus` introuvable).

Une seconde série lance l'outil sur la base RESASAT. Elle est sautée si la variable `RESASAT_PASSWORD` ou `sqlplus` sont absents. Elle vérifie :
* les deux formats : un fichier par table, les mêmes tables dans les deux, aucun lien Markdown vers un fichier absent ;
* le DDL sans nom de schéma ni tablespace, et avec tablespace pour l'option *--with-storage* ;
* un mot de passe erroné : message court, code de retour 1, fichiers existants conservés. Ce test fait une tentative de connexion refusée à chaque lancement.

Les tests ne rejouent pas le DDL produit sur une base.
