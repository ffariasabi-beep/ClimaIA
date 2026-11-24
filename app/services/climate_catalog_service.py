
from math import floor
import time

from app.extensions import db
from app.models import ClimateProfile, Location
from app.services.similarity_service import SimilarityService


class ClimateCatalogService:
    """
    Genera un catálogo inicial de perfiles climáticos mundiales.
    Selecciona localidades representativas de distintas regiones.
    """

    @classmethod
    def _select_candidates(
        cls,
        limit=10,
        min_population=50000,
        exclude_geoname_id=None
    ):
        locations = (
            Location.query
            .filter(
                Location.population >= min_population,
                Location.latitude.isnot(None),
                Location.longitude.isnot(None),
                Location.geoname_id.isnot(None)
            )
            .all()
        )

        cells = {}

        for location in locations:
            if (
                exclude_geoname_id is not None
                and location.geoname_id == exclude_geoname_id
            ):
                continue

            latitude = float(location.latitude)
            longitude = float(location.longitude)

            latitude_cell = floor((latitude + 90) / 20)
            longitude_cell = floor((longitude + 180) / 30)

            cell_key = (latitude_cell, longitude_cell)
            current = cells.get(cell_key)

            if (
                current is None
                or (location.population or 0)
                > (current.population or 0)
            ):
                cells[cell_key] = location

        candidates = sorted(
            cells.values(),
            key=lambda location: location.population or 0,
            reverse=True
        )

        return candidates[:limit]

    @classmethod
    def generate_profiles(
        cls,
        limit=10,
        min_population=50000,
        exclude_geoname_id=None
    ):
        """
        Genera perfiles históricos y los almacena en climate_profiles.
        Se detiene si Open-Meteo devuelve un error 429.
        """

        if not isinstance(limit, int) or not 1 <= limit <= 30:
            raise ValueError("El límite debe estar entre 1 y 30.")

        candidates = cls._select_candidates(
            limit=limit,
            min_population=min_population,
            exclude_geoname_id=exclude_geoname_id
        )

        generated = []
        skipped = []
        errors = []
        request_count = 0

        for location in candidates:
            existing = ClimateProfile.query.filter_by(
                location_id=location.id,
                period_start=SimilarityService.REFERENCE_START,
                period_end=SimilarityService.REFERENCE_END,
                dataset_code=SimilarityService.DATASET_CODE,
                algorithm_name=SimilarityService.ALGORITHM_NAME,
                algorithm_version=SimilarityService.ALGORITHM_VERSION
            ).first()

            if existing is not None:
                skipped.append(location.name)
                continue

            # Pausa entre consultas nuevas.
            if request_count > 0:
                time.sleep(90)

            request_count += 1

            try:
                SimilarityService._get_or_create_stored_profile(
                    location
                )

                generated.append({
                    "name": location.name,
                    "country": location.country,
                    "geoname_id": location.geoname_id
                })

            except Exception as error:
                db.session.rollback()

                error_message = str(error)

                errors.append({
                    "location": location.name,
                    "error": error_message
                })

                # No continuar enviando solicitudes si hay límite de API.
                if "429" in error_message:
                    break

        return {
            "period": {
                "start": SimilarityService.REFERENCE_START.isoformat(),
                "end": SimilarityService.REFERENCE_END.isoformat()
            },
            "selected": len(candidates),
            "generated_count": len(generated),
            "skipped_count": len(skipped),
            "error_count": len(errors),
            "generated": generated,
            "skipped": skipped,
            "errors": errors
        }
