
import json
import math
import os
import tempfile
import time
from datetime import date, datetime, timezone
from threading import Lock

import requests

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required
from app.extensions import db
from app.models import ClimateProfile, Location
from app.services.ai_service import AIService
from app.services.ai_provider_service import AIProviderService
from app.services.location_service import LocationService
from app.services.weather_service import (
    WeatherRateLimitError,
    WeatherService
)
from app.services.similarity_service import SimilarityService
from app.services.climate_anomaly_service import ClimateAnomalyService
from app.services.territory_research_service import TerritoryResearchService
from app.services.territory_analytics_service import (
    TerritoryAnalyticsError,
    TerritoryAnalyticsService
)
from app.services.reverse_geocoding_service import ReverseGeocodingService


api_bp = Blueprint("api", __name__, url_prefix="/api")


# --------------------------------------------------
# CACHÉ DEL ATLAS CLIMÁTICO
# --------------------------------------------------

ATLAS_CACHE = {
    "timestamp": 0,
    "points": None
}

ATLAS_CACHE_SECONDS = 600

ATLAS_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ATLAS_ANOMALY_CACHE = {
    "timestamp": 0,
    "profiles": None,
    "through_year": None,
    "fetched_at": None
}
ATLAS_ANOMALY_CACHE_SECONDS = 86400
ATLAS_ANOMALY_CACHE_LOCK = Lock()
ATLAS_REGION_PROFILE_CACHE = {}
ATLAS_ARCHIVE_COOLDOWN = {"until": 0}
ATLAS_ARCHIVE_DEFAULT_COOLDOWN_SECONDS = 300
ATLAS_LOCAL_PROFILE_MAX_DISTANCE_KM = 5


def _atlas_rate_limit_response(retry_after_seconds):
    retry_after = max(1, math.ceil(retry_after_seconds))
    response = jsonify({
        "success": False,
        "error": (
            "Open-Meteo limitó temporalmente las consultas (HTTP 429). "
            "No se recibieron datos; esperá antes de volver a intentarlo."
        ),
        "retry_after_seconds": retry_after
    })
    response.headers["Retry-After"] = str(retry_after)
    return response, 429


def _active_atlas_rate_limit_response():
    remaining = ATLAS_ARCHIVE_COOLDOWN["until"] - time.monotonic()
    if remaining <= 0:
        return None
    return _atlas_rate_limit_response(remaining)


def _record_atlas_rate_limit(error):
    retry_after = (
        error.retry_after
        if error.retry_after and error.retry_after > 0
        else ATLAS_ARCHIVE_DEFAULT_COOLDOWN_SECONDS
    )
    ATLAS_ARCHIVE_COOLDOWN["until"] = max(
        ATLAS_ARCHIVE_COOLDOWN["until"],
        time.monotonic() + retry_after
    )
    return _atlas_rate_limit_response(retry_after)


def _load_atlas_anomaly_cache():
    with ATLAS_ANOMALY_CACHE_LOCK:
        if ATLAS_ANOMALY_CACHE["profiles"] is not None:
            return

        cache_path = os.path.join(
            current_app.instance_path,
            "atlas_anomaly_profiles.json"
        )
        try:
            with open(cache_path, encoding="utf-8") as cache_file:
                cached = json.load(cache_file)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as error:
            current_app.logger.warning(
                "No se pudo leer la caché histórica del atlas: %s",
                error
            )
            return

        profiles = cached.get("profiles") if isinstance(cached, dict) else None
        through_year = (
            cached.get("through_year")
            if isinstance(cached, dict)
            else None
        )
        fetched_at = (
            cached.get("fetched_at")
            if isinstance(cached, dict)
            else None
        )
        if (
            not isinstance(profiles, list)
            or not profiles
            or not isinstance(through_year, int)
            or not isinstance(fetched_at, str)
        ):
            current_app.logger.warning(
                "La caché histórica del atlas no tiene un formato válido."
            )
            return

        try:
            fetched_datetime = datetime.fromisoformat(
                fetched_at.replace("Z", "+00:00")
            )
            if fetched_datetime.tzinfo is None:
                fetched_datetime = fetched_datetime.replace(
                    tzinfo=timezone.utc
                )
        except ValueError as error:
            current_app.logger.warning(
                "La fecha de la caché histórica del atlas no es válida: %s",
                error
            )
            return

        age_seconds = max(
            0,
            (datetime.now(timezone.utc) - fetched_datetime).total_seconds()
        )
        ATLAS_ANOMALY_CACHE.update({
            "timestamp": time.monotonic() - age_seconds,
            "profiles": profiles,
            "through_year": through_year,
            "fetched_at": fetched_datetime.isoformat()
        })


