
import requests

from datetime import date


class WeatherRateLimitError(RuntimeError):

    def __init__(self, retry_after=None):
        self.retry_after = retry_after
        super().__init__(
            "Open-Meteo alcanzó el límite de consultas (HTTP 429)."
        )


class WeatherService:
    """
    Servicio de ClimaIA para consultar información meteorológica
    actual, pronósticos y registros climáticos históricos.
    """

    GEOCODING_URL = (
        "https://geocoding-api.open-meteo.com/v1/search"
    )

    FORECAST_URL = (
        "https://api.open-meteo.com/v1/forecast"
    )

    ARCHIVE_URL = (
        "https://archive-api.open-meteo.com/v1/archive"
    )

    CLIMATE_REFERENCE_START = "1991-01-01"
    CLIMATE_REFERENCE_END = "2020-12-31"


    @staticmethod
    def _request_json(url, params, timeout=30):
        """
        Realiza una solicitud HTTP y devuelve los datos JSON.
        Conserva información del error para facilitar el diagnóstico.
        """

        try:
            response = requests.get(
                url,
                params=params,
                timeout=timeout
            )

            response.raise_for_status()

            return response.json()

        except requests.Timeout as error:
            raise RuntimeError(
                "La consulta meteorológica tardó demasiado. "
                "Se agotó el tiempo de espera."
            ) from error

        except requests.HTTPError as error:
            response = error.response

            status = (
                response.status_code
                if response is not None
                else "desconocido"
            )

            details = (
                response.text[:500]
                if response is not None
                else str(error)
            )

            print(
                f"ERROR HTTP OPEN-METEO | "
                f"Estado: {status} | "
                f"Detalle: {details}"
            )

            if status == 429:
                retry_after = None
                if response is not None:
                    try:
                        retry_after = int(
                            response.headers.get("Retry-After", "")
                        )
                    except (TypeError, ValueError):
                        pass
                    if retry_after is None:
                        try:
                            error_data = response.json()
                        except (
                            ValueError,
                            requests.exceptions.RequestException
                        ):
                            error_data = {}

                        if isinstance(error_data, dict):
                            reason = str(
                                error_data.get("reason", "")
                            ).lower()
                            if "hour" in reason:
                                retry_after = 3600
                            elif "day" in reason:
                                retry_after = 86400
                raise WeatherRateLimitError(retry_after) from error

            raise RuntimeError(
                f"Open-Meteo respondió con el estado HTTP {status}."
            ) from error

        except requests.ConnectionError as error:
            print(f"ERROR DE CONEXIÓN OPEN-METEO: {error}")

            raise RuntimeError(
                "No se pudo establecer conexión con Open-Meteo."
            ) from error

        except requests.RequestException as error:
            print(f"ERROR DE SOLICITUD OPEN-METEO: {error}")

            raise RuntimeError(
                "Ocurrió un error al consultar el servicio meteorológico."
            ) from error

        except ValueError as error:
            raise RuntimeError(
                "El servicio meteorológico devolvió una respuesta inválida."
            ) from error


    @staticmethod
    def search_location(city_name):
        """
        Busca una ciudad y devuelve sus coordenadas geográficas.
        """

        if not city_name or not city_name.strip():
            raise ValueError("Ingresá el nombre de una ciudad.")

        params = {
            "name": city_name.strip(),
            "count": 5,
            "language": "es",
            "format": "json"
        }

        data = WeatherService._request_json(
            WeatherService.GEOCODING_URL,
            params,
            timeout=15
        )

        results = []

        for location in data.get("results", []):
            results.append({
                "name": location.get("name"),
                "country": location.get("country"),
                "admin1": location.get("admin1"),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "timezone": location.get("timezone")
            })

        return results

    @staticmethod
    def get_weather(latitude, longitude, timezone="auto"):
        """
        Obtiene condiciones meteorológicas actuales
        y un pronóstico diario de los próximos días.
        """

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": (
                "temperature_2m,"
                "relative_humidity_2m,"
                "apparent_temperature,"
                "precipitation,"
                "weather_code,"
                "wind_speed_10m"
            ),
            "daily": (
                "temperature_2m_max,"
                "temperature_2m_min,"
                "precipitation_sum,"
                "precipitation_probability_max"
            ),
            "forecast_days": 7,
            "timezone": timezone
        }

        data = WeatherService._request_json(
            WeatherService.FORECAST_URL,
            params,
            timeout=20
        )

        current = data.get("current", {})
        daily = data.get("daily", {})

        forecast = []

        dates = daily.get("time", [])
        current_date = (current.get("time") or "")[:10]
        today_index = (
            dates.index(current_date)
            if current_date in dates
            else None
        )
        daily_precipitation = daily.get("precipitation_sum", [])
        precipitation_today = (
            daily_precipitation[today_index]
            if today_index is not None
            and today_index < len(daily_precipitation)
            else None
        )

        for index, forecast_date in enumerate(dates):
            forecast.append({
                "date": forecast_date,
                "temperature_max": daily["temperature_2m_max"][index],
                "temperature_min": daily["temperature_2m_min"][index],
                "precipitation": daily["precipitation_sum"][index],
                "precipitation_probability": (
                    daily["precipitation_probability_max"][index]
                )
            })

        return {
            "current": {
                "time": current.get("time"),
                "temperature": current.get("temperature_2m"),
                "humidity": current.get("relative_humidity_2m"),
                "feels_like": current.get("apparent_temperature"),
                "precipitation": current.get("precipitation"),
                "precipitation_today": precipitation_today,
                "weather_code": current.get("weather_code"),
                "wind_speed": current.get("wind_speed_10m")
            },
            "forecast": forecast,
            "units": {
                "temperature": data.get("current_units", {}).get(
                    "temperature_2m"
                ),
                "humidity": data.get("current_units", {}).get(
                    "relative_humidity_2m"
                ),
                "precipitation": data.get("daily_units", {}).get(
                    "precipitation_sum"
                ),
                "current_precipitation": data.get(
                    "current_units", {}
                ).get("precipitation"),
                "wind_speed": data.get("current_units", {}).get(
                    "wind_speed_10m"
                )
            },
            "timezone": data.get("timezone")
        }

    @staticmethod
    def get_historical_weather(
        latitude,
        longitude,
        date,
        timezone="auto"
    ):
        """
        Obtiene registros meteorológicos históricos
        correspondientes a una fecha determinada.
        """

        historical = WeatherService.get_historical_series(
            latitude=latitude,
            longitude=longitude,
            start_date=date,
            end_date=date,
            timezone=timezone
        )

        if not historical["records"]:
            raise ValueError(
                "No hay registros meteorológicos disponibles "
                "para esa fecha."
            )

        record = historical["records"][0]

        return {
            "date": record["date"],
            "temperature_mean": record["temperature_mean"],
            "temperature_max": record["temperature_max"],
            "temperature_min": record["temperature_min"],
            "precipitation": record["precipitation"],
            "wind_speed_max": record["wind_speed_max"],
            "units": historical["units"]
        }

    @staticmethod
    def get_historical_series(
        latitude,
        longitude,
        start_date,
        end_date,
        timezone="auto"
    ):
        """
        Obtiene una serie de registros meteorológicos diarios
        correspondientes a un período determinado.
        """

        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)

        except (TypeError, ValueError) as error:
            raise ValueError(
                "Las fechas deben tener el formato YYYY-MM-DD."
            ) from error

        if start > end:
            raise ValueError(
                "La fecha inicial no puede ser posterior a la final."
            )

        if end > date.today():
            raise ValueError(
                "No se pueden consultar fechas futuras en el archivo histórico."
            )

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "daily": (
                "temperature_2m_mean,"
                "temperature_2m_max,"
                "temperature_2m_min,"
                "precipitation_sum,"
                "wind_speed_10m_max,"
                "sunshine_duration,"
                "shortwave_radiation_sum"
            ),
            "timezone": timezone
        }

        data = WeatherService._request_json(
            WeatherService.ARCHIVE_URL,
            params,
            timeout=60
        )

        daily = data.get("daily", {})
        dates = daily.get("time", [])

        if not dates:
            raise ValueError(
                "No se encontraron registros históricos para el período."
            )

        records = []

        for index, record_date in enumerate(dates):

            def get_value(field):
                values = daily.get(field, [])

                if index >= len(values):
                    return None

                return values[index]

            records.append({
                "date": record_date,
                "temperature_mean": get_value(
                    "temperature_2m_mean"
                ),
                "temperature_max": get_value(
                    "temperature_2m_max"
                ),
                "temperature_min": get_value(
                    "temperature_2m_min"
                ),
                "precipitation": get_value(
                    "precipitation_sum"
                ),
                "wind_speed_max": get_value(
                    "wind_speed_10m_max"
                ),
                "sunshine_duration": get_value(
                    "sunshine_duration"
                ),
                "solar_radiation": get_value(
                    "shortwave_radiation_sum"
                )
            })

        return {
            "location": {
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "elevation": data.get("elevation")
            },
            "period": {
                "start": start_date,
                "end": end_date
            },
            "records": records,
            "units": data.get("daily_units", {}),
            "timezone": data.get("timezone")
        }

    @staticmethod
    def get_climate_profile(
        latitude,
        longitude,
        start_date=None,
        end_date=None,
        timezone="auto"
    ):
        """
        Construye un perfil climático a partir de registros históricos.

        Calcula promedios mensuales de temperatura, precipitaciones,
        viento, horas de sol y radiación solar.
        """

        start_date = (
            start_date or WeatherService.CLIMATE_REFERENCE_START
        )

        end_date = (
            end_date or WeatherService.CLIMATE_REFERENCE_END
        )

        historical = WeatherService.get_historical_series(
            latitude=latitude,
            longitude=longitude,
            start_date=start_date,
            end_date=end_date,
            timezone=timezone
        )

        records = historical["records"]

        monthly_data = {}

        for month in range(1, 13):
            monthly_data[month] = {
                "temperatures": [],
                "maximum_temperatures": [],
                "minimum_temperatures": [],
                "precipitation": [],
                "wind": [],
                "sunshine": [],
                "radiation": []
            }

        annual_data = {}

        for record in records:

            month = int(record["date"][5:7])
            year = int(record["date"][:4])

            values = monthly_data[month]

            if record["temperature_mean"] is not None:
                values["temperatures"].append(
                    record["temperature_mean"]
                )

            if record["temperature_max"] is not None:
                values["maximum_temperatures"].append(
                    record["temperature_max"]
                )

            if record["temperature_min"] is not None:
                values["minimum_temperatures"].append(
                    record["temperature_min"]
                )

            if record["precipitation"] is not None:
                values["precipitation"].append(
                    record["precipitation"]
                )

            if record["wind_speed_max"] is not None:
                values["wind"].append(
                    record["wind_speed_max"]
                )

            if record["sunshine_duration"] is not None:
                values["sunshine"].append(
                    record["sunshine_duration"]
                )

            if record["solar_radiation"] is not None:
                values["radiation"].append(
                    record["solar_radiation"]
                )

            if year not in annual_data:
                annual_data[year] = {
                    "temperatures": [],
                    "precipitation": []
                }

            if record["temperature_mean"] is not None:
                annual_data[year]["temperatures"].append(
                    record["temperature_mean"]
                )

            if record["precipitation"] is not None:
                annual_data[year]["precipitation"].append(
                    record["precipitation"]
                )

        def average(values):
            if not values:
                return None

            return round(sum(values) / len(values), 2)

        monthly_profile = []

        month_names = [
            "Enero", "Febrero", "Marzo", "Abril",
            "Mayo", "Junio", "Julio", "Agosto",
            "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]

        for month in range(1, 13):

            values = monthly_data[month]

            monthly_profile.append({
                "month": month,
                "name": month_names[month - 1],
                "temperature_mean": average(
                    values["temperatures"]
                ),
                "temperature_max_mean": average(
                    values["maximum_temperatures"]
                ),
                "temperature_min_mean": average(
                    values["minimum_temperatures"]
                ),
                "precipitation_mean_daily": average(
                    values["precipitation"]
                ),
                "wind_speed_max_mean": average(
                    values["wind"]
                ),
                "sunshine_duration_mean": average(
                    values["sunshine"]
                ),
                "solar_radiation_mean": average(
                    values["radiation"]
                )
            })

        annual_profile = []

        for year in sorted(annual_data):

            values = annual_data[year]

            annual_profile.append({
                "year": year,
                "temperature_mean": average(
                    values["temperatures"]
                ),
                "precipitation_total": (
                    round(sum(values["precipitation"]), 2)
                    if values["precipitation"]
                    else None
                )
            })

        available_temperatures = [
            record["temperature_mean"]
            for record in records
            if record["temperature_mean"] is not None
        ]

        available_precipitation = [
            record["precipitation"]
            for record in records
            if record["precipitation"] is not None
        ]

        return {
            "location": historical["location"],
            "period": historical["period"],
            "total_records": len(records),
            "monthly_profile": monthly_profile,
            "annual_profile": annual_profile,
            "general_statistics": {
                "temperature_mean": average(
                    available_temperatures
                ),
                "precipitation_mean_daily": average(
                    available_precipitation
                ),
                "precipitation_total": (
                    round(sum(available_precipitation), 2)
                    if available_precipitation
                    else None
                )
            },
            "units": historical["units"],
            "timezone": historical["timezone"]
        }

    @staticmethod
    def get_weather_by_city(city_name):
        """
        Busca una ciudad y consulta sus condiciones meteorológicas.
        """

        locations = WeatherService.search_location(city_name)

        if not locations:
            raise ValueError(
                "No se encontraron resultados para esa ubicación."
            )

        location = locations[0]

        weather = WeatherService.get_weather(
            latitude=location["latitude"],
            longitude=location["longitude"],
            timezone=location.get("timezone") or "auto"
        )

        return {
            "location": location,
            "weather": weather
        }
