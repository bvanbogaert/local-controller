# Interface entre RESASAT et les contrôleurs locaux, version 2

Questions/Remarques:
* `/api/v2` à la place de `/api/v1`.
* Dans l'offre, il y a eu confusion entre la liste des stations complémentaires `others` et l'état des amendements `amendmentStates`.
* Pour identifier les ressources (véhicule, centre, etc), on utilise l'identification numérique interne de RESASAT (`id`), mais toujours accompagnée du nom en clair pour l'affichage.  
* Quelles sont les unités des `eirp`?

## Principes

* **Transport** : 
  HTTPS, corps en JSON (UTF-8), chemins préfixés par `/api/v2`.  
* **Topologie bidirectionnelle** : 
  RESASAT et le contrôleur exposent chacun une API. RESASAT pousse les configurations vers le contrôleur.  
  Le contrôleur pousse son état et ses acquittements vers RESASAT.  
* **Authentification** : 
  Une paire de clefs privée et publique par station et pour le serveur RESASAT, dans chaque sens.  
* **Dates** : 
  ISO 8601 en UTC, par exemple `2026-10-23T19:35:00Z`.  
* **Unités**: 
  Elles sont explicites dans le nom des champs (Hz, symboles/s, bit/s).  
* **Identification des transmissions** : 
  Une transmission est identifiée par son `id` (numéro de réservation dans RESASAT) et sa `version`, qui augmente à chaque modification. Un message déjà reçu peut être rejoué sans effet ; une version plus ancienne que celle connue est ignorée.  
* **Identification des émetteurs, des donneurs d'ordre, des station complémentaires, des satellites et des slots** : 
  Les identifications sont celles utilisées par RESASAT. L'unicité est garantie par l'identifiant numérique `id` utilisé par RESASAT et est toujours accompagné par le nom en clair.  
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
| POST | `/stations/{station}/transmissions/{id}/acknowledgements` | Acquitter une configuration : appliquée ou en échec | Base |
| GET | `/stations/{station}/transmissions?from=…&to=…` | Obtenir les transmissions de la station sur une période | Base |
| POST | `/stations/{station}/transmissions/sync` | Resynchroniser : Le contrôleur envoie la liste de ce qu'il connaît.RESASAT répond en transmettant à nouveau les écarts | Base |
| PUT | `/stations/{station}/status` | Mêmes échanges que ci-dessus mais avec les champs `antenna` et `weather` | O2 |
| GET | `/resources?from=…&to=…&type=…` | Disponibilité des véhicules, des centres et des slots satellite sur une période | O3 |
| POST | `/stations/{station}/reservation-requests` | Proposer une réservation | O4 |

## Cycle de vie d'une configuration

1. RESASAT envoie la configuration (`PUT /transmissions/{id}`).  
2. Le contrôleur répond immédiatement : `received` s'il a enregistré le message, ou une erreur s'il le refuse (données invalides, équipement inconnu).   
   Dans RESASAT, la réservation passe à « Transmise » ou « Refusé ».  
3. Lorsque le contrôleur a pris en compte la configuration, il envoie un acquittement à RESASAT : `acknowledged` ou `failed` avec un code.   
   La réservation passe à « Acquittée » ou « Problème ».  
4. Sans réponse à l'étape 2, RESASAT réessaie avec une temporisation croissante. Sans acquittement dans un délai paramétrable, la réservation passe à « Problème ».  
5. Une modification suit le même chemin avec une `version` supérieure.   
   Une annulation utilise `DELETE` et est acquittée de la même manière.

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

## Exemple : configuration d'une transmission

Cet exemple reprend une transmission réelle au format actuel. 

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
  "slot": { "id": 13721, "name": "Perm 1" },
  "satellite": {
    "id": 182,
    "name": "Eutelsat 8 West B V",
    "txFrequencyHz": 14047000000,
    "txPolarisation": "horizontal",
    "rxFrequencyHz": 12547000000,
    "rxPolarisation": "vertical"
  },
  "parameters": {
    "standard": "dvbs2",
    "modulation": "8PSK",
    "fec": "5/6",
    "symbolRateBaud": 3400000,
    "rollOffPercent": 25,
    "dvbs2FrameSize": "normal",
    "dvbs2PilotInsertion": false,
    "videoCodingStandard": "MPEG4AVC",
    "codingFormat": "4:2:0",
    "videoBitrateBps": 5040000,
    "audioBitratesKbps": [256],
    "packetSizeBytes": 188,
    "eirp": null,
    "redLineUpLevel": null
  },
  "orderCarrier": {
    "txFrequencyHz": 14049160000,
    "rxFrequencyHz": 12549160000,
    "eirp": null
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
    { "station": { "id": 25, "name": "AMIENS" }, "role": "complementaryCenter", "amendmentState": "pending" }
  ]
}
```

Les unités de la PIRE (`eirp`) et du niveau de line-up doivent être clarifiées.

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
