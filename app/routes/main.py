
from datetime import date

from flask import Blueprint, current_app, render_template, request
from flask_login import login_required, current_user

from app.extensions import db
from app.services.weather_service import WeatherService
from app.services.global_climate_service import GlobalClimateService
from app.services.location_service import LocationService
from app.services.similarity_service import SimilarityService
from app.services.ai_service import AIService
from app.services.climate_anomaly_service import ClimateAnomalyService


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    return render_template("index.html")


@main_bp.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():

    # ==========================================
    # 1. INFORMACIÓN METEOROLÓGICA DE ARROYITO
    # ==========================================

    weather_data = None
    weather_error = None
    location = None

    try:
        catalog_locations = LocationService.search_locations(
            "Arroyito, Argentina",
            limit=1
        )
        if catalog_locations:
            location = catalog_locations[0]
            weather_data = WeatherService.get_weather(
                latitude=location["latitude"],
                longitude=location["longitude"],
                timezone=location.get("timezone") or "auto"
            )
        else:
            result = WeatherService.get_weather_by_city("Arroyito")
            weather_data = result["weather"]
            location = result["location"]

    except Exception as error:
        weather_error = str(error)

    # ==========================================
    # 2. INFORMACIÓN CLIMÁTICA GLOBAL HISTÓRICA
    # ==========================================

    global_data = None
    global_error = None

    try:
        global_data = GlobalClimateService.get_global_summary()

    except Exception as error:
        global_error = str(error)

    # ==========================================
    # 3. CONDICIONES METEOROLÓGICAS DEL MUNDO
    # ==========================================

    global_conditions = None
    conditions_error = None
    observatory_report = None
    observatory_ai_error = None
    selected_region_index = 0

    try:
        global_conditions = GlobalClimateService.get_global_conditions()

    except Exception as error:
        conditions_error = str(error)

    if global_conditions and weather_data:
        try:
            argentina_locations = LocationService.search_locations(
                "Arroyito, Argentina",
                limit=1
            )

            if argentina_locations:
                argentina_location = argentina_locations[0]
                current = weather_data.get("current", {})
                global_conditions["regions"].append({
                    "region": "Argentina",
                    "city": argentina_location["name"],
                    "country": argentina_location["country_name"],
                    "latitude": argentina_location["latitude"],
                    "longitude": argentina_location["longitude"],
                    "geoname_id": argentina_location["geoname_id"],
                    "temperature": current.get("temperature"),
                    "humidity": current.get("humidity"),
                    "feels_like": current.get("feels_like"),
                    "precipitation": current.get("precipitation"),
                    "precipitation_today": current.get(
                        "precipitation_today"
                    ),
                    "wind_speed": current.get("wind_speed"),
                    "time": current.get("time")
                })
        except Exception as error:
            print(
                "ERROR AL CARGAR LA LOCALIDAD ARGENTINA "
                "DEL OBSERVATORIO:",
                error
            )

    if request.method == "POST":
        if request.form.get("action") != "generate_observatory_insight":
            observatory_ai_error = (
                "La operación solicitada para el observatorio no es válida."
            )
        elif not global_conditions:
            observatory_ai_error = (
                "No se pudieron cargar las condiciones del lugar seleccionado."
            )
        else:
            try:
                selected_geoname_id = request.form.get(
                    "observatory_location_geoname_id",
                    ""
                ).strip()

                if selected_geoname_id:
                    try:
                        selected_geoname_id = int(selected_geoname_id)
                    except (TypeError, ValueError):
                        raise ValueError(
                            "La localidad seleccionada no es válida."
                        )

                    already_loaded = any(
                        str(region.get("geoname_id"))
                        == str(selected_geoname_id)
                        for region in global_conditions["regions"]
                    )

                    if not already_loaded:
                        selected_location = (
                            LocationService.get_by_geoname_id(
                                selected_geoname_id
                            )
                        )

                        if selected_location is None:
                            raise ValueError(
                                "La localidad seleccionada ya no está "
                                "disponible en el catálogo."
                            )

                        selected_weather = WeatherService.get_weather(
                            latitude=selected_location["latitude"],
                            longitude=selected_location["longitude"],
                            timezone=(
                                selected_location.get("timezone")
                                or "auto"
                            )
                        )
                        current = selected_weather["current"]
                        global_conditions["regions"].append({
                            "region": (
                                selected_location.get("admin_region")
                                or selected_location["country_name"]
                            ),
                            "city": selected_location["name"],
                            "country": selected_location["country_name"],
                            "latitude": selected_location["latitude"],
                            "longitude": selected_location["longitude"],
                            "geoname_id": selected_geoname_id,
                            "temperature": current.get("temperature"),
                            "humidity": current.get("humidity"),
                            "feels_like": current.get("feels_like"),
                            "precipitation": current.get("precipitation"),
                            "precipitation_today": current.get(
                                "precipitation_today"
                            ),
                            "wind_speed": current.get("wind_speed"),
                            "time": current.get("time")
                        })
                        selected_region = global_conditions["regions"][-1]
                    else:
                        selected_region = next(
                            region
                            for region in global_conditions["regions"]
                            if str(region.get("geoname_id"))
                            == str(selected_geoname_id)
                        )
                else:
                    region_index = request.form.get(
                        "observatory_location_index",
                        ""
                    ).strip()
                    try:
                        region_index = int(region_index)
                    except (TypeError, ValueError):
                        raise ValueError(
                            "Elegí una localidad antes de pedir la interpretación."
                        )
                    if not 0 <= region_index < len(
                        global_conditions["regions"]
                    ):
                        raise ValueError(
                            "La localidad seleccionada ya no está disponible."
                        )
                    selected_region = global_conditions["regions"][
                        region_index
                    ]

                selected_region_index = global_conditions["regions"].index(
                    selected_region
                )
                local_climate = {
                    "disponibilidad": "no_disponible",
                    "detalle": (
                        "No se pudo consultar la serie histórica local; "
                        "solo se interpretarán las condiciones meteorológicas "
                        "actuales, sin afirmar tendencias."
                    )
                }
                try:
                    latest_complete_year = date.today().year - 1
                    regional_profile = (
                        ClimateAnomalyService.fetch_regional_annual_profile(
                            latitude=selected_region["latitude"],
                            longitude=selected_region["longitude"],
                            end_year=latest_complete_year
                        )
                    )
                    regional_analysis = (
                        ClimateAnomalyService.summarize_regional_profile(
                            regional_profile,
                            ClimateAnomalyService.REFERENCE_START_YEAR,
                            latest_complete_year
                        )
                    )
                    local_climate = {
                        "disponibilidad": "disponible",
                        "fuente": regional_analysis["source"],
                        "periodo": regional_analysis["period"],
                        "referencia": regional_analysis["reference"],
                        "tendencias_por_decada": regional_analysis["trends"],
                        "comparacion_por_decada": regional_analysis["decades"],
                        "anios_con_datos": len(regional_analysis["annual"])
                    }
                except (RuntimeError, ValueError) as error:
                    current_app.logger.warning(
                        "No se pudo cargar el perfil histórico de %s: %s",
                        selected_region.get("city"),
                        error
                    )
                    local_climate["detalle"] = str(error)

                observatory_report = AIService.generate_observatory_insight(
                    selected_region,
                    local_climate
                )
            except (RuntimeError, ValueError) as error:
                observatory_ai_error = str(error)
            except Exception as error:
                print("ERROR EN LA INTERPRETACIÓN DEL OBSERVATORIO:", error)
                observatory_ai_error = (
                    "No se pudo generar la interpretación del observatorio."
                )

    # ==========================================
    # 4. ENVIAR INFORMACIÓN AL DASHBOARD
    # ==========================================

    return render_template(
        "dashboard.html",
        user=current_user,
        weather_data=weather_data,
        location=location,
        weather_error=weather_error,
        global_data=global_data,
        global_error=global_error,
        global_conditions=global_conditions,
        conditions_error=conditions_error,
        observatory_report=observatory_report,
        observatory_ai_error=observatory_ai_error,
        selected_region_index=selected_region_index
    )


