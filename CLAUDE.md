# Objectif

L'application est un simulateur du contrôleur local. Les provisions pour en faire le contrôleur réel (voire un composant d'une prochaine version de RESASAT) sont bienvenues si, et seulement si, elles ne compliquent ni ne retardent le simulateur. En cas de doute, demander.

Ce projet correspond au Lot 3 de l'offre:
/home/apache/GitProjects/docs-resasat/offre-interface-controleur.md

Il contient aussi le lot 1 de la même offre:
/home/apache/GitProjects/local-controller/README.d/interface-resasat-local-controllerv2.md

# La plateforme de développement et la plateforme cible

RedHat 9.6. 

Frontend:
* TypeScript
* React

Backend:
* Python 3.11
* FastAPI
* Database: DuckDB

# Langue

La documentation, les commentaires dans le code et les interfaces graphiques sont en Français.

Pour le code lui-même, les identificateurs doivent être en anglais. Pour les termes techniques, la traduction anglais --> Français doit être maintenue dans un tableau dans *README.d/translation.md*. Exemple: la traduction EIRP vers PIRE se trouve dans le tableau de traduction. Dans *README.d/glossary.md* on retrouve la définition de EIRP et PIRE et, optionnellement, une référence entre les deux.

# Gestion de configuration (`versionning`)

La gestion de configuration se fait sur GIT avec un `repository` privé sur Github.

Tu peux utiliser les commandes en lecture seule uniquement ; jamais de `add`, `commit`, `push`, ni changement de branche.

# Format de la documentation

Markdown pour le texte.

Pour les schémas
* mermaid, par défaut
* drawio.svg

Pour les formules
* LaTeX
  * $…$ en ligne dans le texte
  * $$…$$ en bloc entre deux paragraphes

# Convention en Markdown

* Un seul titre H1 par fichier
* Des liens relatifs entre documents
* Pas de HTML brut
* Les images dans un sous-dossier fixe *README.d/media/*.

# Organisation de la documentation

De préférence, les documents doivent rester d'une taille raisonnable (pour l'instant, considérons la limite à 5000 mots). Préviens moi quand un document devient trop grand.

La liste exhaustive de la documentation, notamment le contenu de *README.d/*, doit être maintenue dans *README.md* avec:
* Lien vers le document
* Le nom de fichier
* Le titre du document (le premier H1)
* En une phrase, la description de son contenu

Les fichiers suivant ne sont pas destinés à être livrés:
* TODO.md: à faire, mais pas maintenant. Maintenu par le développeur.
* DONE.md: garder trace des entrées retirées de TODO.md. Maintenu par le développeur.

# Maintenir la documentation

Si le changement modifie le fonctionnel, la modification du code met à jour, dans le même changement, le document concerné, la liste du README, le glossaire et les traductions. Par exemple, l'ajout d'un bouton est un changement fonctionnel: on s'attend à une modification de la documentation. La correction d'une erreur de syntaxe ne doit pas faire l'objet d'une modification de la documentation. En cas de doute, demande.
