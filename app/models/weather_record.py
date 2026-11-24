
from datetime import datetime, timezone

from app.extensions import db


class WeatherRecord(db.Model):
    """
    Almacena valores climáticos históricos de una localidad.

    Los registros se identifican por localidad, período y variable.
    """

    __tablename__ = "weather_records"

    id = db.Column(db.Integer, primary_key=True)

    location_id = db.Column(
        db.Integer,
        db.ForeignKey("locations.id"),
        nullable=False,
        index=True
    )

    record_date = db.Column(
        db.Date,
        nullable=False,
        index=True
    )

    temperature_mean = db.Column(db.Float)
    temperature_max = db.Column(db.Float)
    temperature_min = db.Column(db.Float)

    precipitation = db.Column(db.Float)

    wind_speed_max = db.Column(db.Float)

    sunshine_duration = db.Column(db.Float)

    solar_radiation = db.Column(db.Float)

    data_source = db.Column(
        db.String(50),
        nullable=False,
        default="Open-Meteo ERA5"
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    location = db.relationship(
        "Location",
        back_populates="weather_records"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "location_id",
            "record_date",
            name="uq_weather_location_date"
        ),
    )

    def __repr__(self):
        return (
            f"<WeatherRecord location={self.location_id} "
            f"date={self.record_date}>"
        )
