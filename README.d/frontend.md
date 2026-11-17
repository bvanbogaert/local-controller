# Frontend

## Description

Le frontend du simulateur est une application React écrite en TypeScript et construite par Vite. Il s'affiche dans un navigateur et dialogue avec le [backend](backend.md) par les routes `/api`. Le prototype n'a pas d'authentification : l'application s'ouvre directement sur son écran principal.

L'installation de Node.js, la construction et le lancement sont décrits dans [build](build.md).

## Cadre

L'écran se compose de trois zones :
* une barre en haut, avec le bouton ≡ à gauche suivi du titre de l'écran affiché ;
* un panneau à gauche, escamotable, qui porte le menu ;
* le contenu, qui occupe le reste de la fenêtre.

Le panneau est fermé au démarrage. Un clic sur ≡ l'ouvre, un second clic le referme. Ouvert, il pousse le contenu vers la droite. Le choix d'une entrée du menu referme le panneau.

Le menu contient :
* **Configuration**
  * **Importer de RESASAT** : ouvre l'import de la configuration.

## Grille

L'écran principal est l'emplacement de la future grille des réservations. Il est vide pour l'instant.

## Import de la configuration

L'import se déroule en quatre étapes, rappelées en haut de l'écran ; l'étape en cours est mise en évidence. Les règles appliquées à chaque étape sont décrites dans [configuration-import](configuration-import.md).

Un message d'erreur du backend s'affiche dans un bandeau rouge au-dessus de l'étape en cours.

### 1. Fichier

* Choix du fichier de configuration exporté par RESASAT.
* Période : « Actifs et futurs » (choix par défaut) ou « Tout ».
* Origine : « RESASAT seul » (choix par défaut) ou « Tout ».
* « Comparer avec la configuration actuelle » envoie le fichier et passe à l'étape suivante.
* « Fermer » revient à la grille.

### 2. Comparaison

Un tableau donne, pour chaque table, le nombre d'ajouts, de modifications, de suppressions et d'enregistrements écartés par les filtres. Une table absente du fichier est indiquée comme non comparée.

Sous le tableau sont rappelés les filtres choisis, les colonnes ignorées, les tables du fichier qui ne sont pas importées (dont `users`) et les enregistrements illisibles.

* S'il y a des différences : « Sélectionner les modifications » passe à l'étape suivante, « Annuler » abandonne l'import et revient à l'étape 1.
* Sinon, le message « Aucune différence entre le fichier et la configuration actuelle » s'affiche, avec « Choisir un autre fichier » et « Fermer ».

### 3. Sélection

Chaque table qui a des différences forme une section repliable, dont le bandeau donne le nombre de modifications sélectionnées. Une section de plus de 200 lignes est repliée au départ.

Dans une section, un tableau liste les différences :
* une **modification** occupe une ligne par champ modifié, avec sa case à cocher, la valeur actuelle en rouge et la valeur importée en vert ; fond jaune ;
* un **ajout** occupe une ligne, avec une case à cocher ; fond vert. « détail » déplie la liste de ses champs renseignés ;
* une **suppression** occupe une ligne, avec une case à cocher ; fond rouge. « détail » déplie la liste de ses champs.

Les ajouts et les modifications sont cochés au départ, les suppressions ne le sont pas.

« Tout cocher » et « Tout décocher » existent pour l'ensemble et pour chaque table ; « Tout cocher sauf les suppressions » rétablit la sélection de départ. Un compteur indique le nombre de modifications sélectionnées.

En bas de l'écran, toujours visibles :
* « Importer les modifications sélectionnées » demande confirmation en rappelant le nombre de modifications et de suppressions, puis applique ;
* « Retour à la comparaison » revient à l'étape 2 en conservant la sélection ;
* « Annuler » abandonne l'import.

### 4. Application

Le compte rendu donne, par table, le nombre d'ajouts, de modifications et de suppressions appliqués. « Terminer » revient à la grille, « Nouvel import » à l'étape 1.

Si la base refuse une modification, rien n'est appliqué : le message s'affiche à l'étape 3, où la sélection peut être corrigée.

## Organisation du code

Le code est dans *frontend/* :

| Fichier | Rôle |
| --- | --- |
| *index.html* | Page unique de l'application |
| *vite.config.ts* | Construction dans *build/frontend/* ; en développement, renvoi de `/api` vers le backend |
| *src/main.tsx* | Point d'entrée |
| *src/App.tsx* | Cadre : barre, panneau, écran affiché |
| *src/components/SidePanel.tsx* | Panneau escamotable et menu |
| *src/views/GridView.tsx* | Emplacement de la grille |
| *src/views/ConfigurationImport.tsx* | Les quatre étapes de l'import |
| *src/api.ts* | Appels au backend et types des réponses |
| *src/texts.ts* | Tous les textes de l'interface, en français |
| *src/styles.css* | Présentation |

L'application n'utilise ni bibliothèque de composants ni routeur : elle n'a que deux écrans, choisis par un état de *App.tsx*.

Les textes affichés sont regroupés dans *src/texts.ts* ; les identifiants du code sont en anglais. Les libellés des tables et des champs, eux, viennent du backend, qui les lit dans le modèle de données.

La sélection est un ensemble de clés fournies par le backend, une par case à cocher. Le frontend ne renvoie que ces clés : il ne transmet aucune valeur à écrire dans la base.

## Vérification

`npm run build` vérifie les types TypeScript avant de construire. Il n'y a pas encore de tests automatiques du frontend : l'import a été vérifié dans Chromium, de bout en bout, avec un fichier exporté par RESASAT.