def _persist_atlas_anomaly_cache():
    cache_path = os.path.join(
        current_app.instance_path,
        "atlas_anomaly_profiles.json"
    )
    temporary_path = None
    try:
        os.makedirs(current_app.instance_path, exist_ok=True)
        cache_data = {
            "profiles": ATLAS_ANOMALY_CACHE["profiles"],
            "through_year": ATLAS_ANOMALY_CACHE["through_year"],
            "fetched_at": ATLAS_ANOMALY_CACHE["fetched_at"]
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=current_app.instance_path,
            delete=False
        ) as cache_file:
            json.dump(cache_data, cache_file, allow_nan=False)
            temporary_path = cache_file.name
        os.replace(temporary_path, cache_path)
    except (OSError, TypeError, ValueError) as error:
        current_app.logger.warning(
            "No se pudo guardar la caché histórica del atlas: %s",
            error
        )
        if temporary_path and os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError as cleanup_error:
                current_app.logger.warning(
                    "No se pudo limpiar el archivo temporal de caché: %s",
                    cleanup_error
                )


def _cached_atlas_anomaly_response(year, warning):
    with ATLAS_ANOMALY_CACHE_LOCK:
        profiles = ATLAS_ANOMALY_CACHE["profiles"]
        through_year = ATLAS_ANOMALY_CACHE["through_year"]
        fetched_at = ATLAS_ANOMALY_CACHE["fetched_at"]
        if (
            not profiles
            or through_year is None
            or through_year < year
        ):
            return None

        try:
            points = ClimateAnomalyService.summarize_grid_year(
                profiles,
                year
            )
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            current_app.logger.warning(
                "La caché histórica no incluye datos utilizables para %s: %s",
                year,
                error
            )
            return None

    return jsonify({
        "success": True,
        "points": points,
        "year": year,
        "reference_period": "1991-2020",
        "source": "Open-Meteo Historical Weather API · reanalysis",
        "dataset_updated_at": (
            fetched_at or datetime.now(timezone.utc).isoformat()
        ),
        "cached": True,
        "stale": True,
        "warning": warning
    })


def _find_stored_climate_profile(latitude, longitude):
    latitude = float(latitude)
    longitude = float(longitude)
    latitude_delta = ATLAS_LOCAL_PROFILE_MAX_DISTANCE_KM / 110.574
    longitude_scale = max(
        111.32 * abs(math.cos(math.radians(latitude))),
        1e-6
    )
    longitude_delta = min(
        180,
        ATLAS_LOCAL_PROFILE_MAX_DISTANCE_KM / longitude_scale
    )

    candidates = (
        ClimateProfile.query
        .join(Location, ClimateProfile.location_id == Location.id)
        .filter(
            ClimateProfile.period_start == date(1991, 1, 1),
            ClimateProfile.period_end == date(2020, 12, 31),
            Location.latitude.between(
                latitude - latitude_delta,
                latitude + latitude_delta
            ),
            Location.longitude.between(
                max(-180, longitude - longitude_delta),
                min(180, longitude + longitude_delta)
            )
        )
        .all()
    )

    nearest = None
    for profile in candidates:
        features = profile.feature_vector or {}
        monthly_profile = features.get("monthly_profile")
        if not isinstance(monthly_profile, list) or not monthly_profile:
            continue

        location = profile.location
        profile_latitude = math.radians(float(location.latitude))
        target_latitude = math.radians(latitude)
        latitude_difference = target_latitude - profile_latitude
        longitude_difference = math.radians(
            float(location.longitude) - longitude
        )
        haversine = (
            math.sin(latitude_difference / 2) ** 2
            + math.cos(target_latitude)
            * math.cos(profile_latitude)
            * math.sin(longitude_difference / 2) ** 2
        )
        distance_km = 6371 * 2 * math.asin(
            math.sqrt(min(1, max(0, haversine)))
        )

        if distance_km <= ATLAS_LOCAL_PROFILE_MAX_DISTANCE_KM and (
            nearest is None or distance_km < nearest["distance_km"]
        ):
            nearest = {
                "profile": profile,
                "distance_km": distance_km
            }

    if nearest is None:
        return None

    profile = nearest["profile"]
    location = profile.location
    return {
        "availability": "available",
        "profile_type": "monthly_normal",
        "source": (
            "Base de datos local de ClimaIA · "
            f"{profile.dataset_code}"
        ),
        "reference_period": "1991-2020",
        "reference_location": {
            "name": location.name,
            "country_code": location.country_code,
            "distance_km": round(nearest["distance_km"], 1)
        },
        "monthly_profile": profile.feature_vector["monthly_profile"],
        "summary_statistics": profile.summary_statistics or {}
    }


