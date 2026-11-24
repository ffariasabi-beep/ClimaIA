
from datetime import datetime, timezone

from app.extensions import db


class Location(db.Model):
    """
    Representa una localidad del catálogo mundial de GeoNames.
    """

    __tablename__ = "locations"

    id = db.Column(db.Integer, primary_key=True)

    geoname_id = db.Column(
        db.Integer,
        unique=True,
        nullable=False,
        index=True
    )

    name = db.Column(db.String(150), nullable=False, index=True)
    ascii_name = db.Column(db.String(150))

    country_code = db.Column(db.String(2), nullable=False, index=True)

    admin1_code = db.Column(db.String(100))
    admin2_code = db.Column(db.String(100))

    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)

    population = db.Column(db.BigInteger, default=0)

    timezone_name = db.Column(db.String(100))

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    weather_records = db.relationship(
        "WeatherRecord",
        back_populates="location",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Location {self.name}, {self.country_code}>"
