# Glossaire

## Auto-incrément

EN: Auto increment

Colonne dont la valeur est attribuée par la base à l'insertion d'une ligne, à partir d'une séquence. Sert d'identifiant aux lignes d'une table.

Voir Séquence.

## EIRP

EN: Equivalent isotropically radiated power

Voir PIRE.

## ERP

EN: Effective Radiated Power 

ou parfois 

EN: Equivalent Radiated Power

Voir PAR

## Modèle de données

EN: Data model

Description de la structure de la base de données : tables, colonnes, clés primaires et index. Dans ce projet, les fichiers JSON du répertoire *datamodel/*, décrits dans [database](database.md).

## PAR

Puissance apparente rayonnée.
Elle est référencée à un dipôle demi-onde.

Voir ERP

## PIRE ou p.i.r.e

Puissance isotrope rayonnée équivalente.
Elle est référencée à une antenne isotrope.

$$
\text{PIRE} = \text{PAR} + 2{,}15\text{ dB}
$$

Voir EIRP

## Séquence

EN: Sequence

Compteur de la base de données qui fournit des nombres entiers croissants, sans doublon.

Voir Auto-incrément.
