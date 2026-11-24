
from app.extensions import db
from app.models import Location
from app.services.location_catalog_service import LocationCatalogService


class LocationImportService:

    BATCH_SIZE = 1000

    @classmethod
    def import_geonames_catalog(cls):
        """
        Importa el catálogo cities15000 de GeoNames
        en la base de datos de ClimaIA.

        Evita duplicar identificadores y coordenadas.
        """

        catalog = LocationCatalogService.load_locations()

        existing_ids = {
            row[0]
            for row in db.session.query(Location.geoname_id)
            .filter(Location.geoname_id.isnot(None))
            .all()
        }

        existing_coordinates = {
            (round(float(row[0]), 6), round(float(row[1]), 6))
            for row in db.session.query(
                Location.latitude,
                Location.longitude
            ).all()
        }

        imported = 0
        skipped_existing = 0
        skipped_coordinates = 0
        batch = []

        try:
            for item in catalog:

                geoname_id = item["geoname_id"]

                latitude = round(item["latitude"], 6)
                longitude = round(item["longitude"], 6)

                coordinates = (latitude, longitude)

                if geoname_id in existing_ids:
                    skipped_existing += 1
                    continue

                if coordinates in existing_coordinates:
                    skipped_coordinates += 1
                    continue

                location = Location(
                    geoname_id=geoname_id,
                    name=item["name"][:150],
                    ascii_name=item["ascii_name"][:150],
                    country=None,
                    country_code=item["country_code"] or None,
                    admin_region=None,
                    latitude=latitude,
                    longitude=longitude,
                    timezone=item["timezone"] or None,
                    population=item["population"]
                )

                batch.append(location)

                existing_ids.add(geoname_id)
                existing_coordinates.add(coordinates)

                if len(batch) >= cls.BATCH_SIZE:
                    db.session.add_all(batch)
                    db.session.flush()

                    imported += len(batch)
                    batch = []

            if batch:
                db.session.add_all(batch)
                db.session.flush()

                imported += len(batch)

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise

        return {
            "catalog_total": len(catalog),
            "imported": imported,
            "skipped_existing": skipped_existing,
            "skipped_coordinates": skipped_coordinates,
            "database_total": Location.query.count()
        }
