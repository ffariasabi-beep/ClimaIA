
import unicodedata
import os
import requests

from sqlalchemy import or_

from app.extensions import db
from app.models import Location


COUNTRY_ALIASES = {
    "argentina": "AR",
    "united kingdom": "GB",
    "uk": "GB",
    "reino unido": "GB",
    "great britain": "GB",
    "inglaterra": "GB",
    "japan": "JP",
    "japon": "JP",
    "japón": "JP",
    "france": "FR",
    "francia": "FR",
    "spain": "ES",
    "espana": "ES",
    "españa": "ES",
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
    "méxico": "MX",
    "canada": "CA",
    "canadá": "CA",
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
    "países bajos": "NL",
    "belgium": "BE",
    "belgica": "BE",
    "bélgica": "BE",
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
    "turquía": "TR",
    "south africa": "ZA",
    "sudafrica": "ZA",
    "sudáfrica": "ZA",
    "egypt": "EG",
    "egipto": "EG",
    "morocco": "MA",
    "marruecos": "MA",
    "colombia": "CO",
    "peru": "PE",
    "perú": "PE",
    "ecuador": "EC",
    "bolivia": "BO",
    "paraguay": "PY",
}


COUNTRY_NAMES = {
    "AR": "Argentina",
    "ES": "España",
    "GB": "Reino Unido",
    "JP": "Japón",
    "FR": "Francia",
    "IT": "Italia",
    "DE": "Alemania",
    "US": "Estados Unidos",
    "BR": "Brasil",
    "CL": "Chile",
    "UY": "Uruguay",
    "MX": "México",
    "CA": "Canadá",
    "CN": "China",
    "RU": "Rusia",
    "IN": "India",
    "AU": "Australia",
    "NZ": "Nueva Zelanda",
    "KR": "Corea del Sur",
    "NL": "Países Bajos",
    "BE": "Bélgica",
    "CH": "Suiza",
    "PT": "Portugal",
    "IE": "Irlanda",
    "SE": "Suecia",
    "NO": "Noruega",
    "DK": "Dinamarca",
    "FI": "Finlandia",
    "PL": "Polonia",
    "TR": "Turquía",
    "ZA": "Sudáfrica",
    "EG": "Egipto",
    "MA": "Marruecos",
    "CO": "Colombia",
    "PE": "Perú",
    "EC": "Ecuador",
    "BO": "Bolivia",
    "PY": "Paraguay",
    "AT": "Austria",
    "GR": "Grecia",
    "CZ": "Chequia",
    "RO": "Rumania",
    "UA": "Ucrania",
    "TH": "Tailandia",
    "ID": "Indonesia",
    "PH": "Filipinas",
    "VN": "Vietnam",
    "MY": "Malasia",
    "SG": "Singapur",
    "SA": "Arabia Saudita",
    "AE": "Emiratos Árabes Unidos",
    "IL": "Israel",
    "KE": "Kenia",
    "NG": "Nigeria",
    "ET": "Etiopía",
    "IS": "Islandia",
    "HR": "Croacia",
    "RS": "Serbia",
    "HU": "Hungría",
    "BG": "Bulgaria",
    "SK": "Eslovaquia",
    "SI": "Eslovenia",
    "CU": "Cuba",
    "VE": "Venezuela",
    "CR": "Costa Rica",
    "PA": "Panamá",
    "DO": "República Dominicana",
}


CITY_ALIASES = {
    "londres": "London",
    "tokio": "Tokyo",
    "nueva york": "New York",
    "pekin": "Beijing",
    "pequín": "Beijing",
    "moscu": "Moscow",
    "moscú": "Moscow",
    "roma": "Rome",
    "atenas": "Athens",
    "el cairo": "Cairo",
    "ciudad de mexico": "Mexico City",
    "ciudad de méxico": "Mexico City",
    "nueva delhi": "New Delhi",
    "seul": "Seoul",
    "seúl": "Seoul",
}


def normalize_text(value):
    """Normaliza acentos, mayúsculas y espacios."""
    value = unicodedata.normalize("NFKD", str(value or ""))

    value = "".join(
        character
        for character in value
        if not unicodedata.combining(character)
    )

    return " ".join(value.casefold().split())


def country_code_for_name(value):
    normalized_name = normalize_text(value)

    for alias, country_code in COUNTRY_ALIASES.items():
        if normalize_text(alias) == normalized_name:
            return country_code

    for country_code, country_name in COUNTRY_NAMES.items():
        if normalize_text(country_name) == normalized_name:
            return country_code

    return None


def parse_location_query(search_text):
    """
    Permite búsquedas como:
    Córdoba
    Córdoba, Argentina
    Córdoba, España
    Londres, Reino Unido
    """

    parts = [
        part.strip()
        for part in search_text.split(",")
        if part.strip()
    ]

    if len(parts) >= 2:
        city_name = ", ".join(parts[:-1])
        country_name = parts[-1]

        country_code = country_code_for_name(country_name)
    else:
        city_name = parts[0] if parts else search_text.strip()
        country_code = None

    normalized_city = normalize_text(city_name)
    alias = CITY_ALIASES.get(normalized_city)

    search_names = [city_name]

    if alias and alias.casefold() not in {
        name.casefold() for name in search_names
    }:
        search_names.append(alias)

    return search_names, country_code


