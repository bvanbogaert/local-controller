"""Tables de configuration importées de RESASAT."""

# L'ordre compte : une table suit toujours celles qu'elle référence. L'import
# ajoute et modifie dans cet ordre, et supprime dans l'ordre inverse.
IMPORTED_TABLES = (
    "resasat_region",
    "resasat_operator",
    "resasat_satelite",
    "resasat_profile",
    "resasat_station_type",
    "resasat_station",
    "resasat_channel",
    "resasat_st2c",
)

# Tables de liens : une ligne ne vaut que par les enregistrements qu'elle relie.
LINK_TABLES = ("resasat_st2c",)

# Tables de l'export de RESASAT qui ne sont jamais importées, avec le motif
EXCLUDED_TABLES = {
    "users": "données personnelles, non importées",
    "resasat_s2c": "non importée : la compatibilité passe par les types de station",
}
