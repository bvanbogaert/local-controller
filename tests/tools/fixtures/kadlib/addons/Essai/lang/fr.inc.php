<?php
// Fichier langue d'essai, au format de kadlib, pour tests/tools/test_export_oracle_db.py.
// Il correspond au schéma d'essai du test : tables RESASAT_CHANNEL et RESASAT_STATION.

$lcl_filter = "(resasat_station_id > 0)";

// Nom d'une table
$resasat_channel = "Slot";
// Pour cette table, seul le pluriel existe
$resasat_stations = "Stations <b>fixes</b>";

$resasat_channel_id = "Index";
$resasat_channel_id_mask = array("AUTO");

// Entités HTML et taille prise dans defines.inc.php
$resasat_channel_name = "Nom abr&eacute;g&eacute;";
$resasat_channel_name_mask = array("TEXT", "maxlength=$snl size=$snl");

// Clé étrangère vers une table exportée, avec une option de kadlib
$resasat_channel_station_fk = "Station";
$resasat_channel_station_fk_mask = array("FKORNULL", "resasat_station", "resasat_station_id",
	"resasat_station_name", KADLIB_WHERE_CLAUSE => "where $lcl_filter");

// Clé étrangère vers une table hors du préfixe RESASAT_
$resasat_channel_owner_fk = "Utilisateur";
$resasat_channel_owner_fk_mask = array("FK", "users", "ID", "loginname");

// Énumération courte : constantes connues, constante inconnue, clé texte
$resasat_station_id = "&Eacute;tat | validation";
$resasat_station_id_mask = array("ENUM", array(
	CHANNEL_NEW => "Nouveau",
	CHANNEL_ACCEPTED => "Accept&eacute;",
	CHANNEL_UNKNOWN => "Inconnu",
	"H" => "Horizontale (X)"));

// Énumération longue : elle sort du tableau des colonnes
$resasat_station_start_mask = array("ENUMORNULL", array(
	1 => "Un", 2 => "Deux", 3 => "Trois", 4 => "Quatre", 5 => "Cinq", 6 => "Six",
	7 => "Sept", 8 => "Huit", 9 => "Neuf", 10 => "Dix", 11 => "Onze"));

// Variable sans rapport avec le schéma
$resasat_add = "Ajouter";