def _unavailable_climate_profile():
    return {
        "availability": "unavailable",
        "profile_type": "unavailable",
        "source": "Open-Meteo Historical Weather API",
        "reference_period": "1991-2020",
        "limitation": (
            "El proveedor alcanzó temporalmente su límite de consultas; "
            "no hay un perfil local cercano disponible."
        )
    }


# --------------------------------------------------
# 1. BUSCAR LOCALIDADES
# --------------------------------------------------

@api_bp.route("/locations/search", methods=["GET"])
@login_required
def search_locations():

    search_text = request.args.get("q", "").strip()

    if len(search_text) < 2:
        return jsonify({
            "success": False,
            "error": "Ingresá al menos dos caracteres."
        }), 400

    try:
        locations = LocationService.search_locations(
            search_text,
            limit=15
        )

        return jsonify({
            "success": True,
            "count": len(locations),
            "locations": locations
        })

    except ValueError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception:
        return jsonify({
            "success": False,
            "error": "No se pudieron buscar las localidades."
        }), 500


# --------------------------------------------------
# 2. CONSULTAR CLIMA DE UNA LOCALIDAD GEO NAMES
# --------------------------------------------------

@api_bp.route(
    "/locations/<int:geoname_id>/weather",
    methods=["GET"]
)
@login_required
def get_location_weather(geoname_id):

    try:
        location = LocationService.get_by_geoname_id(
            geoname_id
        )

        if location is None:
            return jsonify({
                "success": False,
                "error": "No se encontró la localidad solicitada."
            }), 404

        weather = WeatherService.get_weather(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone=location.get("timezone") or "auto"
        )

        return jsonify({
            "success": True,
            "location": location,
            "weather": weather
        })

    except (ValueError, RuntimeError) as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 502

    except Exception:
        return jsonify({
            "success": False,
            "error": "No se pudo consultar el clima de esta localidad."
        }), 500


# --------------------------------------------------
# 3. CONSULTAR CLIMA DE CUALQUIER PUNTO DEL MAPA
# --------------------------------------------------

@api_bp.route("/weather/coordinates", methods=["GET"])
@login_required
def get_weather_by_coordinates():

    latitude_text = request.args.get("latitude", "")
    longitude_text = request.args.get("longitude", "")

    try:
        latitude = float(latitude_text)
        longitude = float(longitude_text)

        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ValueError("Las coordenadas no son válidas.")

        if not -90 <= latitude <= 90:
            raise ValueError("La latitud debe estar entre -90 y 90.")

        if not -180 <= longitude <= 180:
            raise ValueError("La longitud debe estar entre -180 y 180.")

        weather = WeatherService.get_weather(
            latitude=latitude,
            longitude=longitude,
            timezone="auto"
        )

        return jsonify({
            "success": True,
            "location": {
                "name": "Punto seleccionado en el mapa",
                "latitude": latitude,
                "longitude": longitude,
                "country_name": None
            },
            "weather": weather
        })

    except (TypeError, ValueError) as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except RuntimeError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 502

    except Exception:
        return jsonify({
            "success": False,
            "error": "No se pudo consultar el clima de esas coordenadas."
        }), 500


@api_bp.route("/geocoding/reverse", methods=["GET"])
@login_required
def reverse_geocode_coordinates():
    try:
        latitude = float(request.args.get("latitude", ""))
        longitude = float(request.args.get("longitude", ""))
        result = ReverseGeocodingService.lookup(latitude, longitude)
        return jsonify({"success": True, "location": result})
    except ValueError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 400
    except RuntimeError as error:
        status = (
            503
            if not current_app.config.get("BIGDATACLOUD_API_KEY")
            else 502
        )
        return jsonify({
            "success": False,
            "error": str(error)
        }), status


