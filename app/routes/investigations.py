
from pathlib import Path
from datetime import date
from uuid import uuid4
from math import sqrt

from flask import (
    Blueprint,
    render_template,
    request,
    flash,
    redirect,
    url_for
)

from flask_login import login_required

from app.services.image_analysis_service import ImageAnalysisService
from app.services.weather_service import WeatherService
from app.services.ai_service import AIService
from app.services.location_service import LocationService


investigations_bp = Blueprint(
    "investigations",
    __name__
)

UPLOAD_FOLDER = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "uploads"
)

ALLOWED_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "webp"
}

MAX_FILE_SIZE = 10 * 1024 * 1024


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


def save_uploaded_image(uploaded_file):
    """Valida y guarda una imagen con un nombre único."""

    if not uploaded_file or not uploaded_file.filename:
        raise ValueError("Falta seleccionar una imagen.")

    if not allowed_file(uploaded_file.filename):
        raise ValueError(
            "Formato no válido. Utilizá JPG, PNG o WEBP."
        )

    uploaded_file.seek(0, 2)
    file_size = uploaded_file.tell()
    uploaded_file.seek(0)

    if file_size == 0:
        raise ValueError("El archivo seleccionado está vacío.")

    if file_size > MAX_FILE_SIZE:
        raise ValueError(
            "La imagen supera el límite de 10 MB."
        )

    extension = uploaded_file.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid4().hex}.{extension}"

    image_path = UPLOAD_FOLDER / filename
    uploaded_file.save(image_path)

    return image_path, filename


def parse_and_validate_dates(first_value, second_value):
    """Valida dos fechas diferentes y evita fechas futuras."""

    if not first_value or not second_value:
        raise ValueError(
            "Seleccioná las dos fechas para realizar la comparación."
        )

    try:
        first = date.fromisoformat(first_value)
        second = date.fromisoformat(second_value)

    except ValueError:
        raise ValueError(
            "Una de las fechas ingresadas no es válida."
        )

    if first > date.today() or second > date.today():
        raise ValueError(
            "No se pueden consultar fechas futuras."
        )

    if first == second:
        raise ValueError(
            "Seleccioná dos fechas diferentes para compararlas."
        )

    return first.isoformat(), second.isoformat()


def parse_climate_period(start_value, end_value):
    """Valida el período histórico elegido para comparar localidades."""

    if not start_value or not end_value:
        raise ValueError(
            "Seleccioná la fecha inicial y la fecha final del período."
        )

    try:
        start = date.fromisoformat(start_value)
        end = date.fromisoformat(end_value)

    except ValueError:
        raise ValueError(
            "El período seleccionado contiene una fecha inválida."
        )

    if start > end:
        raise ValueError(
            "La fecha inicial no puede ser posterior a la fecha final."
        )

    if end > date.today():
        raise ValueError(
            "La fecha final no puede estar en el futuro."
        )

    if start.year < 1940:
        raise ValueError(
            "El período debe comenzar en 1940 o en un año posterior."
        )

    if (end - start).days < 364:
        raise ValueError(
            "Elegí un período de al menos un año para comparar los climas."
        )

    return start.isoformat(), end.isoformat()


def get_weather_comparison(first_date, second_date):
    """Consulta los registros históricos de Arroyito y calcula diferencias."""

    locations = WeatherService.search_location("Arroyito")

    if not locations:
        raise RuntimeError(
            "No se pudo encontrar la ubicación de Arroyito."
        )

    location = locations[0]

    latitude = location["latitude"]
    longitude = location["longitude"]
    timezone = location.get("timezone") or "auto"

    first_weather = WeatherService.get_historical_weather(
        latitude=latitude,
        longitude=longitude,
        date=first_date,
        timezone=timezone
    )

    second_weather = WeatherService.get_historical_weather(
        latitude=latitude,
        longitude=longitude,
        date=second_date,
        timezone=timezone
    )

    weather_comparison = {
        "temperature_difference": round(
            second_weather["temperature_mean"]
            - first_weather["temperature_mean"],
            2
        ),
        "temperature_max_difference": round(
            second_weather["temperature_max"]
            - first_weather["temperature_max"],
            2
        ),
        "temperature_min_difference": round(
            second_weather["temperature_min"]
            - first_weather["temperature_min"],
            2
        ),
        "precipitation_difference": round(
            second_weather["precipitation"]
            - first_weather["precipitation"],
            2
        ),
        "wind_difference": round(
            second_weather["wind_speed_max"]
            - first_weather["wind_speed_max"],
            2
        )
    }

    return first_weather, second_weather, weather_comparison


