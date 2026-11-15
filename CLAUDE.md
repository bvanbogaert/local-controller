# Langue

La documentation, les commentaires dans le code et les interfaces graphiques sont en francais.

Pour le code lui-même, les identificateurs doivent être en anglais. Pour les termes techniques, la traduction anglais --> francais doit être maintenue dans *README.d/translation.md*.

# Gestion de configuration (`versionning`)

La gestion de configuration se fait sur GIT avec un `repository` privé sur Github.

Tu peux accéder à l'historique, mais je veux garder le contrôle des `commit`s et des `push`.

# Format de la documentation

Markdown pour le texte.

Les schémas
* drawio
* mermaid

La documentation doit pouvoir être exportée en PDF.

# Organisation de la documentation

De préférence, les documents doivent rester d'une taille raisonnable (pour l'instant, considéront la limite à 5000 mots). Préviens moi quand un document devient trop grand.

*README.md* contient principalement les liens vers la documentation avec une description sommaire.
* *README.d/* contient les documents. Par exemple:
  * *README.d/build.md* décrit l'installation de l'environnement de développement et la procédure de fabrication. 
  * *README.d/installation.md* décrit l'installation de l'environnement de développement et la procédure de fabrication. 
  * *README.d/translation.md* donne la traduction des termes technique de l'anglais vers le francais. 
  * *README.d/glossary.md* donne la signification des termes utilisés. 

# Maintenir la documentation

A chaque modification, il faut ajuster la documentation.

La liste exhaustive de la documentation doit être maintenue dans *README.md*