# --------------------------------------------------
# 4. OBTENER GRILLA METEOROLÓGICA MUNDIAL
# --------------------------------------------------

@api_bp.route("/atlas/grid", methods=["GET"])
@login_required
def get_atlas_grid():

    force_refresh = request.args.get("refresh") == "1"

    current_time = time.monotonic()

    # Reutilizar datos durante diez minutos.
    if (
        not force_refresh
        and ATLAS_CACHE["points"] is not None
        and current_time - ATLAS_CACHE["timestamp"] < ATLAS_CACHE_SECONDS
    ):
        return jsonify({
            "success": True,
            "points": ATLAS_CACHE["points"],
            "cached": True,
            "resolution": "12 columnas x 6 filas",
            "source": "Open-Meteo Forecast API"
        })

    try:

        coordinates = ClimateAnomalyService.grid_coordinates()

        latitude_values = ",".join(
            str(point["latitude"])
            for point in coordinates
        )

        longitude_values = ",".join(
            str(point["longitude"])
            for point in coordinates
        )

        response = requests.get(
            ATLAS_FORECAST_URL,
            params={
                "latitude": latitude_values,
                "longitude": longitude_values,
                "current": (
                    "temperature_2m,"
                    "relative_humidity_2m,"
                    "precipitation,"
                    "wind_speed_10m"
                ),
                "timezone": "UTC"
            },
            timeout=45
        )

        response.raise_for_status()

        data = response.json()

        # Con múltiples coordenadas Open-Meteo devuelve
        # una lista de respuestas.
        if isinstance(data, dict):
            data = [data]

        if not isinstance(data, list) or len(data) != len(coordinates):
            raise RuntimeError(
                "La cantidad de datos recibidos no coincide "
                "con la grilla solicitada."
            )

        points = []

        for index, item in enumerate(data):

            current = item.get("current", {})

            points.append({
                "latitude": coordinates[index]["latitude"],
                "longitude": coordinates[index]["longitude"],

                "temperature": current.get(
                    "temperature_2m"
                ),

                "humidity": current.get(
                    "relative_humidity_2m"
                ),

                "precipitation": current.get(
                    "precipitation"
                ),

                "wind_speed": current.get(
                    "wind_speed_10m"
                ),

                "time": current.get("time")
            })

        ATLAS_CACHE["points"] = points
        ATLAS_CACHE["timestamp"] = time.monotonic()

        return jsonify({
            "success": True,
            "points": points,
            "cached": False,
            "resolution": "12 columnas x 6 filas",
            "source": "Open-Meteo"
        })

    except requests.RequestException as error:

        print(
            "ERROR AL CONSULTAR LA GRILLA CLIMÁTICA:",
            error
        )

        return jsonify({
            "success": False,
            "error": "No se pudo conectar con el servicio meteorológico."
        }), 502

    except RuntimeError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 502

    except Exception as error:

        print(
            "ERROR EN EL ATLAS CLIMÁTICO:",
            error
        )

        return jsonify({
            "success": False,
            "error": "No se pudo procesar la grilla climática."
        }), 500


