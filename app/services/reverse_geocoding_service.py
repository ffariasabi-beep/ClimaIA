import math
import time
from threading import Lock

import requests

from flask import current_app


class ReverseGeocodingService:
    URL = "https://api-bdc.net/data/reverse-geocode"
    CACHE_SECONDS = 21600
    MAX_CACHE_ENTRIES = 512
    _cache = {}
    _cache_lock = Lock()

    @classmethod
    def lookup(cls, latitude, longitude):
        latitude = cls._coordinate(latitude, -90, 90, "latitud")
        longitude = cls._coordinate(longitude, -180, 180, "longitud")
        cache_key = (round(latitude, 4), round(longitude, 4))
        now = time.monotonic()

        with cls._cache_lock:
            cached = cls._cache.get(cache_key)
            if cached and now - cached["timestamp"] < cls.CACHE_SECONDS:
                return dict(cached["result"])
            if cached:
                cls._cache.pop(cache_key, None)

        api_key = current_app.config.get("BIGDATACLOUD_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Falta configurar BIGDATACLOUD_API_KEY para identificar "
                "la ubicación del punto seleccionado."
            )

        try:
            response = requests.get(
                cls.URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "localityLanguage": "es",
                    "key": api_key
                },
                timeout=12
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as error:
            raise RuntimeError(
                "La identificación de la ubicación tardó demasiado."
            ) from error
        except requests.HTTPError as error:
            status = (
                error.response.status_code
                if error.response is not None
                else "desconocido"
            )
            raise RuntimeError(
                f"BigDataCloud respondió con HTTP {status}."
            ) from error
        except requests.RequestException as error:
            raise RuntimeError(
                "No se pudo conectar con el servicio de geocodificación."
            ) from error
        except ValueError as error:
            raise RuntimeError(
                "BigDataCloud devolvió una respuesta inválida."
            ) from error

        if not isinstance(payload, dict):
            raise RuntimeError(
                "BigDataCloud devolvió una respuesta inválida."
            )

        country = cls._text(payload.get("countryName"))
        province = cls._text(payload.get("principalSubdivision"))
        locality = (
            cls._text(payload.get("locality"))
            or cls._text(payload.get("city"))
            or cls._administrative_locality(payload)
        )
        is_ocean = not country and not province and not locality

        result = {
            "latitude": latitude,
            "longitude": longitude,
            "locality": locality,
            "province": province,
            "country": country,
            "is_ocean": is_ocean,
            "display_name": (
                "Mar u océano"
                if is_ocean
                else ", ".join(
                    part for part in (locality, province, country) if part
                )
            )
        }

        with cls._cache_lock:
            if len(cls._cache) >= cls.MAX_CACHE_ENTRIES:
                oldest_key = min(
                    cls._cache,
                    key=lambda key: cls._cache[key]["timestamp"]
                )
                cls._cache.pop(oldest_key, None)
            cls._cache[cache_key] = {
                "timestamp": time.monotonic(),
                "result": result
            }

        return dict(result)

    @staticmethod
    def _coordinate(value, minimum, maximum, label):
        try:
            coordinate = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"La {label} no es válida.") from error
        if not math.isfinite(coordinate) or not minimum <= coordinate <= maximum:
            raise ValueError(f"La {label} está fuera de rango.")
        return coordinate

    @staticmethod
    def _text(value):
        return value.strip() if isinstance(value, str) and value.strip() else ""

    @classmethod
    def _administrative_locality(cls, payload):
        locality_info = payload.get("localityInfo")
        if not isinstance(locality_info, dict):
            return ""
        administrative = locality_info.get("administrative")
        if not isinstance(administrative, list):
            return ""
        for item in reversed(administrative):
            if isinstance(item, dict):
                name = cls._text(item.get("name"))
                if name:
                    return name
        return ""
