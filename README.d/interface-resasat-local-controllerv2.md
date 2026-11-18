# Interface entre RESASAT et les contrôleurs locaux, version 2

Questions/Remarques:
* `/api/v2` à la place de `/api/v1`.
* Dans l'offre, il y a eu confusion entre la liste des stations complémentaires `others` et l'état des amendements `amendmentStates`.
* Pour identifier les ressources (véhicule, centre, etc), on utilise l'identification numérique interne de RESASAT (`id`), mais toujours accompagnée du nom en clair pour l'affichage.  
* Quelles sont les unités des `eirp`, `sourceEirp`, `destinationEirp` et `redLineUpLevel` ? Les colonnes sont des entiers sans unité dans le modèle de données.

## Principes

* **Transport** : 
  HTTPS, corps en JSON (UTF-8), chemins préfixés par `/api/v2`.  
* **Topologie bidirectionnelle** : 
  RESASAT et le contrôleur exposent chacun une API. RESASAT pousse les configurations vers le contrôleur.  
  Le contrôleur pousse son état et ses acquittements vers RESASAT.  
* **Authentification** : 
  Une paire de clefs privée et publique par station et pour le serveur RESASAT, dans chaque sens.  
* **Dates** : 
  ISO 8601 en UTC, par exemple `2026-10-23T19:35:00Z`. Dans le modèle de données, les dates sont des dates Unix en secondes.  