@api_bp.route("/atlas/anomalies", methods=["GET"])
@login_required
def get_atlas_anomalies():
    latest_complete_year = date.today().year - 1
    requested_year = request.args.get("year", str(latest_complete_year))

    try:
        year = int(requested_year)
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "El año solicitado no es válido."
        }), 400

    if not (
        ClimateAnomalyService.REFERENCE_START_YEAR
        <= year
        <= latest_complete_year
    ):
        return jsonify({
            "success": False,
            "error": (
                "Elegí un año completo entre 1991 y "
                f"{latest_complete_year}."
            )
        }), 400

    _load_atlas_anomaly_cache()
    force_refresh = request.args.get("refresh") == "1"
    current_time = time.monotonic()
    cache_is_valid = (
        not force_refresh
        and ATLAS_ANOMALY_CACHE["profiles"] is not None
        and ATLAS_ANOMALY_CACHE["through_year"] >= year
        and current_time - ATLAS_ANOMALY_CACHE["timestamp"]
        < ATLAS_ANOMALY_CACHE_SECONDS
    )

    cache_refreshed = False
    if not cache_is_valid:
        rate_limit_response = _active_atlas_rate_limit_response()
        if rate_limit_response:
            return (
                _cached_atlas_anomaly_response(
                    year,
                    "No se pudo actualizar el archivo; se muestran "
                    "los últimos datos guardados."
                )
                or rate_limit_response
            )

        try:
            rate_limit_response = None
            with ATLAS_ANOMALY_CACHE_LOCK:
                current_time = time.monotonic()
                cache_is_valid = (
                    not force_refresh
                    and ATLAS_ANOMALY_CACHE["profiles"] is not None
                    and ATLAS_ANOMALY_CACHE["through_year"]
                    >= latest_complete_year
                    and current_time - ATLAS_ANOMALY_CACHE["timestamp"]
                    < ATLAS_ANOMALY_CACHE_SECONDS
                )

                if not cache_is_valid:
                    rate_limit_response = (
                        _active_atlas_rate_limit_response()
                    )
                    if not rate_limit_response:
                        profiles = (
                            ClimateAnomalyService
                            .fetch_global_annual_profiles(
                                latest_complete_year
                            )
                        )
                        ATLAS_ANOMALY_CACHE.update({
                            "timestamp": time.monotonic(),
                            "profiles": profiles,
                            "through_year": latest_complete_year,
                            "fetched_at": datetime.now(
                                timezone.utc
                            ).isoformat()
                        })
                        cache_refreshed = True

            if rate_limit_response:
                return (
                    _cached_atlas_anomaly_response(
                        year,
                        "No se pudo actualizar el archivo; se muestran "
                        "los últimos datos guardados."
                    )
                    or rate_limit_response
                )

        except WeatherRateLimitError as error:
            rate_limit_response = _record_atlas_rate_limit(error)
            return (
                _cached_atlas_anomaly_response(
                    year,
                    "Open-Meteo limitó temporalmente las consultas; "
                    "se muestran los últimos datos guardados."
                )
                or rate_limit_response
            )

        except RuntimeError as error:
            cached_response = _cached_atlas_anomaly_response(
                year,
                "No se pudo actualizar el archivo; se muestran "
                "los últimos datos guardados."
            )
            if cached_response:
                return cached_response
            return jsonify({
                "success": False,
                "error": str(error)
            }), 502

        except Exception as error:
            current_app.logger.exception(
                "No se pudieron actualizar las anomalías del atlas."
            )
            cached_response = _cached_atlas_anomaly_response(
                year,
                "No se pudo actualizar el archivo; se muestran "
                "los últimos datos guardados."
            )
            if cached_response:
                return cached_response
            return jsonify({
                "success": False,
                "error": "No se pudieron calcular las anomalías del atlas."
            }), 500

    if cache_refreshed:
        _persist_atlas_anomaly_cache()

    try:
        points = ClimateAnomalyService.summarize_grid_year(
            ATLAS_ANOMALY_CACHE["profiles"],
            year
        )
    except RuntimeError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 502

    return jsonify({
        "success": True,
        "points": points,
        "year": year,
        "reference_period": "1991-2020",
        "source": "Open-Meteo Historical Weather API · reanalysis",
        "dataset_updated_at": (
            ATLAS_ANOMALY_CACHE["fetched_at"]
            or datetime.now(timezone.utc).isoformat()
        ),
        "cached": cache_is_valid
    })


def _get_or_fetch_atlas_region_profile(
    latitude,
    longitude,
    profile_end_year
):
    cache_key = (
        round(latitude, 4),
        round(longitude, 4),
        profile_end_year
    )
    current_time = time.monotonic()
    cached_profile = ATLAS_REGION_PROFILE_CACHE.get(cache_key)
    was_cached = (
        cached_profile is not None
        and current_time - cached_profile["timestamp"]
        < ATLAS_ANOMALY_CACHE_SECONDS
    )

    if not was_cached:
        with ATLAS_ANOMALY_CACHE_LOCK:
            cached_profile = ATLAS_REGION_PROFILE_CACHE.get(cache_key)
            current_time = time.monotonic()
            was_cached = (
                cached_profile is not None
                and current_time - cached_profile["timestamp"]
                < ATLAS_ANOMALY_CACHE_SECONDS
            )
            if not was_cached:
                for expired_key, entry in tuple(
                    ATLAS_REGION_PROFILE_CACHE.items()
                ):
                    if (
                        current_time - entry["timestamp"]
                        >= ATLAS_ANOMALY_CACHE_SECONDS
                    ):
                        ATLAS_REGION_PROFILE_CACHE.pop(
                            expired_key,
                            None
                        )

                if len(ATLAS_REGION_PROFILE_CACHE) >= 32:
                    oldest_key = min(
                        ATLAS_REGION_PROFILE_CACHE,
                        key=lambda key: (
                            ATLAS_REGION_PROFILE_CACHE[key]["timestamp"]
                        )
                    )
                    ATLAS_REGION_PROFILE_CACHE.pop(oldest_key, None)

                rate_limit_response = _active_atlas_rate_limit_response()
                if rate_limit_response:
                    return None, False, rate_limit_response

                weather_profile = (
                    ClimateAnomalyService.fetch_regional_annual_profile(
                        latitude=latitude,
                        longitude=longitude,
                        end_year=profile_end_year
                    )
                )
                cached_profile = {
                    "timestamp": time.monotonic(),
                    "dataset_updated_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "profile": weather_profile
                }
                ATLAS_REGION_PROFILE_CACHE[cache_key] = cached_profile

    return cached_profile, was_cached, None