def get_location_candidates(search_text):
    """Busca localidades en el catálogo mundial de ClimaIA."""

    if not search_text or not search_text.strip():
        return []

    return LocationService.search_locations(
        search_text.strip(),
        limit=20
    )


def get_climate_location(geoname_id):
    """Recupera una localidad seleccionada mediante su identificador GeoNames."""

    try:
        geoname_id = int(geoname_id)
    except (TypeError, ValueError):
        raise ValueError(
            "Seleccioná una localidad válida en cada campo."
        )

    location = LocationService.get_by_geoname_id(geoname_id)

    if location is None:
        raise ValueError(
            "Una de las localidades seleccionadas ya no está disponible."
        )

    return location


def calculate_climate_comparison(first_profile, second_profile):
    """
    Compara los perfiles mensuales de dos localidades.

    Las diferencias se calculan como:
    segundo lugar menos primer lugar.
    """

    first_months = first_profile.get("monthly_profile", [])
    second_months = second_profile.get("monthly_profile", [])

    if len(first_months) != 12 or len(second_months) != 12:
        raise ValueError(
            "No hay suficientes datos mensuales para comparar "
            "los perfiles climáticos."
        )

    monthly_differences = []

    temperature_squared_errors = []
    precipitation_squared_errors = []

    temperature_absolute_errors = []
    precipitation_absolute_errors = []

    for first_month, second_month in zip(
        first_months,
        second_months
    ):
        first_temperature = first_month.get("temperature_mean")
        second_temperature = second_month.get("temperature_mean")

        first_precipitation = first_month.get("precipitation_mean_daily")
        second_precipitation = second_month.get("precipitation_mean_daily")

        if (
            first_temperature is None
            or second_temperature is None
            or first_precipitation is None
            or second_precipitation is None
        ):
            raise ValueError(
                "Uno de los perfiles contiene meses sin datos suficientes."
            )

        temperature_difference = (
            second_temperature - first_temperature
        )

        precipitation_difference = (
            second_precipitation - first_precipitation
        )

        temperature_squared_errors.append(
            temperature_difference ** 2
        )

        precipitation_squared_errors.append(
            precipitation_difference ** 2
        )

        temperature_absolute_errors.append(
            abs(temperature_difference)
        )

        precipitation_absolute_errors.append(
            abs(precipitation_difference)
        )

        monthly_differences.append({
            "month": first_month.get("month"),
            "name": first_month.get("name"),
            "first_temperature": round(first_temperature, 2),
            "second_temperature": round(second_temperature, 2),
            "temperature_difference": round(
                temperature_difference,
                2
            ),
            "first_precipitation": round(first_precipitation, 2),
            "second_precipitation": round(second_precipitation, 2),
            "precipitation_difference": round(
                precipitation_difference,
                2
            )
        })

    temperature_rmse = sqrt(
        sum(temperature_squared_errors)
        / len(temperature_squared_errors)
    )

    precipitation_rmse = sqrt(
        sum(precipitation_squared_errors)
        / len(precipitation_squared_errors)
    )

    temperature_mae = (
        sum(temperature_absolute_errors)
        / len(temperature_absolute_errors)
    )

    precipitation_mae = (
        sum(precipitation_absolute_errors)
        / len(precipitation_absolute_errors)
    )

    first_statistics = first_profile.get("general_statistics", {})
    second_statistics = second_profile.get("general_statistics", {})

    first_mean_temperature = first_statistics.get("temperature_mean")
    second_mean_temperature = second_statistics.get("temperature_mean")

    first_total_precipitation = first_statistics.get("precipitation_total")
    second_total_precipitation = second_statistics.get("precipitation_total")

    return {
        "monthly_differences": monthly_differences,
        "temperature_rmse": round(temperature_rmse, 2),
        "precipitation_rmse": round(precipitation_rmse, 2),
        "temperature_mae": round(temperature_mae, 2),
        "precipitation_mae": round(precipitation_mae, 2),
        "first_mean_temperature": first_mean_temperature,
        "second_mean_temperature": second_mean_temperature,
        "mean_temperature_difference": (
            round(
                second_mean_temperature - first_mean_temperature,
                2
            )
            if first_mean_temperature is not None
            and second_mean_temperature is not None
            else None
        ),
        "first_total_precipitation": first_total_precipitation,
        "second_total_precipitation": second_total_precipitation,
        "total_precipitation_difference": (
            round(
                second_total_precipitation - first_total_precipitation,
                2
            )
            if first_total_precipitation is not None
            and second_total_precipitation is not None
            else None
        )
    }