# ==========================================
# ADN CLIMÁTICO
# ==========================================

@main_bp.route("/climate-profile", methods=["GET", "POST"])
@login_required
def climate_profile():

    profile = None
    location = None
    locations = []
    error = None
    searched_city = ""

    if request.method == "POST":

        searched_city = request.form.get(
            "city", ""
        ).strip()

        action = request.form.get("action", "search")

        try:

            if not searched_city:
                raise ValueError(
                    "Ingresá el nombre de una ciudad o localidad."
                )

            # ======================================
            # 1. BUSCAR LOCALIDADES EN SQLITE
            # ======================================

            if action == "search":

                locations = LocationService.search_locations(
                    searched_city,
                    limit=20
                )

                if not locations:
                    raise ValueError(
                        "No se encontraron localidades en el catálogo. "
                        "Probá con otro nombre."
                    )

            # ======================================
            # 2. SELECCIONAR LOCALIDAD POR GEONAMES
            # ======================================

            elif action == "select":

                selected_geoname_id = request.form.get(
                    "selected_geoname_id",
                    ""
                )

                try:
                    selected_geoname_id = int(selected_geoname_id)

                except (TypeError, ValueError):
                    raise ValueError(
                        "El identificador de la localidad no es válido."
                    )

                # Recuperamos directamente la localidad
                # desde la base de datos.

                location = LocationService.get_by_geoname_id(
                    selected_geoname_id
                )

                if location is None:
                    raise ValueError(
                        "La localidad seleccionada no existe "
                        "en el catálogo. Volvé a buscarla."
                    )

                # ==================================
                # 3. GENERAR PERFIL CLIMÁTICO REAL
                # ==================================

                profile = WeatherService.get_climate_profile(
                    latitude=location["latitude"],
                    longitude=location["longitude"],
                    timezone=location.get("timezone") or "auto"
                )

            else:
                raise ValueError(
                    "La operación solicitada no es válida."
                )

        except Exception as exception:
            error = str(exception)

    # ==========================================
    # 4. MOSTRAR RESULTADOS
    # ==========================================

    return render_template(
        "climate_profile.html",
        user=current_user,
        profile=profile,
        location=location,
        locations=locations,
        error=error,
        searched_city=searched_city
    )