@api_bp.route("/atlas/region-profile", methods=["GET"])
@login_required
def get_atlas_region_profile():
    latest_complete_year = date.today().year - 1

    try:
        latitude = float(request.args.get("latitude", ""))
        longitude = float(request.args.get("longitude", ""))
        start_year = int(request.args.get(
            "start_year",
            str(ClimateAnomalyService.REFERENCE_START_YEAR)
        ))
        end_year = int(request.args.get(
            "end_year",
            str(latest_complete_year)
        ))
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Las coordenadas o el período no son válidos."
        }), 400

    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        return jsonify({
            "success": False,
            "error": "La latitud debe estar entre -90 y 90."
        }), 400

    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        return jsonify({
            "success": False,
            "error": "La longitud debe estar entre -180 y 180."
        }), 400

    if (
        start_year < ClimateAnomalyService.REFERENCE_START_YEAR
        or start_year > end_year
        or end_year > latest_complete_year
    ):
        return jsonify({
            "success": False,
            "error": (
                "El período debe estar entre 1991 y "
                f"{latest_complete_year}, con inicio anterior al final."
            )
        }), 400

    profile_end_year = max(
        ClimateAnomalyService.REFERENCE_END_YEAR,
        end_year
    )

    try:
        cached_profile, was_cached, rate_limit_response = (
            _get_or_fetch_atlas_region_profile(
                latitude,
                longitude,
                profile_end_year
            )
        )
        if rate_limit_response:
            return rate_limit_response

        profile = cached_profile["profile"]
        analysis = ClimateAnomalyService.summarize_regional_profile(
            profile,
            start_year,
            end_year
        )
    except WeatherRateLimitError as error:
        return _record_atlas_rate_limit(error)
    except (RuntimeError, ValueError) as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 502
    except Exception as error:
        print("ERROR AL CALCULAR EL PERFIL CLIMÁTICO REGIONAL:", error)
        return jsonify({
            "success": False,
            "error": "No se pudo procesar el perfil climático regional."
        }), 500

    return jsonify({
        "success": True,
        "profile": analysis,
        "dataset_updated_at": cached_profile["dataset_updated_at"],
        "cached": was_cached
    })


def _parse_territory_date(value):
    if not isinstance(value, str):
        raise ValueError("La fecha satelital no es válida.")

    try:
        parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("La fecha satelital no es válida.") from error

    if (
        parsed_date.isoformat() != value
        or parsed_date < date(2002, 7, 3)
        or parsed_date >= date.today()
    ):
        raise ValueError(
            "Elegí una fecha disponible de NASA MODIS Aqua "
            "entre 2002-07-03 y ayer."
        )

    return parsed_date.isoformat()


