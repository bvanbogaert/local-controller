# Fabrication

To be completed

## Export en PDF

L'outil en python *tools/export-to-pdf.py*, basé sur Pandoc, exporte la documentation en PDF:
* L'option *--global* produit un document global (servant pour le dossier technique final) reprenant tous les sous documents référencés dans *README.md*
  * La première section contient *README.md*
  * Les sections suivantes contiennent les sous documents.
  * Les liens vers les documents sont remplacés par le nom de la section et, si possible, cliquable. 
* L'option *--file myfile.md* convertit le document nommé. Par exemple, *README.d/interface-resasat-local-controllerv2.md* pour les cycles de revue du Lot 1.
