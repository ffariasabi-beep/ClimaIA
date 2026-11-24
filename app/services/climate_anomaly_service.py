import math
import time
from threading import Lock

from app.services.weather_service import WeatherService


class ClimateAnomalyService:

    REFERENCE_START_YEAR = 1991
    REFERENCE_END_YEAR = 2020
    MAX_LOCATIONS_PER_ARCHIVE_REQUEST = 24
    LATITUDES = [-75, -45, -15, 15, 45, 75]
    LONGITUDES = [
        -165, -135, -105, -75, -45, -15,
        15, 45, 75, 105, 135, 165
    ]
    REGIONAL_PROFILE_CACHE_SECONDS = 86400
    _regional_profile_cache = {}
    _regional_profile_cache_lock = Lock()

    @classmethod
    def grid_coordinates(cls):
        return [
            {"latitude": latitude, "longitude": longitude}
            for latitude in cls.LATITUDES
            for longitude in cls.LONGITUDES
        ]

    @classmethod
    def fetch_global_annual_profiles(cls, end_year):
        coordinates = cls.grid_coordinates()
        profiles = []
        for offset in range(
            0,
            len(coordinates),
            cls.MAX_LOCATIONS_PER_ARCHIVE_REQUEST
        ):
            location_batch = coordinates[
                offset:offset + cls.MAX_LOCATIONS_PER_ARCHIVE_REQUEST
            ]
            data = WeatherService._request_json(
                WeatherService.ARCHIVE_URL,
                {
                    "latitude": ",".join(
                        str(point["latitude"])
                        for point in location_batch
                    ),
                    "longitude": ",".join(
                        str(point["longitude"])
                        for point in location_batch
                    ),
                    "start_date": (
                        f"{cls.REFERENCE_START_YEAR}-01-01"
                    ),
                    "end_date": f"{end_year}-12-31",
                    "daily": (
                        "temperature_2m_mean,"
                        "precipitation_sum"
                    ),
                    "timezone": "UTC"
                },
                timeout=120
            )

            if isinstance(data, dict):
                data = [data]

            if not isinstance(data, list) or len(data) != len(location_batch):
                raise RuntimeError(
                    "El archivo histórico no devolvió todos los puntos "
                    "de la grilla mundial."
                )

            for coordinate, response in zip(location_batch, data):
                profiles.append({
                    **coordinate,
                    "annual": cls._aggregate_daily_records(
                        response.get("daily", {})
                    )
                })

        return profiles

    @classmethod
    def fetch_regional_annual_profile(
        cls,
        latitude,
        longitude,
        end_year
    ):
        cache_key = (
            round(float(latitude), 4),
            round(float(longitude), 4),
            int(end_year)
        )
        now = time.monotonic()
        with cls._regional_profile_cache_lock:
            cached = cls._regional_profile_cache.get(cache_key)
            if (
                cached
                and now - cached["timestamp"]
                < cls.REGIONAL_PROFILE_CACHE_SECONDS
            ):
                return {
                    "annual_profile": list(cached["annual_profile"])
                }

        data = WeatherService._request_json(
            WeatherService.ARCHIVE_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "start_date": (
                    f"{cls.REFERENCE_START_YEAR}-01-01"
                ),
                "end_date": f"{end_year}-12-31",
                "daily": (
                    "temperature_2m_mean,"
                    "precipitation_sum"
                ),
                "timezone": "UTC"
            },
            timeout=60
        )

        daily = data.get("daily", {})
        if not daily.get("time"):
            raise RuntimeError(
                "El archivo histórico no devolvió datos para esta ubicación."
            )

        annual_profile = cls._aggregate_daily_records(daily)
        with cls._regional_profile_cache_lock:
            if len(cls._regional_profile_cache) >= 128:
                oldest_key = min(
                    cls._regional_profile_cache,
                    key=lambda key: cls._regional_profile_cache[key]["timestamp"]
                )
                cls._regional_profile_cache.pop(oldest_key, None)
            cls._regional_profile_cache[cache_key] = {
                "timestamp": time.monotonic(),
                "annual_profile": annual_profile
            }

        return {
            "annual_profile": list(annual_profile)
        }

    @staticmethod
    def _average(values):
        available = [
            float(value)
            for value in values
            if value is not None and math.isfinite(float(value))
        ]
        if not available:
            return None
        return sum(available) / len(available)

    @staticmethod
    def _linear_slope(records, key):
        values = [
            (record["year"], record[key])
            for record in records
            if record.get(key) is not None
        ]
        if len(values) < 2:
            return None

        mean_year = sum(year for year, _ in values) / len(values)
        mean_value = sum(value for _, value in values) / len(values)
        denominator = sum((year - mean_year) ** 2 for year, _ in values)
        if denominator == 0:
            return None

        return sum(
            (year - mean_year) * (value - mean_value)
            for year, value in values
        ) / denominator

    @classmethod
    def _aggregate_daily_records(cls, daily):
        dates = daily.get("time", [])
        temperatures = daily.get("temperature_2m_mean", [])
        precipitation = daily.get("precipitation_sum", [])
        annual = {}

        for index, date_text in enumerate(dates):
            year = int(date_text[:4])
            year_data = annual.setdefault(year, {
                "temperature_sum": 0.0,
                "temperature_count": 0,
                "precipitation_sum": 0.0,
                "precipitation_count": 0
            })

            if index < len(temperatures) and temperatures[index] is not None:
                temperature = float(temperatures[index])
                if math.isfinite(temperature):
                    year_data["temperature_sum"] += temperature
                    year_data["temperature_count"] += 1

            if index < len(precipitation) and precipitation[index] is not None:
                rainfall = float(precipitation[index])
                if math.isfinite(rainfall):
                    year_data["precipitation_sum"] += rainfall
                    year_data["precipitation_count"] += 1

        return [
            {
                "year": year,
                "temperature_mean": (
                    round(values["temperature_sum"]
                          / values["temperature_count"], 2)
                    if values["temperature_count"]
                    else None
                ),
                "precipitation_total": (
                    round(values["precipitation_sum"], 2)
                    if values["precipitation_count"]
                    else None
                )
            }
            for year, values in sorted(annual.items())
        ]

    @classmethod
    def summarize_grid_year(cls, profiles, year):
        points = []
        for profile in profiles:
            annual = profile.get("annual", [])
            reference = [
                record for record in annual
                if cls.REFERENCE_START_YEAR
                <= record["year"]
                <= cls.REFERENCE_END_YEAR
            ]
            reference_temperature = cls._average(
                record.get("temperature_mean")
                for record in reference
            )
            reference_precipitation = cls._average(
                record.get("precipitation_total")
                for record in reference
            )
            target = next(
                (record for record in annual if record["year"] == year),
                None
            )

            temperature = (
                target.get("temperature_mean")
                if target else None
            )
            precipitation = (
                target.get("precipitation_total")
                if target else None
            )
            temperature_trend = cls._linear_slope(
                reference,
                "temperature_mean"
            )
            precipitation_trend = cls._linear_slope(
                reference,
                "precipitation_total"
            )

            points.append({
                "latitude": profile["latitude"],
                "longitude": profile["longitude"],
                "year": year,
                "reference_period": "1991-2020",
                "temperature_mean": temperature,
                "reference_temperature_mean": (
                    round(reference_temperature, 2)
                    if reference_temperature is not None
                    else None
                ),
                "temperature_anomaly": (
                    round(temperature - reference_temperature, 2)
                    if temperature is not None
                    and reference_temperature is not None
                    else None
                ),
                "precipitation_total": precipitation,
                "reference_precipitation_total": (
                    round(reference_precipitation, 2)
                    if reference_precipitation is not None
                    else None
                ),
                "precipitation_anomaly_pct": (
                    round(
                        (precipitation - reference_precipitation)
                        / reference_precipitation * 100,
                        1
                    )
                    if precipitation is not None
                    and reference_precipitation not in (None, 0)
                    else None
                ),
                "temperature_trend_per_decade": (
                    round(temperature_trend * 10, 2)
                    if temperature_trend is not None
                    else None
                ),
                "precipitation_trend_pct_per_decade": (
                    round(
                        precipitation_trend
                        / reference_precipitation * 1000,
                        1
                    )
                    if precipitation_trend is not None
                    and reference_precipitation not in (None, 0)
                    else None
                )
            })

        if not any(
            point["temperature_anomaly"] is not None
            or point["precipitation_anomaly_pct"] is not None
            for point in points
        ):
            raise RuntimeError(
                f"No hay datos históricos disponibles para {year}."
            )

        return points

    @classmethod
    def summarize_regional_profile(
        cls,
        profile,
        start_year,
        end_year
    ):
        annual = profile.get("annual_profile", [])
        reference = [
            record for record in annual
            if cls.REFERENCE_START_YEAR
            <= record["year"]
            <= cls.REFERENCE_END_YEAR
        ]
        reference_temperature = cls._average(
            record.get("temperature_mean")
            for record in reference
        )
        reference_precipitation = cls._average(
            record.get("precipitation_total")
            for record in reference
        )
        if reference_temperature is None or reference_precipitation is None:
            raise RuntimeError(
                "No se pudo calcular la referencia climática 1991-2020."
            )

        annual_anomalies = []
        for record in annual:
            temperature = record.get("temperature_mean")
            precipitation = record.get("precipitation_total")
            annual_anomalies.append({
                "year": record["year"],
                "temperature_mean": temperature,
                "temperature_anomaly": (
                    round(temperature - reference_temperature, 2)
                    if temperature is not None
                    else None
                ),
                "precipitation_total": precipitation,
                "precipitation_anomaly_pct": (
                    round(
                        (precipitation - reference_precipitation)
                        / reference_precipitation * 100,
                        1
                    )
                    if precipitation is not None
                    and reference_precipitation != 0
                    else None
                )
            })

        selected = [
            record for record in annual_anomalies
            if start_year <= record["year"] <= end_year
        ]
        decades = {}
        for record in selected:
            decade = record["year"] // 10 * 10
            group = decades.setdefault(decade, {
                "temperature_anomalies": [],
                "precipitation_anomalies": []
            })
            if record["temperature_anomaly"] is not None:
                group["temperature_anomalies"].append(
                    record["temperature_anomaly"]
                )
            if record["precipitation_anomaly_pct"] is not None:
                group["precipitation_anomalies"].append(
                    record["precipitation_anomaly_pct"]
                )

        decade_comparison = [
            {
                "decade": decade,
                "temperature_anomaly": (
                    round(cls._average(values["temperature_anomalies"]), 2)
                    if values["temperature_anomalies"]
                    else None
                ),
                "precipitation_anomaly_pct": (
                    round(cls._average(values["precipitation_anomalies"]), 1)
                    if values["precipitation_anomalies"]
                    else None
                )
            }
            for decade, values in sorted(decades.items())
        ]

        temperature_slope = cls._linear_slope(
            selected,
            "temperature_anomaly"
        )
        precipitation_slope = cls._linear_slope(
            selected,
            "precipitation_anomaly_pct"
        )
        valid_temperatures = [
            record for record in selected
            if record["temperature_anomaly"] is not None
        ]

        return {
            "annual": selected,
            "reference": {
                "start_year": cls.REFERENCE_START_YEAR,
                "end_year": cls.REFERENCE_END_YEAR,
                "temperature_mean": round(reference_temperature, 2),
                "precipitation_mean": round(reference_precipitation, 2)
            },
            "decades": decade_comparison,
            "trends": {
                "temperature_per_decade": (
                    round(temperature_slope * 10, 2)
                    if temperature_slope is not None
                    else None
                ),
                "precipitation_pct_per_decade": (
                    round(precipitation_slope * 10, 1)
                    if precipitation_slope is not None
                    else None
                )
            },
            "extremes": {
                "warmest": (
                    max(
                        valid_temperatures,
                        key=lambda item: item["temperature_anomaly"]
                    )
                    if valid_temperatures
                    else None
                ),
                "coolest": (
                    min(
                        valid_temperatures,
                        key=lambda item: item["temperature_anomaly"]
                    )
                    if valid_temperatures
                    else None
                )
            },
            "source": "Open-Meteo Historical Weather API · reanalysis",
            "period": {"start_year": start_year, "end_year": end_year}
        }