class LocationService:

    @staticmethod
    def _serialize_location(location):

        country_code = location.country_code

        country_name = (
            COUNTRY_NAMES.get(country_code)
            or location.country
            or country_code
            or "País no identificado"
        )

        display_name = f"{location.name}, {country_name}"

        return {
            "id": location.id,
            "geoname_id": location.geoname_id,
            "name": location.name,
            "ascii_name": location.ascii_name,
            "country": location.country,
            "country_code": country_code,
            "country_name": country_name,
            "display_name": display_name,
            "admin_region": location.admin_region,
            "latitude": float(location.latitude),
            "longitude": float(location.longitude),
            "timezone": location.timezone,
            "population": location.population
        }

    @staticmethod
    def search_locations(search_text, limit=20):

        if not search_text or not search_text.strip():
            raise ValueError(
                "Ingresá el nombre de una localidad."
            )

        if isinstance(limit, str) and limit.strip().isdigit():
            limit = int(limit.strip())

        if type(limit) is not int or limit < 1 or limit > 100:
            raise ValueError(
                "El límite debe estar entre 1 y 100."
            )

        search_text = search_text.strip()

        normalized_query = normalize_text(search_text)
        country_only = country_code_for_name(normalized_query)

        if country_only:
            locations = (
                Location.query
                .filter(Location.country_code == country_only)
                .order_by(Location.population.desc())
                .limit(limit)
                .all()
            )

            return [
                LocationService._serialize_location(location)
                for location in locations
            ]

        search_names, country_code = parse_location_query(
            search_text
        )

        name_filters = []

        for name in search_names:
            normalized_name = normalize_text(name)

            name_filters.extend([
                Location.name.ilike(f"%{name}%"),
                Location.ascii_name.ilike(f"%{name}%"),
                Location.ascii_name.ilike(f"%{normalized_name}%")
            ])

        query = Location.query.filter(
            or_(*name_filters)
        )

        if country_code:
            query = query.filter(
                Location.country_code == country_code
            )

        locations = (
            query
            .order_by(
                Location.name.ilike(search_names[0]).desc(),
                Location.ascii_name.ilike(
                    normalize_text(search_names[0])
                ).desc(),
                Location.population.desc()
            )
            .limit(limit)
            .all()
        )

        if locations:
            return [
                LocationService._serialize_location(location)
                for location in locations
            ]

        return LocationService._search_geonames(
            search_names[0],
            country_code,
            limit
        )

    @staticmethod
    def _search_geonames(search_name, country_code=None, limit=20):

        username = os.getenv("GEONAMES_USERNAME")

        if not username:
            raise RuntimeError(
                "Falta configurar GEONAMES_USERNAME en el archivo .env."
            )

        params = {
            "name": search_name,
            "featureClass": "P",
            "maxRows": limit,
            "lang": "es",
            "username": username
        }

        if country_code:
            params["country"] = country_code

        try:
            response = requests.get(
                "https://api.geonames.org/searchJSON",
                params=params,
                timeout=15
            )

            response.raise_for_status()
            data = response.json()

        except requests.RequestException as error:
            raise RuntimeError(
                f"No se pudo consultar GeoNames: {error}"
            ) from error

        if "status" in data:
            message = data["status"].get(
                "message",
                "Error desconocido de GeoNames."
            )
            raise RuntimeError(f"GeoNames: {message}")

        results = []

        for item in data.get("geonames", []):

            geoname_id = item.get("geonameId")

            if not geoname_id:
                continue

            location = Location.query.filter_by(
                geoname_id=int(geoname_id)
            ).first()

            if location is None:

                location = Location(
                    geoname_id=int(geoname_id),
                    name=item.get("name") or search_name,
                    ascii_name=item.get("asciiName") or item.get("name"),
                    country=item.get("countryName"),
                    country_code=item.get("countryCode"),
                    admin_region=item.get("adminName1"),
                    latitude=float(item["lat"]),
                    longitude=float(item["lng"]),
                    timezone=None,
                    population=int(item.get("population") or 0)
                )

                db.session.add(location)

                try:
                    db.session.commit()

                except Exception:
                    db.session.rollback()

                    location = Location.query.filter_by(
                        geoname_id=int(geoname_id)
                    ).first()

                    if location is None:
                        raise

            results.append(
                LocationService._serialize_location(location)
            )

        return results

    @staticmethod
    def get_by_geoname_id(geoname_id):

        if not isinstance(geoname_id, int):
            raise ValueError(
                "El identificador GeoNames debe ser un entero."
            )

        location = Location.query.filter_by(
            geoname_id=geoname_id
        ).first()

        if location is None:
            return None

        return LocationService._serialize_location(location)