def _validate_territory_selection(selection):
    if not isinstance(selection, dict):
        raise ValueError("Seleccioná un punto o un área en el mapa.")

    selection_type = selection.get("type")
    name = selection.get("name", "")
    if not isinstance(name, str) or len(name) > 160:
        raise ValueError("El nombre de la selección no es válido.")

    if selection_type == "point":
        try:
            latitude = float(selection.get("latitude"))
            longitude = float(selection.get("longitude"))
        except (TypeError, ValueError) as error:
            raise ValueError("Las coordenadas no son válidas.") from error

        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            raise ValueError("Las coordenadas no son válidas.")

        return {
            "type": "point",
            "name": name or "Punto seleccionado",
            "latitude": round(latitude, 4),
            "longitude": round(longitude, 4)
        }

    if selection_type == "area":
        try:
            south = float(selection.get("south"))
            north = float(selection.get("north"))
            west = float(selection.get("west"))
            east = float(selection.get("east"))
        except (TypeError, ValueError) as error:
            raise ValueError("Los límites del área no son válidos.") from error

        if (
            not all(math.isfinite(value) for value in (south, north, west, east))
            or not -90 <= south < north <= 90
            or not -180 <= west < east <= 180
        ):
            raise ValueError("Los límites del área no son válidos.")

        latitude = (south + north) / 2
        longitude = (west + east) / 2
        return {
            "type": "area",
            "name": name or "Área seleccionada",
            "south": round(south, 4),
            "north": round(north, 4),
            "west": round(west, 4),
            "east": round(east, 4),
            "center_latitude": round(latitude, 4),
            "center_longitude": round(longitude, 4)
        }

    raise ValueError("Seleccioná un punto o un área en el mapa.")


@api_bp.route("/territory/research", methods=["POST"])
@login_required
def research_territory():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "success": False,
            "error": "La consulta de investigación no es válida."
        }), 400

    question = payload.get("question")
    if (
        not isinstance(question, str)
        or not question.strip()
        or len(question.strip()) > 1200
    ):
        return jsonify({
            "success": False,
            "error": "Escribí una pregunta de hasta 1200 caracteres."
        }), 400

    compare_active = payload.get("compare_active", False)
    if not isinstance(compare_active, bool):
        return jsonify({
            "success": False,
            "error": "El estado de comparación no es válido."
        }), 400

    try:
        selection = _validate_territory_selection(payload.get("selection"))
        selected_dates = [
            _parse_territory_date(payload.get("date"))
        ]
        if compare_active:
            comparison_date = _parse_territory_date(
                payload.get("comparison_date")
            )
            if comparison_date == selected_dates[0]:
                raise ValueError(
                    "Elegí dos fechas distintas para compararlas."
                )
            selected_dates.append(comparison_date)
    except ValueError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    history = payload.get("conversation_history", [])
    if not isinstance(history, list) or len(history) > 6 or len(history) % 2:
        return jsonify({
            "success": False,
            "error": "La conversación es demasiado extensa para continuar."
        }), 400

    validated_history = []
    for index, message in enumerate(history):
        expected_role = "user" if index % 2 == 0 else "assistant"
        maximum_length = 1200 if expected_role == "user" else 6000
        if (
            not isinstance(message, dict)
            or message.get("role") != expected_role
            or not isinstance(message.get("content"), str)
            or len(message["content"]) > maximum_length
        ):
            return jsonify({
                "success": False,
                "error": "El historial de la conversación no es válido."
            }), 400
        validated_history.append({
            "role": expected_role,
            "content": message["content"]
        })

    if not AIProviderService.is_configured():
        return jsonify({
            "success": False,
            "error": (
                "Configurá GROQ_API_KEY y GROQ_MODEL para consultar a la IA."
            )
        }), 503

    latitude = selection.get(
        "latitude",
        selection.get("center_latitude")
    )
    longitude = selection.get(
        "longitude",
        selection.get("center_longitude")
    )
    latest_complete_year = date.today().year - 1
    profile_end_year = max(
        ClimateAnomalyService.REFERENCE_END_YEAR,
        latest_complete_year
    )

    try:
        try:
            cached_profile, _, rate_limit_response = (
                _get_or_fetch_atlas_region_profile(
                    latitude,
                    longitude,
                    profile_end_year
                )
            )
            if rate_limit_response:
                climate_profile = (
                    _find_stored_climate_profile(latitude, longitude)
                    or _unavailable_climate_profile()
                )
            else:
                climate_profile = (
                    ClimateAnomalyService.summarize_regional_profile(
                        cached_profile["profile"],
                        ClimateAnomalyService.REFERENCE_START_YEAR,
                        latest_complete_year
                    )
                )
                climate_profile.update({
                    "availability": "available",
                    "profile_type": "annual_series",
                    "source": (
                        "Open-Meteo Historical Weather API · reanalysis"
                    ),
                    "reference_period": "1991-2020"
                })
        except WeatherRateLimitError as error:
            _record_atlas_rate_limit(error)
            climate_profile = (
                _find_stored_climate_profile(latitude, longitude)
                or _unavailable_climate_profile()
            )

        satellite_images = TerritoryResearchService.fetch_satellite_tiles(
            latitude,
            longitude,
            selected_dates
        )
        answer = AIService.generate_territory_research_answer(
            question=question.strip(),
            selection=selection,
            climate_profile=climate_profile,
            satellite_images=satellite_images,
            conversation_history=validated_history
        )
    except WeatherRateLimitError as error:
        return _record_atlas_rate_limit(error)
    except RuntimeError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 502
    except Exception as error:
        print("ERROR EN LA INVESTIGACIÓN TERRITORIAL:", error)
        return jsonify({
            "success": False,
            "error": "No se pudo procesar la consulta territorial."
        }), 500

    climate_available = (
        climate_profile.get("availability") == "available"
    )
    climate_profile_type = climate_profile.get("profile_type")
    if climate_profile_type == "annual_series":
        climate_period = {
            "start_year": ClimateAnomalyService.REFERENCE_START_YEAR,
            "end_year": latest_complete_year
        }
    elif climate_profile_type == "monthly_normal":
        climate_period = {
            "start_year": ClimateAnomalyService.REFERENCE_START_YEAR,
            "end_year": ClimateAnomalyService.REFERENCE_END_YEAR
        }
    else:
        climate_period = None

    sources = ["NASA GIBS · MODIS Aqua Corrected Reflectance"]
    if climate_available:
        sources.append(climate_profile["source"])

    return jsonify({
        "success": True,
        "answer": answer,
        "sources": sources,
        "climate_available": climate_available,
        "climate_profile_type": climate_profile_type,
        "climate_period": climate_period
    })


