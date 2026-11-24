
import math
from datetime import date

from app.extensions import db
from app.models import ClimateProfile, Location
from app.services.location_service import LocationService
from app.services.weather_service import WeatherService


class SimilarityService:
    """
    Compara perfiles climáticos históricos y encuentra localidades
    con patrones de temperatura y precipitación similares.
    """

    REFERENCE_START = date(1991, 1, 1)
    REFERENCE_END = date(2020, 12, 31)

    DATASET_CODE = "open-meteo-archive"
    ALGORITHM_NAME = "monthly-climate-profile"
    ALGORITHM_VERSION = "1.0"

    @staticmethod
    def _validate_profile(profile, profile_name):
        if not isinstance(profile, dict):
            raise ValueError(
                f"El perfil de {profile_name} no es válido."
            )

        monthly_profile = profile.get("monthly_profile")

        if not isinstance(monthly_profile, list):
            raise ValueError(
                f"El perfil de {profile_name} no contiene "
                "información mensual."
            )

        months = {}

        for item in monthly_profile:
            if not isinstance(item, dict):
                continue

            month = item.get("month")

            if isinstance(month, int) and month in range(1, 13):
                months[month] = item

        if len(months) != 12:
            raise ValueError(
                f"El perfil de {profile_name} no contiene "
                "los 12 meses del año."
            )

        return months

    @staticmethod
    def _calculate_rmse(first_values, second_values):
        if len(first_values) != len(second_values):
            raise ValueError(
                "Las series deben tener la misma cantidad de valores."
            )

        if not first_values:
            return None

        squared_differences = [
            (first - second) ** 2
            for first, second in zip(first_values, second_values)
        ]

        return round(
            math.sqrt(
                sum(squared_differences) / len(squared_differences)
            ),
            2
        )

    @staticmethod
    def compare_profiles(first_profile, second_profile):
        """
        Compara dos perfiles del mismo período histórico.
        """

        first_period = first_profile.get("period", {})
        second_period = second_profile.get("period", {})

        if (
            first_period.get("start") != second_period.get("start")
            or first_period.get("end") != second_period.get("end")
        ):
            raise ValueError(
                "Los perfiles deben utilizar exactamente "
                "el mismo período histórico."
            )

        first_months = SimilarityService._validate_profile(
            first_profile,
            "la primera localidad"
        )

        second_months = SimilarityService._validate_profile(
            second_profile,
            "la segunda localidad"
        )

        monthly_comparison = []
        temperature_differences = []
        precipitation_differences = []

        first_temperatures = []
        second_temperatures = []
        first_precipitations = []
        second_precipitations = []

        for month in range(1, 13):
            first = first_months[month]
            second = second_months[month]

            first_temperature = first.get("temperature_mean")
            second_temperature = second.get("temperature_mean")

            first_precipitation = first.get(
                "precipitation_mean_daily"
            )
            second_precipitation = second.get(
                "precipitation_mean_daily"
            )

            values = [
                first_temperature,
                second_temperature,
                first_precipitation,
                second_precipitation
            ]

            if any(value is None for value in values):
                raise ValueError(
                    f"No hay datos suficientes para comparar "
                    f"el mes {month}."
                )

            temperature_difference = round(
                second_temperature - first_temperature,
                2
            )

            precipitation_difference = round(
                second_precipitation - first_precipitation,
                2
            )

            first_temperatures.append(first_temperature)
            second_temperatures.append(second_temperature)

            first_precipitations.append(first_precipitation)
            second_precipitations.append(second_precipitation)

            temperature_differences.append(temperature_difference)
            precipitation_differences.append(precipitation_difference)

            monthly_comparison.append({
                "month": month,
                "name": first.get("name"),
                "first_temperature": first_temperature,
                "second_temperature": second_temperature,
                "temperature_difference": temperature_difference,
                "first_precipitation_daily": first_precipitation,
                "second_precipitation_daily": second_precipitation,
                "precipitation_difference": precipitation_difference
            })

        return {
            "period": first_period,
            "locations": {
                "first": first_profile.get("location", {}),
                "second": second_profile.get("location", {})
            },
            "temperature": {
                "rmse": SimilarityService._calculate_rmse(
                    first_temperatures,
                    second_temperatures
                ),
                "mean_absolute_difference": round(
                    sum(abs(value) for value in temperature_differences)
                    / 12,
                    2
                ),
                "monthly_differences": temperature_differences
            },
            "precipitation": {
                "rmse": SimilarityService._calculate_rmse(
                    first_precipitations,
                    second_precipitations
                ),
                "mean_absolute_difference": round(
                    sum(abs(value) for value in precipitation_differences)
                    / 12,
                    2
                ),
                "monthly_differences": precipitation_differences
            },
            "monthly_comparison": monthly_comparison,
            "method": (
                "Comparación de los 12 promedios mensuales de temperatura "
                "y precipitación diaria del mismo período histórico."
            )
        }

    @staticmethod
    def _profile_dates(profile):
        period = profile.get("period", {})

        start = period.get("start", SimilarityService.REFERENCE_START)
        end = period.get("end", SimilarityService.REFERENCE_END)

        if isinstance(start, str):
            start = date.fromisoformat(start)

        if isinstance(end, str):
            end = date.fromisoformat(end)

        return start, end

    @classmethod
    def _get_or_create_stored_profile(cls, location):
        """
        Recupera el perfil guardado de una localidad.
        Si no existe, lo calcula y lo almacena.
        """

        stored = ClimateProfile.query.filter_by(
            location_id=location.id,
            period_start=cls.REFERENCE_START,
            period_end=cls.REFERENCE_END,
            dataset_code=cls.DATASET_CODE,
            algorithm_name=cls.ALGORITHM_NAME,
            algorithm_version=cls.ALGORITHM_VERSION
        ).first()

        if stored is not None:
            return stored

        # Convertir las fechas a cadenas AAAA-MM-DD.
        profile = WeatherService.get_climate_profile(
            latitude=float(location.latitude),
            longitude=float(location.longitude),
            start_date=cls.REFERENCE_START.isoformat(),
            end_date=cls.REFERENCE_END.isoformat(),
            timezone=location.timezone or "auto"
        )

        monthly_profile = profile.get("monthly_profile")

        cls._validate_profile(
            profile,
            location.name
        )

        sample_count = profile.get("total_records", 0)

        stored = ClimateProfile(
            location_id=location.id,
            period_start=cls.REFERENCE_START,
            period_end=cls.REFERENCE_END,
            dataset_code=cls.DATASET_CODE,
            algorithm_name=cls.ALGORITHM_NAME,
            algorithm_version=cls.ALGORITHM_VERSION,
            sample_count=int(sample_count or 0),
            feature_vector={
                "monthly_profile": monthly_profile,
                "units": profile.get("units", {})
            },
            summary_statistics=profile.get(
                "general_statistics",
                {}
            )
        )

        db.session.add(stored)
        db.session.commit()

        return stored

    @staticmethod
    def _stored_profile_to_dict(stored):
        location = stored.location
        location_data = LocationService._serialize_location(location)

        return {
            "location": {
                "id": location.id,
                "geoname_id": location.geoname_id,
                "name": location.name,
                "country": location_data["country_name"],
                "country_code": location_data["country_code"],
                "latitude": float(location.latitude),
                "longitude": float(location.longitude)
            },
            "period": {
                "start": stored.period_start.isoformat(),
                "end": stored.period_end.isoformat()
            },
            "monthly_profile": stored.feature_vector.get(
                "monthly_profile",
                []
            )
        }

    @staticmethod
    def _normalized_distance(comparison, target_profile):
        """
        Índice de distancia sin unidades.
        Un valor menor indica mayor semejanza.
        No representa un porcentaje.
        """

        months = SimilarityService._validate_profile(
            target_profile,
            "la localidad de referencia"
        )

        temperatures = [
            months[month]["temperature_mean"]
            for month in range(1, 13)
        ]

        precipitations = [
            months[month]["precipitation_mean_daily"]
            for month in range(1, 13)
        ]

        def standard_deviation(values):
            average = sum(values) / len(values)

            variance = sum(
                (value - average) ** 2
                for value in values
            ) / len(values)

            return math.sqrt(variance)

        temperature_scale = max(
            standard_deviation(temperatures),
            1.0
        )

        precipitation_scale = max(
            standard_deviation(precipitations),
            0.5
        )

        temperature_distance = (
            comparison["temperature"]["rmse"] / temperature_scale
        )

        precipitation_distance = (
            comparison["precipitation"]["rmse"] / precipitation_scale
        )

        return round(
            math.sqrt(
                (
                    temperature_distance ** 2
                    + precipitation_distance ** 2
                ) / 2
            ),
            4
        )

    @classmethod
    def find_similar_locations(cls, geoname_id, limit=10):
        """
        Busca localidades con perfiles climáticos similares.
        Solo compara perfiles del mismo período, fuente y algoritmo.
        """

        location = Location.query.filter_by(
            geoname_id=geoname_id
        ).first()

        if location is None:
            raise ValueError(
                "No se encontró la localidad solicitada."
            )

        target_stored = cls._get_or_create_stored_profile(location)
        target_profile = cls._stored_profile_to_dict(target_stored)

        candidates = (
            ClimateProfile.query
            .filter(
                ClimateProfile.location_id != location.id,
                ClimateProfile.period_start == cls.REFERENCE_START,
                ClimateProfile.period_end == cls.REFERENCE_END,
                ClimateProfile.dataset_code == cls.DATASET_CODE,
                ClimateProfile.algorithm_name == cls.ALGORITHM_NAME,
                ClimateProfile.algorithm_version == cls.ALGORITHM_VERSION
            )
            .all()
        )

        results = []

        for candidate in candidates:
            try:
                candidate_profile = cls._stored_profile_to_dict(
                    candidate
                )

                comparison = cls.compare_profiles(
                    target_profile,
                    candidate_profile
                )

                distance = cls._normalized_distance(
                    comparison,
                    target_profile
                )

                results.append({
                    "location": candidate_profile["location"],
                    "distance_index": distance,
                    "temperature_rmse": comparison["temperature"]["rmse"],
                    "precipitation_rmse": comparison["precipitation"]["rmse"],
                    "comparison": comparison
                })

            except (ValueError, TypeError, KeyError):
                continue

        results.sort(
            key=lambda item: item["distance_index"]
        )

        return {
            "target": target_profile["location"],
            "period": target_profile["period"],
            "count": min(len(results), limit),
            "results": results[:limit],
            "method": (
                "Ordenamiento por distancia climática normalizada, "
                "calculada a partir de los RMSE mensuales de temperatura "
                "y precipitación diaria."
            ),
            "message": (
                None if results else
                "Todavía no hay otros perfiles climáticos almacenados "
                "para comparar. Es necesario generar perfiles de otras "
                "localidades."
            )
        }