* **Unités**: 
  Elles sont explicites dans le nom des champs (Hz, symboles/s, bit/s). Le modèle de données stocke les fréquences en MHz et les débits symboles en Msymboles/s : la conversion est indiquée dans la [table de correspondance](#correspondance-avec-le-modèle-de-données).  
* **Valeurs énumérées** : 
  Les valeurs énumérées sont celles de l'interface, données dans la [description formelle](#description-formelle-des-objets-json). Lorsqu'elles diffèrent des valeurs stockées dans RESASAT, la conversion est donnée dans la [table de correspondance](#correspondance-avec-le-modèle-de-données). Une colonne au format `yes_no` est transmise en booléen.  
* **Noms** : 
  Les noms transmis (`name`) sont ceux de RESASAT (colonnes `…_name`) et non ceux des contrôleurs locaux de la version 1 (colonnes `…_controler_n…`).  
* **Identification des transmissions** : 
  Une transmission est identifiée par son `id` (numéro de réservation dans RESASAT) et sa `version` (numéro d'amendement de la réservation), qui augmente à chaque modification. Un message déjà reçu peut être rejoué sans effet ; une version plus ancienne que celle connue est ignorée.  
* **Identification des émetteurs, des donneurs d'ordre, des station complémentaires, des satellites et des slots** : 
  Les identifications sont celles utilisées par RESASAT. L'unicité est garantie par l'identifiant numérique `id` utilisé par RESASAT et est toujours accompagné par le nom en clair.  
* **Enregistrements de référence** : 
  Lorsque le contrôleur reçoit une configuration de transmission, chaque objet (station, satellite, slot, profil) est comparé à l'enregistrement de même `id` dans sa base : s'il n'existe pas, il est créé ; s'il est différent, l'enregistrement est mis à jour et la modification est écrite dans le journal. Ce dernier cas est exceptionnel et ne devrait jamais se produire. Les colonnes qui ne sont pas transmises restent à NULL lors d'une création et ne sont pas modifiées lors d'une mise à jour.  
* **Erreurs** : 
  Codes HTTP usuels et corps d'erreur normalisé (RFC 9457) avec un code applicatif.


## API exposée par le contrôleur local (appelée par RESASAT)

| Méthode | Chemin | Rôle | Périmètre |
| ----- | ----- | ----- | ----- |
| PUT | `/transmissions/{id}` | Créer ou modifier une transmission. Le corps contient la configuration complète et sa `version` | Base |
| DELETE | `/transmissions/{id}` | Annuler une transmission | Base |
| GET | `/transmissions` | Lister les transmissions connues du contrôleur (`id`, `version`) | Base |
| GET | `/status` | Lire l'état de la station à la demande | Base |

## API exposée par RESASAT (appelée par le contrôleur local)

| Méthode | Chemin | Rôle | Périmètre |
| ----- | ----- | ----- | ----- |
| PUT | `/stations/{station}/status` | Publier l'état : mode manuel/automatique, porteuse, horodatage | Base |
| PUT | `/stations/{station}/transmissions/{id}/acknowledgement` | Acquitter une configuration : appliquée ou en échec. Idempotent : un nouvel envoi remplace le précédent ; un acquittement d'une `version` antérieure à la version actuelle est ignoré | Base |
| GET | `/stations/{station}/transmissions?from=…&to=…` | Obtenir les transmissions de la station sur une période | Base |
| POST | `/stations/{station}/transmissions/sync` | Resynchroniser : Le contrôleur envoie la liste de ce qu'il connaît.RESASAT répond en transmettant à nouveau les écarts | Base |
| GET | `/stations/{station}/transmissions/{id}/amendment-states` | Obtenir l'état actuel des amendements de la transmission `id` | O1 |
| PUT | `/stations/{station}/status` | Mêmes échanges que ci-dessus mais avec les champs `antenna` et `weather` | O2 |
| GET | `/resources?from=…&to=…&type=…` | Disponibilité des véhicules, des centres et des slots satellite sur une période | O3 |
| POST | `/stations/{station}/reservation-requests` | Proposer une réservation | O4 |

## Cycle de vie d'une configuration

1. RESASAT envoie la configuration (`PUT /transmissions/{id}`).  
2. Le contrôleur répond immédiatement : `received` s'il a enregistré le message, ou une erreur s'il le refuse (données invalides, équipement inconnu).   
   Dans RESASAT, la réservation passe à « Transmise » ou « Refusé ».  
3. Pendant la prise en compte de la configuration, le contrôleur peut envoyer des acquittements `sent` décrivant la progression. Lorsqu'il a terminé, il envoie un acquittement `acknowledged`, ou `problem` avec la description de l'erreur.   
   La réservation passe à « Acquittée » ou « Problème ».  
4. Sans réponse à l'étape 2, RESASAT réessaie avec une temporisation croissante. Sans acquittement dans un délai paramétrable, la réservation passe à « Problème ».  
5. Une modification suit le même chemin avec une `version` supérieure.   
   Une annulation utilise `DELETE` et est acquittée de la même manière.

## Exemples : acquittement

Corps de `PUT /stations/{station}/transmissions/{id}/acknowledgement`, en cours de configuration :

```json
{
  "version": 1,
  "state": "sent",
  "description": "Configuration du modem (2/3)"
}
```

Configuration appliquée :

```json
{
  "version": 1,
  "state": "acknowledged",
  "description": ""
}
```

Configuration en échec :

```json
{
  "version": 1,
  "state": "problem",
  "description": "IRD 1 : pas de réponse"
}
```

## Resynchronisation

Le contrôleur local appelle `POST /stations/{station}/transmissions/sync` à intervalle régulier et à chaque retour en ligne. Il envoie la liste des transmissions à venir qu'il connaît :

```json
{
  "from": "2026-10-23T00:00:00Z",
  "to": "2026-10-30T00:00:00Z",
  "known": [
    { "id": 369286, "version": 1 },
    { "id": 369301, "version": 3 }
  ]
}
```

RESASAT compare avec son propre planning et transmet à nouveau les écarts (les transmissions manquantes ou périmées) par le canal habituel. De son côté, RESASAT peut vérifier à tout moment ce que connaît un contrôleur avec `GET /transmissions`.

## État des amendements (option O1)

La configuration d'une transmission contient l'état initial des amendements dans `amendmentStates`. Le contrôleur obtient ensuite l'état actuel avec `GET /stations/{station}/transmissions/{id}/amendment-states`, par exemple lors de l'affichage du détail d'une transmission ou à intervalle régulier pendant les transmissions en cours.

RESASAT répond avec la `version` de la transmission et l'état des amendements de chaque station concernée :

```json
{
  "id": 369286,
  "version": 1,
  "amendmentStates": [
    { "station": { "id": 4801, "name": "D Bastia" }, "role": "emitter", "amendmentState": "acknowledged" },
    { "station": { "id": 36, "name": "ORLEANS" }, "role": "orderingCenter", "amendmentState": "acknowledged" },
    { "station": { "id": 25, "name": "AMIENS" }, "role": "complementaryCenter", "amendmentState": "sent" }
  ]
}
```

Seuls les amendements en vigueur (`resasat_amendment_deleted` = 0) sont transmis. Si la `version` reçue est supérieure à celle que connaît le contrôleur, une nouvelle configuration est en cours d'envoi : le contrôleur peut l'attendre ou la demander par une resynchronisation.

Réponses :

| Code HTTP | Signification |
| ----- | ----- |
| 200 | État des amendements dans le corps |
| 404 | Transmission inconnue, annulée, ou qui ne concerne pas la station `{station}` |

## Exemple : configuration d'une transmission

Cet exemple reprend une transmission réelle. 

Le bloc `amendmentStates` relève de l'option O1 (ERRATUM: en non pas `others` comme écrit dans l'offre).

```json
{
  "id": 369286,
  "version": 1,
  "title": "Direct Bastia",
  "start": "2026-10-23T19:35:00Z",
  "end": "2026-10-23T19:48:00Z",
  "source": { "id": 4801, "name": "D Bastia" },
  "destination": { "id": 36, "name": "ORLEANS" },
  "audioCount": 2,
  "orderCarrierRequested": true,
  "satellite": {
    "id": 182,
    "name": "E8WB V"
  },
  "channel": {
    "id": 13721,
    "name": "Perm 1",
    "txFrequencyHz": 14047000000,
    "txPolarisation": "horizontal",
    "rxFrequencyHz": 12547000000,
    "rxPolarisation": "vertical"
  },
  "orderCarrier": {
    "origin": { "txFrequencyHz": 14044840000, "rxFrequencyHz": 12544840000 },
    "destination": { "txFrequencyHz": 14049160000, "rxFrequencyHz": 12549160000 }
  },
  "profile": {
    "id": 3961,
    "name": "P4,25Mhz",
    "standard": "dvbs2",
    "modulation": "8PSK",
    "fec": "5/6",
    "symbolRateBaud": 3400000,
    "rollOffPercent": 25,
    "dvbs2FrameSize": "normal",
    "dvbs2PilotInsertion": false,
    "videoCodingStandard": "MPEG4AVC",
    "codingFormat": "4:2:0",
    "videoBitrate2AudioBps": 5040000,
    "videoBitrate4AudioBps": null,
    "audioBitrate1Kbps": 256,
    "audioBitrate2Kbps": 256,
    "packetSizeBytes": 188,
    "eirp": null,
    "sourceEirp": null,
    "destinationEirp": null,
    "redLineUpLevel": null
  },
  "devices": [
    { "type": "modem", "automatic": true, "number": 1 },
    { "type": "ird", "number": 1 }
  ],
  "others": [
    { "id": 25, "name": "AMIENS" }
  ],
  "amendmentStates": [
    { "station": { "id": 4801, "name": "D Bastia" }, "role": "emitter", "amendmentState": "acknowledged" },
    { "station": { "id": 36, "name": "ORLEANS" }, "role": "orderingCenter", "amendmentState": "sent" },
    { "station": { "id": 25, "name": "AMIENS" }, "role": "complementaryCenter", "amendmentState": "new" }
  ]
}
```

Les unités de la PIRE (`eirp`, `sourceEirp`, `destinationEirp`) et du niveau de line-up doivent être clarifiées.

## Exemple : état de la station

Les blocs `antenna` et `weather` relèvent de l'option O2.

```json
{
  "timestamp": "2026-10-23T19:35:12Z",
  "mode": "automatic",
  "carrier": "on",
  "antenna": { "azimuthDeg": 187.4, "elevationDeg": 33.1, "polarisationDeg": -12.0 },
  "weather": {
    "temperatureC": 11.5,
    "pressureHpa": 1013.2,
    "humidityPercent": 78,
    "windSpeedMps": 6.3
  }
}
```

## Exemple : réponse à une proposition de réservation (option O4)

```json
{
  "decision": "refused",
  "reasons": [
    { "resource": "slot", "id": 13721, "name": "Perm 1", "code": "SLOT_UNAVAILABLE" },
    { "resource": "emitter", "id": 4801, "name": "D Bastia", "code": "EMITTER_UNAVAILABLE" }
  ]
}
```

Codes prévus :

| Code | Signification |
| ----- | ----- |
| `SLOT_UNAVAILABLE` | Le slot satellite est déjà réservé ou restreint sur la période |
| `EMITTER_UNAVAILABLE` | L’émetteur (véhicule ou centre) est déjà engagé sur la période |
| `ORDERING_CENTER_UNAVAILABLE` | Le centre donneur d'ordre n'est pas disponible |
| `COMPLEMENTARY_CENTER_UNAVAILABLE` | Un centre complémentaire n'est pas disponible |
| `STATION_SLOT_INCOMPATIBLE` | La station n'est pas autorisée sur ce slot |

Ces contrôles sont ceux que RESASAT applique déjà lors d'une réservation saisie par un utilisateur.

## Description formelle des objets JSON

Conventions :

* **Types** : `integer`, `number` (nombre décimal), `string`, `boolean`, `date-time` (chaîne ISO 8601 en UTC), `object`, `array`.
* **Oblig.** : « oui » si le champ doit être présent. Un champ présent dont le type est suivi de `| null` peut valoir `null` (colonne NULL dans le modèle de données).
* Un champ inconnu est ignoré par le destinataire, pour permettre l'ajout de champs sans changer de version d'interface.

### `StationRef` : référence à une station

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `id` | `integer` | oui | Identifiant RESASAT de la station |
| `name` | `string` (20 car. max.) | oui | Nom de la station |

### `Transmission` : configuration d'une transmission

Corps de `PUT /transmissions/{id}` et éléments de la réponse de `GET /stations/{station}/transmissions`.

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `id` | `integer` | oui | Numéro de la réservation |
| `version` | `integer` | oui | Numéro d'amendement de la réservation, croissant |
| `title` | `string` (255 car. max.) \| `null` | oui | Titre |
| `start` | `date-time` | oui | Début |
| `end` | `date-time` | oui | Fin, postérieure à `start` |
| `source` | `StationRef` | oui | Émetteur |
| `destination` | `StationRef` | oui | Donneur d'ordre |
| `audioCount` | `integer` | oui | Nombre d'audios : `2` ou `4`. Détermine le débit vidéo du profil à utiliser |
| `orderCarrierRequested` | `boolean` | oui | Porteuse d'ordre demandée pour cette transmission |
| `satellite` | `Satellite` | oui | Satellite du slot |
| `channel` | `Channel` | oui | Slot |
| `orderCarrier` | `OrderCarrier` | non | Fréquences de la porteuse d'ordre. Présent si et seulement si le slot a une porteuse d'ordre |
| `profile` | `Profile` | oui | Profil du slot |
| `devices` | `array` de `Device` | oui | Équipements de la station à configurer |
| `others` | `array` de `StationRef` | oui | Stations complémentaires ; tableau vide s'il n'y en a pas |
| `amendmentStates` | `array` de `AmendmentState` | non (O1) | État initial des amendements |

### `Satellite`

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `id` | `integer` | oui | Identifiant RESASAT du satellite |
| `name` | `string` (10 car. max.) | oui | Nom |

### `Channel` : slot

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `id` | `integer` | oui | Identifiant RESASAT du slot |
| `name` | `string` (10 car. max.) | oui | Nom |
| `txFrequencyHz` | `integer` | oui | Fréquence montante, en Hz |
| `txPolarisation` | `string` | oui | Polarisation montante : `"horizontal"` (X) ou `"vertical"` (Y) |
| `rxFrequencyHz` | `integer` | oui | Fréquence descendante, en Hz |
| `rxPolarisation` | `string` | oui | Polarisation descendante : `"horizontal"` (X) ou `"vertical"` (Y) |

### `OrderCarrier` : porteuse d'ordre

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `origin` | `OrderCarrierFrequencies` | oui | Fréquences utilisées par l'émetteur (`source`) |
| `destination` | `OrderCarrierFrequencies` | oui | Fréquences utilisées par le donneur d'ordre (`destination`) |

`OrderCarrierFrequencies` :

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `txFrequencyHz` | `integer` | oui | Fréquence montante, en Hz |
| `rxFrequencyHz` | `integer` | oui | Fréquence descendante, en Hz |

### `Profile` : profil

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `id` | `integer` | oui | Identifiant RESASAT du profil |
| `name` | `string` (10 car. max.) | oui | Nom |
| `standard` | `string` | oui | Standard de modulation : `"dvb"`, `"dvbs2"` ou `"dvbs2x"` |
| `modulation` | `string` | oui | `"QPSK"`, `"8PSK"` ou `"16QAM"` |
| `fec` | `string` | oui | `"1/2"`, `"2/3"`, `"3/4"`, `"4/5"`, `"5/6"`, `"6/7"` ou `"7/8"` |
| `symbolRateBaud` | `integer` | oui | Débit symboles, en symboles/s |
| `rollOffPercent` | `integer` \| `null` | oui | Facteur de roll-off, en % : `20`, `25`, `30` ou `35` |
| `dvbs2FrameSize` | `string` \| `null` | oui | DVB-S2 et DVB-S2X seulement : `"normal"` ou `"short"` |
| `dvbs2PilotInsertion` | `boolean` \| `null` | oui | DVB-S2 et DVB-S2X seulement : insertion de pilotes |
| `videoCodingStandard` | `string` \| `null` | oui | `"MPEG2"` ou `"MPEG4AVC"` |
| `codingFormat` | `string` \| `null` | oui | `"4:2:0"` ou `"4:2:2"` |
| `videoBitrate2AudioBps` | `integer` \| `null` | oui | Débit vidéo avec 2 audios, en bit/s |
| `videoBitrate4AudioBps` | `integer` \| `null` | oui | Débit vidéo avec 4 audios, en bit/s |
| `audioBitrate1Kbps` | `integer` | oui | Débit de la première paire audio, en kbit/s |
| `audioBitrate2Kbps` | `integer` | oui | Débit de la deuxième paire audio, en kbit/s ; utilisé si `audioCount` vaut 4 |
| `packetSizeBytes` | `integer` | oui | Taille des paquets du flux transport, en octets |
| `eirp` | `integer` \| `null` | oui | PIRE de la porteuse vidéo (unité à préciser) |
| `sourceEirp` | `integer` \| `null` | oui | PIRE de la porteuse d'ordre de l'émetteur (unité à préciser) |
| `destinationEirp` | `integer` \| `null` | oui | PIRE de la porteuse d'ordre du donneur d'ordre (unité à préciser) |
| `redLineUpLevel` | `integer` \| `null` | oui | Niveau de line-up (unité à préciser) |

Correspondance de `standard` avec `resasat_profile_norm` :

| JSON | Valeur stockée | Signification |
| ----- | ----- | ----- |
| `"dvb"` | 0 | DVB |
| `"dvbs2"` | 1 | DVB S2 |
| `"dvbs2x"` | à définir | DVB S2X, prévu dans l'interface mais pas encore dans RESASAT |

### `Device` : équipement

Les équipements sont calculés par RESASAT à partir de la réservation, du slot et du type des stations ; ils ne correspondent à aucune table.

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `type` | `string` | oui | `"uplinkChain"` (chaîne d'émission, émetteur seulement), `"modem"` (porteuse d'ordre) ou `"ird"` (récepteur-décodeur) |
| `number` | `integer` | oui | Nombre d'équipements de ce type. `0` pour un modem indique que la station n'émet ni ne reçoit d'ordres |
| `automatic` | `boolean` | pour `modem` | La station est autorisée à monter la porteuse d'ordre sans opérateur |
| `manualLineup` | `boolean` | pour `uplinkChain` | Le line-up est fait manuellement (slot occasionnel) |

### `AmendmentState` : état d'un amendement (option O1)

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `station` | `StationRef` | oui | Station destinataire de l'amendement |
| `role` | `string` | oui | Rôle de la station dans la transmission : `"emitter"` (`source`), `"orderingCenter"` (`destination`) ou `"complementaryCenter"` (élément de `others`) |
| `amendmentState` | `string` | oui | État de l'amendement, voir ci-dessous |

Correspondance de `amendmentState` avec `resasat_amendment_state` :

| JSON | Valeur stockée | Signification |
| ----- | ----- | ----- |
| `"new"` | 0 | Nouveau, pas encore transmis |
| `"sent"` | 1 | Transmis |
| `"problem"` | 2 | Problème |
| `"acknowledged"` | 3 | Acquitté |
| `"manual"` | 4 | Manuel : station sans interface automatique |
| `"notApplicable"` | 5 | Non applicable |
| `"refused"` | 6 | Refusé |
| `"toBeAcknowledged"` | 7 | À acquitter (simulateur) |

### `AmendmentStates` : réponse de `GET …/amendment-states` (option O1)

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `id` | `integer` | oui | Numéro de la réservation |
| `version` | `integer` | oui | Version actuelle de la transmission dans RESASAT |
| `amendmentStates` | `array` de `AmendmentState` | oui | État actuel des amendements |

### `Acknowledgement` : corps de `PUT …/transmissions/{id}/acknowledgement`

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `version` | `integer` | oui | Version de la transmission acquittée |
| `state` | `string` | oui | `"sent"`, `"problem"` ou `"acknowledged"`, voir ci-dessous |
| `description` | `string` | oui | Chaîne vide pour `"acknowledged"` ; progression de la configuration pour `"sent"` ; description de l'erreur pour `"problem"` |

`state` reprend un sous-ensemble des valeurs de `amendmentState` :

| JSON | Valeur stockée | Signification |
| ----- | ----- | ----- |
| `"sent"` | 1 | Transmis : configuration en cours de prise en compte par le contrôleur |
| `"problem"` | 2 | Problème : la configuration n'a pas pu être appliquée |
| `"acknowledged"` | 3 | Acquitté : la configuration est appliquée |

### `TransmissionRef` : élément des listes de transmissions

Éléments de la réponse de `GET /transmissions` et du champ `known` de la resynchronisation.

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `id` | `integer` | oui | Numéro de la réservation |
| `version` | `integer` | oui | Version connue |

### `SyncRequest` : corps de `POST …/transmissions/sync`

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `from` | `date-time` | oui | Début de la période |
| `to` | `date-time` | oui | Fin de la période, postérieure à `from` |
| `known` | `array` de `TransmissionRef` | oui | Transmissions de la période connues du contrôleur |

### `StationStatus` : état de la station

Corps de `PUT /stations/{station}/status` et réponse de `GET /status`.

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `timestamp` | `date-time` | oui | Date de l'état |
| `mode` | `string` | oui | `"manual"` ou `"automatic"` |
| `carrier` | `string` | oui | État de la porteuse : `"off"` ou `"on"` |
| `antenna` | `Antenna` | non (O2) | Position de l'antenne |
| `weather` | `Weather` | non (O2) | Mesures météorologiques |

Correspondance avec le modèle de données (la valeur 2, « Indéterminé », est positionnée par RESASAT lui-même et n'est jamais transmise) :

| Champ | JSON | Valeur stockée |
| ----- | ----- | ----- |
| `mode` → `resasat_station_auto` | `"manual"` / `"automatic"` | 0 / 1 |
| `carrier` → `resasat_station_carry` | `"off"` / `"on"` | 0 / 1 |

`Antenna` (O2) :

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `azimuthDeg` | `number` | oui | Azimut, en degrés |
| `elevationDeg` | `number` | oui | Élévation, en degrés |
| `polarisationDeg` | `number` | oui | Angle de polarisation, en degrés |

`Weather` (O2) :

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `temperatureC` | `number` | non | Température, en °C |
| `pressureHpa` | `number` | non | Pression, en hPa |
| `humidityPercent` | `number` | non | Humidité relative, en % |
| `windSpeedMps` | `number` | non | Vitesse du vent, en m/s |

### `ReservationRequestResponse` : réponse à une proposition de réservation (option O4)

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `decision` | `string` | oui | `"accepted"` ou `"refused"` |
| `reasons` | `array` de `RefusalReason` | si `refused` | Motifs du refus |

`RefusalReason` :

| Champ | Type | Oblig. | Description |
| ----- | ----- | ----- | ----- |
| `resource` | `string` | oui | `"slot"`, `"emitter"`, `"orderingCenter"` ou `"complementaryCenter"` |
| `id` | `integer` | oui | Identifiant RESASAT de la ressource |
| `name` | `string` | oui | Nom de la ressource |
| `code` | `string` | oui | Un des codes prévus ci-dessus |

## Correspondance avec le modèle de données

Cette table donne, pour chaque champ JSON, la colonne de RESASAT (voir [datamodel/](../datamodel/)) dont il provient et la conversion appliquée. Le modèle du contrôleur local ne correspond pas exactement à celui de RESASAT : les colonnes propres à RESASAT ne sont pas transmises, et les valeurs ambiguës de RESASAT sont explicitées dans l'interface (par exemple la polarisation).

### Configuration d'une transmission

| Table.colonne | Champ JSON | Conversion |
| ----- | ----- | ----- |
| `resasat_reservation.resasat_reservation_id` | `id` | |
| `resasat_reservation.resasat_reservation_amendment` | `version` | |
| `resasat_reservation.resasat_reservation_title` | `title` | |
| `resasat_reservation.resasat_reservation_start` | `start` | Date Unix → ISO 8601 UTC |
| `resasat_reservation.resasat_reservation_end` | `end` | Date Unix → ISO 8601 UTC |
| `resasat_reservation.resasat_reservation_emiter_fk` | `source.id` | |
| `resasat_reservation.resasat_reservation_receiver_f` | `destination.id` | |
| `resasat_reservation.resasat_reservation_channel_fk` | `channel.id` | |
| `resasat_reservation.resasat_reservation_audio` | `audioCount` | NULL → 2 |
| `resasat_reservation.resasat_reservation_do` | `orderCarrierRequested` | 0 / 1 → `false` / `true` |
| `resasat_reservation.resasat_reservation_ird` | `devices[type="ird"].number` | |
| `resasat_r2s.resasat_r2s_station_fk` (où `resasat_r2s_reservation_fk` = `id`) | `others[].id` | Une ligne par station complémentaire |
| `resasat_station.resasat_station_id` | `source.id`, `destination.id`, `others[].id`, `amendmentStates[].station.id` | |
| `resasat_station.resasat_station_name` | `source.name`, `destination.name`, `others[].name`, `amendmentStates[].station.name` | |
| `resasat_satelite.resasat_satelite_id` | `satellite.id` | |
| `resasat_satelite.resasat_satelite_name` | `satellite.name` | |
| `resasat_channel.resasat_channel_id` | `channel.id` | |
| `resasat_channel.resasat_channel_name` | `channel.name` | |
| `resasat_channel.resasat_channel_video_tx_frequ` | `channel.txFrequencyHz` | MHz × 10⁶ |
| `resasat_channel.resasat_channel_polarisation` | `channel.txPolarisation` | `"H"` → `"horizontal"` ; `"V"` → `"vertical"` |
| `resasat_channel.resasat_channel_video_rx_frequ` | `channel.rxFrequencyHz` | MHz × 10⁶ |
| `resasat_channel.resasat_channel_polarisation` | `channel.rxPolarisation` | Polarisation inverse : `"H"` → `"vertical"` ; `"V"` → `"horizontal"` |
| `resasat_channel.resasat_channel_satelite_fk` | `satellite.id` | |
| `resasat_channel.resasat_channel_profile_fk` | `profile.id` | |
| `resasat_channel.resasat_channel_do_present` | présence de `orderCarrier` | 1 → présent ; NULL ou 0 → absent |
| `resasat_channel.resasat_channel_order_uplink_o` | `orderCarrier.origin.txFrequencyHz` | MHz × 10⁶ |
| `resasat_channel.resasat_channel_order_down_ori` | `orderCarrier.origin.rxFrequencyHz` | MHz × 10⁶ |
| `resasat_channel.resasat_channel_order_uplink_r` | `orderCarrier.destination.txFrequencyHz` | MHz × 10⁶ |
| `resasat_channel.resasat_channel_order_down_rec` | `orderCarrier.destination.rxFrequencyHz` | MHz × 10⁶ |
| `resasat_profile.resasat_profile_id` | `profile.id` | |
| `resasat_profile.resasat_profile_name` | `profile.name` | |
| `resasat_profile.resasat_profile_norm` | `profile.standard` | 0 / 1 → `"dvb"` / `"dvbs2"` ; `"dvbs2x"` pas encore dans RESASAT |
| `resasat_profile.resasat_profile_modulation` | `profile.modulation` | |
| `resasat_profile.resasat_profile_fec` | `profile.fec` | |
| `resasat_profile.resasat_profile_symbole_bandwi` | `profile.symbolRateBaud` | Msymboles/s × 10⁶ |
| `resasat_profile.resasat_profile_rollofffactor` | `profile.rollOffPercent` | |
| `resasat_profile.resasat_profile_dvbs2framsize` | `profile.dvbs2FrameSize` | `"Normal"` / `"Short"` → `"normal"` / `"short"` |
| `resasat_profile.resasat_profile_dvbs2pilins` | `profile.dvbs2PilotInsertion` | 0 / 1 → `false` / `true` |
| `resasat_profile.resasat_profile_vid_cod_std` | `profile.videoCodingStandard` | `"MPEG2"` → `"MPEG2"` ; `"MPEG4 AVC"` → `"MPEG4AVC"` (sans espace) |
| `resasat_profile.resasat_profile_cod_format` | `profile.codingFormat` | |
| `resasat_profile.resasat_profile_videobr_2` | `profile.videoBitrate2AudioBps` | |
| `resasat_profile.resasat_profile_videobr_4` | `profile.videoBitrate4AudioBps` | |
| — | `profile.audioBitrate1Kbps` | Pas de colonne : valeur fixe 256 |
| — | `profile.audioBitrate2Kbps` | Pas de colonne : valeur fixe 256 |
| — | `profile.packetSizeBytes` | Pas de colonne : valeur fixe 188 |
| `resasat_profile.resasat_profile_eirp` | `profile.eirp` | |
| `resasat_profile.resasat_profile_source_eirp` | `profile.sourceEirp` | |
| `resasat_profile.resasat_profile_dest_eirp` | `profile.destinationEirp` | |
| `resasat_profile.resasat_profile_red_line_up_le` | `profile.redLineUpLevel` | |
| `resasat_amendment.resasat_amendment_station_fk` | `amendmentStates[].station.id` | Amendements de la réservation `id` avec `resasat_amendment_deleted` = 0 |
| `resasat_amendment.resasat_amendment_state` | `amendmentStates[].amendmentState` | Voir la correspondance de `amendmentState` |
| — | `amendmentStates[].role` | Calculé : station = `source`, `destination` ou élément de `others` |
| — | `devices` (sauf le nombre d'IRD) | Calculé par RESASAT |

Colonnes de RESASAT non transmises :

| Table | Colonnes |
| ----- | ----- |
| `resasat_satelite` | `description`, `position`, `balise_h`, `balise_v`, `controler_na`, `rainbow_name`, `start`, `end` |
| `resasat_channel` | `description`, `start`, `end`, `permanent`, `operator_fk`, `user_fk`, `globecast_nam`, `replicat_fk`, `preference`, `bandwidth`, `is_special`, `history_id`, `validation`, `is_foreign`, `is_nodal`, `slot`, `transpondeur` |
| `resasat_profile` | `description`, `start`, `end`, `payload_bandwi`, `history_id`, `validation`, `is_foreign` |
| `resasat_station` | toutes sauf `id` et `name` |

### Acquittement

L'acquittement s'applique à l'amendement en vigueur (`resasat_amendment_deleted` = 0) de la réservation `{id}` pour la station `{station}`.

| Table.colonne | Champ JSON | Conversion |
| ----- | ----- | ----- |
| `resasat_reservation.resasat_reservation_amendment` | `version` | |
| `resasat_amendment.resasat_amendment_state` | `state` | Voir la correspondance de `state` |
| — | `description` | Pas de colonne dans le modèle de données |

### État de la station

| Table.colonne | Champ JSON | Conversion |
| ----- | ----- | ----- |
| `resasat_station.resasat_station_auto` | `mode` | 0 / 1 → `"manual"` / `"automatic"` |
| `resasat_station.resasat_station_carry` | `carrier` | 0 / 1 → `"off"` / `"on"` |
| — | `timestamp`, `antenna`, `weather` | Pas de colonne dans le modèle de données |