@api_bp.route("/territory/analytics", methods=["POST"])
@login_required
def analyze_territory_surface():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "success": False,
            "error": "La solicitud de análisis no es válida."
        }), 400

    try:
        selection = _validate_territory_selection(
            payload.get("selection")
        )
        primary_date = _parse_territory_date(payload.get("date"))
        compare_active = payload.get("compare_active", False)
        if not isinstance(compare_active, bool):
            raise ValueError(
                "El estado de comparación no es válido."
            )
        comparison_date = None
        if compare_active:
            comparison_date = _parse_territory_date(
                payload.get("comparison_date")
            )
            if comparison_date == primary_date:
                raise ValueError(
                    "Elegí dos fechas distintas para comparar."
                )

        analysis = TerritoryAnalyticsService.analyze(
            selection=selection,
            primary_date=primary_date,
            comparison_date=comparison_date
        )
    except ValueError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 400
    except TerritoryAnalyticsError as error:
        current_app.logger.warning(
            "No se pudo completar el análisis satelital territorial: %s",
            error
        )
        return jsonify({
            "success": False,
            "error": str(error)
        }), 502
    except Exception:
        current_app.logger.exception(
            "Falló el análisis satelital territorial."
        )
        return jsonify({
            "success": False,
            "error": (
                "No se pudo procesar el análisis satelital. "
                "Intentá nuevamente."
            )
        }), 500

    return jsonify({
        "success": True,
        "analysis": analysis
    })


# --------------------------------------------------
# 5. BUSCAR LOCALIDADES CON CLIMAS SIMILARES
# --------------------------------------------------

@api_bp.route(
    "/climates/similar/<int:geoname_id>",
    methods=["GET"]
)
@login_required
def get_similar_climates(geoname_id):

    try:
        limit = request.args.get("limit", 10, type=int)

        if limit is None or not 1 <= limit <= 30:
            return jsonify({
                "success": False,
                "error": "El límite debe estar entre 1 y 30."
            }), 400

        result = SimilarityService.find_similar_locations(
            geoname_id=geoname_id,
            limit=limit
        )

        return jsonify({
            "success": True,
            **result
        })

    except ValueError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 404

    except (RuntimeError, requests.RequestException) as error:
        print("ERROR AL BUSCAR CLIMAS SIMILARES:", error)

        return jsonify({
            "success": False,
            "error": "No se pudieron obtener los datos climáticos."
        }), 502

    except Exception as error:
        db.session.rollback()

        print("ERROR EN CLIMAS SIMILARES:", error)

        return jsonify({
            "success": False,
            "error": "Ocurrió un error al buscar climas similares."
        }), 500