@investigations_bp.route(
    "/investigations",
    methods=["GET", "POST"]
)
@login_required
def index():

    # Resultados del análisis de una imagen
    analysis = None
    image_url = None
    single_image_ai_report = None
    single_image_ai_error = None

    # Resultados de la comparación visual
    comparison = None
    first_image_url = None
    second_image_url = None

    # Resultados meteorológicos
    first_weather = None
    second_weather = None
    weather_comparison = None
    weather_error = None

    # Informes de inteligencia artificial
    ai_report = None
    ai_error = None

    # Fechas de las comparaciones existentes
    first_date = None
    second_date = None

    # Comparación entre localidades
    first_location = None
    second_location = None
    first_profile = None
    second_profile = None
    climate_comparison = None

    first_location_candidates = []
    second_location_candidates = []

    first_city_search = ""
    second_city_search = ""

    climate_start_date = request.form.get(
        "climate_start_date",
        "1991-01-01"
    )

    climate_end_date = request.form.get(
        "climate_end_date",
        "2020-12-31"
    )

    # Identifica qué modalidad se procesó
    analysis_mode = None

    if request.method == "POST":

        action = request.form.get("action", "analyze")
        saved_paths = []

        try:

            # ==================================================
            # 1. ANÁLISIS DE UNA SOLA IMAGEN
            # ==================================================

            if action == "analyze":

                analysis_mode = "single"

                UPLOAD_FOLDER.mkdir(
                    parents=True,
                    exist_ok=True
                )

                uploaded_file = request.files.get("image")

                image_path, filename = save_uploaded_image(
                    uploaded_file
                )

                saved_paths.append(image_path)

                analysis = ImageAnalysisService.analyze_image(
                    image_path
                )

                image_url = url_for(
                    "static",
                    filename=f"uploads/{filename}"
                )

                try:
                    single_image_ai_report = (
                        AIService.generate_single_image_report(
                            visual_analysis=analysis
                        )
                    )

                except RuntimeError as error:
                    single_image_ai_error = str(error)

                except Exception:
                    single_image_ai_error = (
                        "No se pudo generar la interpretación "
                        "de inteligencia artificial."
                    )

            # ==================================================
            # 2. COMPARACIÓN DE DOS IMÁGENES
            # ==================================================

            elif action == "compare":

                analysis_mode = "visual_comparison"

                UPLOAD_FOLDER.mkdir(
                    parents=True,
                    exist_ok=True
                )

                first_date, second_date = parse_and_validate_dates(
                    request.form.get("first_date"),
                    request.form.get("second_date")
                )

                first_file = request.files.get("first_image")
                second_file = request.files.get("second_image")

                first_path, first_filename = save_uploaded_image(
                    first_file
                )

                saved_paths.append(first_path)

                second_path, second_filename = save_uploaded_image(
                    second_file
                )

                saved_paths.append(second_path)

                comparison = ImageAnalysisService.compare_images(
                    first_path,
                    second_path
                )

                first_image_url = url_for(
                    "static",
                    filename=f"uploads/{first_filename}"
                )

                second_image_url = url_for(
                    "static",
                    filename=f"uploads/{second_filename}"
                )

                try:
                    (
                        first_weather,
                        second_weather,
                        weather_comparison
                    ) = get_weather_comparison(
                        first_date,
                        second_date
                    )

                except (
                    RuntimeError,
                    ValueError,
                    KeyError,
                    TypeError,
                    IndexError
                ):
                    weather_error = (
                        "No se pudieron obtener los registros "
                        "meteorológicos de una o ambas fechas. "
                        "La comparación visual sí se realizó."
                    )

                try:
                    ai_report = AIService.generate_climate_report(
                        visual_comparison=comparison,
                        first_weather=first_weather,
                        second_weather=second_weather,
                        weather_comparison=weather_comparison
                    )

                except RuntimeError as error:
                    ai_error = str(error)

                except Exception:
                    ai_error = (
                        "No se pudo generar el informe de inteligencia "
                        "artificial. La comparación visual se realizó."
                    )

            # ==================================================
            # 3. COMPARACIÓN DE DOS FECHAS DE ARROYITO
            # ==================================================

            elif action == "compare_dates":

                analysis_mode = "weather_comparison"

                first_date, second_date = parse_and_validate_dates(
                    request.form.get("first_date"),
                    request.form.get("second_date")
                )

                (
                    first_weather,
                    second_weather,
                    weather_comparison
                ) = get_weather_comparison(
                    first_date,
                    second_date
                )

                try:
                    ai_report = (
                        AIService.generate_weather_comparison_report(
                            first_weather=first_weather,
                            second_weather=second_weather,
                            weather_comparison=weather_comparison
                        )
                    )

                except RuntimeError as error:
                    ai_error = str(error)

                except Exception:
                    ai_error = (
                        "No se pudo generar el informe meteorológico "
                        "de inteligencia artificial."
                    )

            # ==================================================
            # 4. BUSCAR LOCALIDADES PARA COMPARAR
            # ==================================================

            elif action == "search_places":

                analysis_mode = "place_search"

                first_city_search = request.form.get(
                    "first_city",
                    ""
                ).strip()

                second_city_search = request.form.get(
                    "second_city",
                    ""
                ).strip()

                if not first_city_search and not second_city_search:
                    raise ValueError(
                        "Ingresá al menos una localidad para buscar."
                    )

                if first_city_search:
                    first_location_candidates = (
                        get_location_candidates(first_city_search)
                    )

                if second_city_search:
                    second_location_candidates = (
                        get_location_candidates(second_city_search)
                    )

                if first_city_search and not first_location_candidates:
                    flash(
                        "No se encontraron resultados para la primera localidad.",
                        "warning"
                    )

                if second_city_search and not second_location_candidates:
                    flash(
                        "No se encontraron resultados para la segunda localidad.",
                        "warning"
                    )

            # ==================================================
            # 5. COMPARACIÓN CLIMÁTICA ENTRE DOS LOCALIDADES
            # ==================================================

            elif action == "compare_places":

                analysis_mode = "place_comparison"

                first_city_search = request.form.get(
                    "first_city",
                    ""
                ).strip()

                second_city_search = request.form.get(
                    "second_city",
                    ""
                ).strip()

                climate_start_date, climate_end_date = (
                    parse_climate_period(
                        request.form.get("climate_start_date"),
                        request.form.get("climate_end_date")
                    )
                )

                first_location = get_climate_location(
                    request.form.get("first_geoname_id")
                )

                second_location = get_climate_location(
                    request.form.get("second_geoname_id")
                )

                if (
                    first_location["geoname_id"]
                    == second_location["geoname_id"]
                ):
                    raise ValueError(
                        "Seleccioná dos localidades diferentes."
                    )

                first_profile = WeatherService.get_climate_profile(
                    latitude=first_location["latitude"],
                    longitude=first_location["longitude"],
                    start_date=climate_start_date,
                    end_date=climate_end_date,
                    timezone=first_location.get("timezone") or "auto"
                )

                second_profile = WeatherService.get_climate_profile(
                    latitude=second_location["latitude"],
                    longitude=second_location["longitude"],
                    start_date=climate_start_date,
                    end_date=climate_end_date,
                    timezone=second_location.get("timezone") or "auto"
                )

                climate_comparison = calculate_climate_comparison(
                    first_profile,
                    second_profile
                )

            else:
                raise ValueError(
                    "La modalidad de análisis seleccionada no es válida."
                )

        except ValueError as error:

            for path in saved_paths:
                if path.exists():
                    path.unlink()

            flash(str(error), "error")

            if action not in ("search_places",):
                return redirect(url_for("investigations.index"))

        except Exception as error:

            for path in saved_paths:
                if path.exists():
                    path.unlink()

            print(
                "Error en Investigaciones:",
                repr(error)
            )

            flash(
                "No se pudo completar el procesamiento. "
                "Revisá los datos e intentá nuevamente.",
                "error"
            )

    return render_template(
        "investigation.html",

        # Análisis individual
        analysis=analysis,
        image_url=image_url,
        single_image_ai_report=single_image_ai_report,
        single_image_ai_error=single_image_ai_error,

        # Comparación visual
        comparison=comparison,
        first_image_url=first_image_url,
        second_image_url=second_image_url,

        # Fechas
        first_date=first_date,
        second_date=second_date,

        # Meteorología
        first_weather=first_weather,
        second_weather=second_weather,
        weather_comparison=weather_comparison,
        weather_error=weather_error,

        # Informes de IA
        ai_report=ai_report,
        ai_error=ai_error,

        # Comparación de localidades
        first_location=first_location,
        second_location=second_location,
        first_profile=first_profile,
        second_profile=second_profile,
        climate_comparison=climate_comparison,
        first_location_candidates=first_location_candidates,
        second_location_candidates=second_location_candidates,
        first_city_search=first_city_search,
        second_city_search=second_city_search,
        climate_start_date=climate_start_date,
        climate_end_date=climate_end_date,

        # Modalidad procesada
        analysis_mode=analysis_mode,

        # Fecha máxima para los selectores
        today=date.today().isoformat()
    )
