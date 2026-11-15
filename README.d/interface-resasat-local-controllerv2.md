# Interface entre REASASAT et le contrôleur local version 2

Cette section donne les grandes lignes. Le lot 1 les précise et les fige.

## **1 Principes**

* **Transport** : HTTPS, corps en JSON (UTF-8), chemins préfixés par `/api/v1`.  
* **Topologie bidirectionnelle** : RESASAT et le contrôleur exposent chacun une API. RESASAT pousse les configurations vers le contrôleur.  
  Le contrôleur pousse son état et ses acquittements vers RESASAT.  
* **Authentification** : une paire de clefs privée et publique par station et pour le serveur RESASAT, dans chaque sens.  
* **Dates** : ISO 8601 en UTC, par exemple `2026-10-23T19:35:00Z`.  
* **Unités**: elles sont explicites dans le nom des champs (Hz, symboles/s, bit/s).  
* **Identification** : une transmission est identifiée par son `id` (numéro de réservation dans RESASAT) et sa `version`, qui augmente à chaque modification. Un message déjà reçu peut être rejoué sans effet ; une version plus ancienne que celle connue est ignorée.  
* **Erreurs** : codes HTTP usuels et corps d'erreur normalisé (RFC 9457\) avec un code applicatif.

## **2 API exposée par le contrôleur local (appelée par RESASAT)**

| Méthode | Chemin | Rôle | Périmètre |
| ----- | ----- | ----- | ----- |
| PUT | `/transmissions/{id}` | Créer ou modifier une transmission. Le corps contient la configuration complète et sa `version` | Base |
| DELETE | `/transmissions/{id}` | Annuler une transmission | Base |
| GET | `/transmissions` | Lister les transmissions connues du contrôleur (`id`, `version`) | Base |
| GET | `/status` | Lire l'état de la station à la demande | Base |

## **3 API exposée par RESASAT (appelée par le contrôleur local)**

| Méthode | Chemin | Rôle | Périmètre |
| ----- | ----- | ----- | ----- |
| PUT | `/stations/{station}/status` | Publier l'état : mode manuel/automatique, porteuse, horodatage | Base |
| POST | `/stations/{station}/transmissions/{id}/acknowledgements` | Acquitter une configuration : appliquée ou en échec | Base |
| GET | `/stations/{station}/transmissions?from=…&to=…` | Obtenir les transmissions de la station sur une période | Base |
| POST | `/stations/{station}/transmissions/sync` | Resynchroniser : Le contrôleur envoie la liste de ce qu'il connaît.RESASAT répond en transmettant à nouveau les écarts | Base |
| PUT | `/stations/{station}/status` | Mêmes échanges que ci-dessus mais avec les champs `antenna` et `weather` | O2 |
| GET | `/resources?from=…&to=…&type=…` | Disponibilité des véhicules, des centres et des slots satellite sur une période | O3 |
| POST | `/stations/{station}/reservation-requests` | Proposer une réservation | O4 |

## **4 Cycle de vie d'une configuration**

1. RESASAT envoie la configuration (`PUT /transmissions/{id}`).  
2. Le contrôleur répond immédiatement : `received` s'il a enregistré le message, ou une erreur s'il le refuse (données invalides, équipement inconnu).   
   Dans RESASAT, la réservation passe à « Transmise » ou « Refusé ».  
3. Lorsque le contrôleur a pris en compte la configuration, il envoie un acquittement à RESASAT : `acknowledged` ou `failed` avec un code.   
   La réservation passe à « Acquittée » ou « Problème ».  
4. Sans réponse à l'étape 2, RESASAT réessaie avec une temporisation croissante. Sans acquittement dans un délai paramétrable, la réservation passe à « Problème ».  
5. Une modification suit le même chemin avec une `version` supérieure.   
   Une annulation utilise `DELETE` et est acquittée de la même manière.

## **5 Resynchronisation**

Le contrôleur local appelle `POST /stations/{station}/transmissions/sync` à intervalle régulier et à chaque retour en ligne. Il envoie la liste des transmissions à venir qu'il connaît :

```
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

## **6 Exemple : configuration d'une transmission**

Cet exemple reprend une transmission réelle au format actuel. Le bloc `others` relève de l'option O1.

```
{
  "id": 369286,
  "version": 1,
  "title": "Direct Bastia",
  "start": "2026-10-23T19:35:00Z",
  "end": "2026-10-23T19:48:00Z",
  "source": "D Bastia",
  "destination": "ORLEANS",
  "slot": "Perm 1",
  "satellite": {
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
    { "station": "D Bastia", "role": "emitter", "configState": "acknowledged" },
    { "station": "ORLEANS", "role": "orderingCenter", "configState": "sent" },
    { "station": "AMIENS", "role": "complementaryCenter", "configState": "pending" }
  ]
}
```

Les unités de la PIRE (`eirp`) et du niveau de line-up doivent être clarifiées.

## **7 Exemple : état de la station**

Les blocs `antenna` et `weather` relèvent de l'option O2.

```
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

## **8 Exemple : réponse à une proposition de réservation (option O4)**

```
{
  "decision": "refused",
  "reasons": [
    { "resource": "slot", "name": "Perm 1", "code": "SLOT_UNAVAILABLE" },
    { "resource": "emitter", "name": "D Bastia", "code": "EMITTER_UNAVAILABLE" }
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

