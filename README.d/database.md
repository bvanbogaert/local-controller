# Base de données

On distingues les types de tables suivantes:

* Tables de configuration: elles décrivent les sites et le matériels.
* Tables opérationnelles: elles contiennent les réservations et leur état

## Tables de configuration

    resasat_station
    resasat_station_type
    resasat_st2c
    resasat_satelite
    resasat_s2c
    resasat_region
    resasat_profile
    resasat_operator
    resasat_channel
    users

## Tables opérationnelles

    resasat_amendment
    resasat_r2s
    resasat_reservation

## Tables d'audit

    resasat_diff
    resasat_log

## Modèle de données

Le modèle de données est le répertoire *datamodel/* : un fichier JSON par table, dont le nom est celui de la table (*datamodel/resasat_r2s.json* pour la table `resasat_r2s`). Ces fichiers sont la référence de la structure de la base du contrôleur local.

Ils viennent du schéma de la base Oracle de RESASAT, exporté par *tools/export-oracle-db.py --format json*, et se maintiennent ensuite à la main. *tools/create-db.py* crée et met à jour la base DuckDB à partir d'eux. Les deux outils sont décrits dans [build](build.md).

### Format d'un fichier

```json
{
  "name": "resasat_r2s",
  "comment": "Liens Réservation-Station",
  "columns": [
    {
      "name": "resasat_r2s_id",
      "comment": "Index",
      "type": "int",
      "nullable": false,
      "default": null,
      "auto_increment": true
    },
    {
      "name": "resasat_r2s_station_fk",
      "comment": "Station",
      "type": "int",
      "nullable": true,
      "default": null,
      "auto_increment": false,
      "references": {
        "table": "resasat_station",
        "column": "resasat_station_id"
      }
    }
  ],
  "primary_key": ["resasat_r2s_id"],
  "indexes": [
    {
      "name": "idx_resasat_r2s_reservation_fk",
      "unique": false,
      "columns": ["resasat_r2s_reservation_fk", "resasat_r2s_station_fk"]
    }
  ]
}
```

Champs de la table :

| Champ | Obligatoire | Contenu |
| --- | --- | --- |
| `name` | oui | Nom de la table, égal au nom du fichier |
| `comment` | non | Description de la table |
| `columns` | oui | Liste des colonnes, dans l'ordre de création |
| `primary_key` | oui | Colonnes de la clé primaire, une ou plusieurs ; liste vide si la table n'en a pas |
| `indexes` | oui | Liste des index ; liste vide si la table n'en a pas |

Champs d'une colonne :

| Champ | Obligatoire | Contenu |
| --- | --- | --- |
| `name` | oui | Nom de la colonne |
| `comment` | non | Description de la colonne |
| `type` | oui | `int`, `bigint`, `double` ou `varchar` |
| `length` | pour `varchar` | Largeur, en caractères |
| `nullable` | oui | `true` si la colonne accepte NULL. Doit valoir `false` pour une colonne de la clé primaire |
| `default` | non | Valeur par défaut : nombre, chaîne, ou `null` s'il n'y en a pas |
| `auto_increment` | non | `true` si la colonne est alimentée par une séquence ; demande un type entier et exclut `default` |
| `format` | non | Présentation d'une valeur entière : `yes_no` (0 = non, 1 = oui) ou `datetime` (date Unix, en secondes). Documentaire |
| `references` | non | Clé étrangère : `table` et `column` visées et, facultatif, `label`, la colonne qui nomme l'enregistrement visé. Documentaire |
| `values` | non | Énumération : signification de chaque valeur. Documentaire |

Champs d'un index : `name` (nom de l'index), `unique` (`true` ou `false`) et `columns` (liste des colonnes, dans l'ordre).

Les noms de tables, de colonnes et d'index s'écrivent en minuscules, avec des lettres, des chiffres et `_`. Un nom d'index ne peut servir qu'une fois dans tout le modèle. Un champ inconnu est refusé, pour qu'une faute de frappe ne passe pas inaperçue.

Les champs documentaires `format`, `references` et `values` ne sont pas appliqués à la base : aucune contrainte de clé étrangère ni de vérification n'est créée, comme dans RESASAT où ces règles sont portées par l'application. Ils servent à présenter les valeurs à l'utilisateur, par exemple dans l'[import de la configuration](configuration-import.md).

### Types

| Modèle de données | DuckDB | Oracle (RESASAT) |
| --- | --- | --- |
| `int` | `INTEGER` | `NUMBER(1)` à `NUMBER(9)` |
| `bigint` | `BIGINT` | `NUMBER(10)` à `NUMBER(18)` |
| `double` | `DOUBLE` | `BINARY_DOUBLE`, `BINARY_FLOAT`, `FLOAT` |
| `varchar` + `length` | `VARCHAR(length)` | `VARCHAR2(length)`, `CHAR(length)` |

Les colonnes `NUMBER(10)` de RESASAT contiennent des dates Unix, en secondes : dix chiffres ne tiennent pas sur les 32 bits d'un `int`, d'où le type `bigint`.

DuckDB accepte la largeur d'un `varchar` mais ne l'applique pas et ne la conserve pas : une chaîne plus longue est acceptée. `length` documente la largeur de RESASAT et sert de provision pour MariaDB et Oracle.

### Auto-incrément

DuckDB n'a pas de colonne auto-incrémentée : une colonne `auto_increment` reçoit pour valeur par défaut la valeur suivante d'une séquence. La séquence porte le nom qu'elle a dans RESASAT, celui de la colonne suivi de `_seq` (`resasat_r2s_id_seq`) ; si la colonne ne commence pas par le nom de sa table, le nom de la table est ajouté devant (`users_id_seq`).

La séquence n'avance que lorsqu'une ligne est insérée sans identifiant. Un chargement de données qui fournit ses propres identifiants doit ensuite avancer la séquence : l'[import de la configuration](configuration-import.md) le fait après chaque ajout.
