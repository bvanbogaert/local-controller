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
