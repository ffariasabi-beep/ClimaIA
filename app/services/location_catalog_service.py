import csv
import unicodedata
from pathlib import Path


COUNTRY_ALIASES = {
    "argentina": "AR",
    "united kingdom": "GB",
    "uk": "GB",
    "reino unido": "GB",
    "great britain": "GB",
    "inglaterra": "GB",
    "japan": "JP",
    "japon": "JP",
    "france": "FR",
    "francia": "FR",
    "spain": "ES",
    "espana": "ES",
    "italy": "IT",
    "italia": "IT",
    "germany": "DE",
    "alemania": "DE",
    "united states": "US",
    "estados unidos": "US",
    "usa": "US",
    "brazil": "BR",
    "brasil": "BR",
    "chile": "CL",
    "uruguay": "UY",
    "mexico": "MX",
    "canada": "CA",
    "china": "CN",
    "russia": "RU",
    "rusia": "RU",
    "india": "IN",
    "australia": "AU",
    "new zealand": "NZ",
    "nueva zelanda": "NZ",
    "south korea": "KR",
    "corea del sur": "KR",
    "netherlands": "NL",
    "paises bajos": "NL",
    "belgium": "BE",
    "belgica": "BE",
    "switzerland": "CH",
    "suiza": "CH",
    "portugal": "PT",
    "ireland": "IE",
    "irlanda": "IE",
    "sweden": "SE",
    "suecia": "SE",
    "norway": "NO",
    "noruega": "NO",
    "denmark": "DK",
    "dinamarca": "DK",
    "finland": "FI",
    "finlandia": "FI",
    "poland": "PL",
    "polonia": "PL",
    "turkey": "TR",
    "turquia": "TR",
    "south africa": "ZA",
    "sudafrica": "ZA",
    "egypt": "EG",
    "egipto": "EG",
    "morocco": "MA",
    "marruecos": "MA",
    "colombia": "CO",
    "peru": "PE",
    "ecuador": "EC",
    "bolivia": "BO",
    "paraguay": "PY",
}


CITY_ALIASES = {
    "londres": "London",
    "tokio": "Tokyo",
    "nueva york": "New York",
    "pekin": "Beijing",
    "moscu": "Moscow",
    "roma": "Rome",
    "atenas": "Athens",
    "el cairo": "Cairo",
    "ciudad de mexico": "Mexico City",
    "nueva delhi": "New Delhi",
    "seul": "Seoul",
}


def normalize_text(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(
        character
        for character in value
        if not unicodedata.combining(character)
    )
    return " ".join(value.casefold().split())


def parse_location_query(search_text):
    parts = [part.strip() for part in search_text.split(",") if part.strip()]

    if len(parts) >= 2:
        city_name = ", ".join(parts[:-1])
        country_code = COUNTRY_ALIASES.get(normalize_text(parts[-1]))
    else:
        city_name = parts[0] if parts else search_text.strip()
        country_code = None

    normalized_city = normalize_text(city_name)
    alias = CITY_ALIASES.get(normalized_city)

    search_names = [city_name]
    if alias:
        search_names.append(alias)

    return search_names, country_code


class LocationCatalogService:
    """
    Lee el catálogo mundial de localidades de GeoNames.

    Archivo esperado:
    data/locations/cities15000.txt

    El archivo original utiliza columnas separadas por tabulaciones.
    """

    CATALOG_PATH = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "locations"
        / "cities15000.txt"
    )

    _locations_cache = None

    @classmethod
    def load_locations(cls, force_reload=False):
        """
        Carga las localidades desde el archivo GeoNames.
        La información queda almacenada en memoria para evitar
        leer el archivo repetidamente.
        """

        if cls._locations_cache is not None and not force_reload:
            return cls._locations_cache

        if not cls.CATALOG_PATH.exists():
            raise FileNotFoundError(
                "No se encontró el catálogo mundial de localidades. "
                "Verificá que cities15000.txt esté en "
                "data/locations/."
            )

        locations = []
        invalid_rows = 0

        try:
            with open(
                cls.CATALOG_PATH,
                "r",
                encoding="utf-8"
            ) as file:

                reader = csv.reader(
                    file,
                    delimiter="\t"
                )

                for row in reader:

                    if len(row) < 19:
                        invalid_rows += 1
                        continue

                    try:
                        location = {
                            "geoname_id": int(row[0]),
                            "name": row[1],
                            "ascii_name": row[2],
                            "latitude": float(row[4]),
                            "longitude": float(row[5]),
                            "feature_class": row[6],
                            "feature_code": row[7],
                            "country_code": row[8],
                            "admin1_code": row[10],
                            "admin2_code": row[11],
                            "population": int(row[14] or 0),
                            "timezone": row[17]
                        }

                        if not location["name"]:
                            invalid_rows += 1
                            continue

                        locations.append(location)

                    except (ValueError, IndexError):
                        invalid_rows += 1
                        continue

        except OSError as error:
            raise RuntimeError(
                "No se pudo leer el catálogo de localidades."
            ) from error

        if not locations:
            raise ValueError(
                "El catálogo no contiene localidades válidas. "
                "Verificá que el archivo GeoNames esté completo."
            )

        cls._locations_cache = locations

        return locations

    @classmethod
    def get_global_candidates(
        cls,
        exclude_geoname_id=None,
        limit=None
    ):
        """
        Devuelve localidades reales para comparar perfiles climáticos.
        No inventa coordenadas ni nombres.
        """

        locations = cls.load_locations()

        candidates = [
            location
            for location in locations
            if location["geoname_id"] != exclude_geoname_id
        ]

        candidates.sort(
            key=lambda location: location["population"],
            reverse=True
        )

        if limit is not None:
            if limit < 1:
                raise ValueError(
                    "El límite debe ser mayor que cero."
                )

            candidates = candidates[:limit]

        return candidates

    @classmethod
    def search_locations(cls, search_text, limit=20):
        """
        Busca localidades por nombre, aceptando acentos,
        algunos nombres traducidos y país opcional.
        """

        if not search_text or not search_text.strip():
            raise ValueError(
                "Ingresá el nombre de una localidad."
            )

        if limit < 1:
            raise ValueError(
                "El límite debe ser mayor que cero."
            )

        search_names, country_code = parse_location_query(
            search_text.strip()
        )

        normalized_names = [
            normalize_text(name)
            for name in search_names
        ]

        locations = cls.load_locations()

        matches = [
            location
            for location in locations
            if (
                not country_code
                or location["country_code"] == country_code
            )
            and any(
                normalized_name in normalize_text(location["name"])
                or normalized_name in normalize_text(location["ascii_name"])
                for normalized_name in normalized_names
            )
        ]

        matches.sort(
            key=lambda location: (
                0 if normalize_text(location["name"]) in normalized_names
                or normalize_text(location["ascii_name"]) in normalized_names
                else 1,
                -location["population"]
            )
        )

        return matches[:limit]

    @classmethod
    def get_catalog_statistics(cls):
        """
        Devuelve información general del catálogo cargado.
        """

        locations = cls.load_locations()

        countries = {
            location["country_code"]
            for location in locations
            if location["country_code"]
        }

        return {
            "total_locations": len(locations),
            "total_countries": len(countries),
            "catalog_file": cls.CATALOG_PATH.name
        }