@main_bp.route("/climate-connections", methods=["GET", "POST"])
@login_required
def climate_connections():
    locations = []
    searched_city = ""
    selected_location = None
    similarity_result = None
    ai_report = None
    error = None
    ai_error = None

    if request.method == "POST":
        action = request.form.get("action", "search")

        if action == "search":
            searched_city = request.form.get("city", "").strip()

            try:
                if not searched_city:
                    raise ValueError(
                        "Ingresá el nombre de una ciudad o localidad."
                    )

                locations = LocationService.search_locations(
                    searched_city,
                    limit=20
                )

                if not locations:
                    raise ValueError(
                        "No se encontraron localidades en el catálogo. "
                        "Probá con otro nombre."
                    )

            except ValueError as exception:
                error = str(exception)
            except Exception as exception:
                db.session.rollback()
                print("ERROR AL BUSCAR LOCALIDADES PARA CONEXIONES:", exception)
                error = "No se pudieron buscar las localidades."

        elif action == "find_similar":
            try:
                try:
                    selected_geoname_id = int(
                        request.form.get("selected_geoname_id", "")
                    )
                except (TypeError, ValueError):
                    raise ValueError(
                        "El identificador de la localidad no es válido."
                    )

                selected_location = LocationService.get_by_geoname_id(
                    selected_geoname_id
                )

                if selected_location is None:
                    raise ValueError(
                        "La localidad seleccionada no existe "
                        "en el catálogo. Volvé a buscarla."
                    )

                searched_city = selected_location["name"]
                similarity_result = (
                    SimilarityService.find_similar_locations(
                        geoname_id=selected_geoname_id,
                        limit=10
                    )
                )

                if similarity_result["results"]:
                    try:
                        ai_report = AIService.generate_similarity_report(
                            similarity_result
                        )
                    except RuntimeError as exception:
                        ai_error = str(exception)
                    except Exception:
                        ai_error = (
                            "No se pudo generar la interpretación "
                            "de inteligencia artificial."
                        )

            except (TypeError, ValueError) as exception:
                error = str(exception) or (
                    "El identificador de la localidad no es válido."
                )
            except RuntimeError as exception:
                db.session.rollback()
                error = str(exception)
            except Exception as exception:
                db.session.rollback()
                print(
                    "ERROR EN CONEXIONES CLIMÁTICAS:",
                    exception
                )
                error = (
                    "No se pudieron calcular las localidades similares. "
                    "Intentá nuevamente."
                )

        else:
            error = "La operación solicitada no es válida."

    return render_template(
        "climate_connections.html",
        user=current_user,
        locations=locations,
        searched_city=searched_city,
        selected_location=selected_location,
        similarity_result=similarity_result,
        ai_report=ai_report,
        error=error,
        ai_error=ai_error
    )
