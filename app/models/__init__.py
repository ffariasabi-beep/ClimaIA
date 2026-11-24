
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db, login_manager


def utc_now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(
        db.String(60),
        unique=True,
        nullable=False,
        index=True
    )

    email = db.Column(
        db.String(150),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash = db.Column(db.String(255), nullable=False)

    phone = db.Column(db.String(30), nullable=True)

    google_id = db.Column(
        db.String(255),
        unique=True,
        nullable=True,
        index=True
    )

    email_verified = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )
    
    role = db.Column(
        db.String(20),
        nullable=False,
        default="researcher"
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    investigations = db.relationship(
        "Investigation",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"

class PendingRegistration(db.Model):
    __tablename__ = "pending_registrations"

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(150), nullable=False, unique=True)
    phone = db.Column(db.String(30), nullable=True)

    password_hash = db.Column(db.String(255), nullable=False)
    verification_code_hash = db.Column(db.String(255), nullable=False)

    expires_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

class Location(db.Model):
    __tablename__ = "locations"

    id = db.Column(db.Integer, primary_key=True)

    # Identificador único de GeoNames
    geoname_id = db.Column(
        db.Integer,
        unique=True,
        nullable=True,
        index=True
    )

    name = db.Column(db.String(150), nullable=False, index=True)

    ascii_name = db.Column(db.String(150), nullable=True)

    country = db.Column(db.String(100), nullable=True, index=True)

    country_code = db.Column(db.String(3), nullable=True)

    admin_region = db.Column(db.String(150), nullable=True)

    latitude = db.Column(db.Numeric(9, 6), nullable=False)

    longitude = db.Column(db.Numeric(9, 6), nullable=False)

    timezone = db.Column(db.String(80), nullable=True)

    elevation_m = db.Column(db.Float, nullable=True)

    population = db.Column(
        db.BigInteger,
        nullable=False,
        default=0
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    weather_records = db.relationship(
        "WeatherRecord",
        back_populates="location"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "latitude",
            "longitude",
            name="uq_location_coordinates"
        ),
    )

    def __repr__(self):
        return f"<Location {self.name}, {self.country}>"


class DataSource(db.Model):
    __tablename__ = "data_sources"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(120), nullable=False)

    provider = db.Column(db.String(120), nullable=False)

    dataset_code = db.Column(
        db.String(80),
        nullable=False,
        unique=True
    )

    source_type = db.Column(
        db.String(30),
        nullable=False
    )

    resolution_km = db.Column(db.Float, nullable=True)

    temporal_resolution = db.Column(
        db.String(30),
        nullable=True
    )

    coverage_start = db.Column(db.Date, nullable=True)

    documentation_url = db.Column(db.String(500), nullable=True)

    license_name = db.Column(db.String(150), nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    weather_records = db.relationship(
        "WeatherRecord",
        back_populates="data_source"
    )

    def __repr__(self):
        return f"<DataSource {self.dataset_code}>"


class WeatherRecord(db.Model):
    __tablename__ = "weather_records"

    id = db.Column(db.Integer, primary_key=True)

    location_id = db.Column(
        db.Integer,
        db.ForeignKey("locations.id"),
        nullable=False,
        index=True
    )

    data_source_id = db.Column(
        db.Integer,
        db.ForeignKey("data_sources.id"),
        nullable=False
    )

    record_date = db.Column(db.Date, nullable=False, index=True)

    dataset_version = db.Column(
        db.String(80),
        nullable=True
    )

    temperature_mean = db.Column(db.Float, nullable=True)

    temperature_max = db.Column(db.Float, nullable=True)

    temperature_min = db.Column(db.Float, nullable=True)

    precipitation_sum = db.Column(db.Float, nullable=True)

    humidity_mean = db.Column(db.Float, nullable=True)

    wind_speed_mean = db.Column(db.Float, nullable=True)

    wind_speed_max = db.Column(db.Float, nullable=True)

    pressure_mean = db.Column(db.Float, nullable=True)

    cloud_cover_mean = db.Column(db.Float, nullable=True)

    soil_moisture_mean = db.Column(db.Float, nullable=True)

    sunshine_duration = db.Column(db.Float, nullable=True)

    missing_variables = db.Column(
        db.JSON,
        nullable=True
    )

    quality_status = db.Column(
        db.String(30),
        nullable=False,
        default="pending"
    )

    raw_metadata = db.Column(
        db.JSON,
        nullable=True
    )

    imported_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    location = db.relationship(
        "Location",
        back_populates="weather_records"
    )

    data_source = db.relationship(
        "DataSource",
        back_populates="weather_records"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "location_id",
            "data_source_id",
            "record_date",
            "dataset_version",
            name="uq_weather_record_origin"
        ),
        db.CheckConstraint(
            "temperature_min IS NULL OR temperature_max IS NULL "
            "OR temperature_min <= temperature_max",
            name="ck_temperature_min_max"
        ),
        db.CheckConstraint(
            "humidity_mean IS NULL OR "
            "(humidity_mean >= 0 AND humidity_mean <= 100)",
            name="ck_humidity_range"
        ),
        db.CheckConstraint(
            "precipitation_sum IS NULL OR precipitation_sum >= 0",
            name="ck_precipitation_nonnegative"
        ),
    )

    def __repr__(self):
        return f"<WeatherRecord {self.record_date}>"


class ClimateProfile(db.Model):
    __tablename__ = "climate_profiles"

    id = db.Column(db.Integer, primary_key=True)

    location_id = db.Column(
        db.Integer,
        db.ForeignKey("locations.id"),
        nullable=False,
        index=True
    )

    period_start = db.Column(db.Date, nullable=False)

    period_end = db.Column(db.Date, nullable=False)

    dataset_code = db.Column(db.String(80), nullable=False)

    algorithm_name = db.Column(db.String(100), nullable=False)

    algorithm_version = db.Column(db.String(50), nullable=False)

    sample_count = db.Column(db.Integer, nullable=False)

    feature_vector = db.Column(db.JSON, nullable=False)

    summary_statistics = db.Column(db.JSON, nullable=False)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    location = db.relationship("Location")

    __table_args__ = (
        db.CheckConstraint(
            "period_start <= period_end",
            name="ck_profile_period"
        ),
        db.CheckConstraint(
            "sample_count >= 0",
            name="ck_profile_sample_count"
        ),
    )


class Investigation(db.Model):
    __tablename__ = "investigations"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    title = db.Column(db.String(180), nullable=False)

    description = db.Column(db.Text, nullable=True)

    investigation_type = db.Column(
        db.String(50),
        nullable=False,
        default="general"
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="draft"
    )

    parameters = db.Column(db.JSON, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False
    )

    user = db.relationship(
        "User",
        back_populates="investigations"
    )

    comparisons = db.relationship(
        "Comparison",
        back_populates="investigation",
        cascade="all, delete-orphan"
    )

    ai_reports = db.relationship(
        "AIReport",
        back_populates="investigation",
        cascade="all, delete-orphan"
    )

    saved_maps = db.relationship(
        "SavedMap",
        back_populates="investigation",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Investigation {self.title}>"


class Comparison(db.Model):
    __tablename__ = "comparisons"

    id = db.Column(db.Integer, primary_key=True)

    investigation_id = db.Column(
        db.Integer,
        db.ForeignKey("investigations.id"),
        nullable=False,
        index=True
    )

    target_location_id = db.Column(
        db.Integer,
        db.ForeignKey("locations.id"),
        nullable=False
    )

    candidate_location_id = db.Column(
        db.Integer,
        db.ForeignKey("locations.id"),
        nullable=False
    )

    target_date = db.Column(db.Date, nullable=False)

    candidate_date = db.Column(db.Date, nullable=False)

    similarity_score = db.Column(db.Float, nullable=False)

    algorithm_name = db.Column(db.String(100), nullable=False)

    algorithm_version = db.Column(db.String(50), nullable=False)

    variables_used = db.Column(db.JSON, nullable=False)

    variable_differences = db.Column(db.JSON, nullable=False)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    investigation = db.relationship(
        "Investigation",
        back_populates="comparisons"
    )

    target_location = db.relationship(
        "Location",
        foreign_keys=[target_location_id]
    )

    candidate_location = db.relationship(
        "Location",
        foreign_keys=[candidate_location_id]
    )

    __table_args__ = (
        db.CheckConstraint(
            "similarity_score >= 0 AND similarity_score <= 100",
            name="ck_similarity_score"
        ),
    )


class Anomaly(db.Model):
    __tablename__ = "anomalies"

    id = db.Column(db.Integer, primary_key=True)

    weather_record_id = db.Column(
        db.Integer,
        db.ForeignKey("weather_records.id"),
        nullable=False,
        index=True
    )

    variable_name = db.Column(db.String(80), nullable=False)

    observed_value = db.Column(db.Float, nullable=False)

    reference_mean = db.Column(db.Float, nullable=True)

    reference_std = db.Column(db.Float, nullable=True)

    z_score = db.Column(db.Float, nullable=True)

    severity = db.Column(
        db.String(30),
        nullable=False
    )

    detection_method = db.Column(
        db.String(100),
        nullable=False
    )

    reference_period = db.Column(db.JSON, nullable=True)

    explanation = db.Column(db.Text, nullable=True)

    detected_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    weather_record = db.relationship("WeatherRecord")


class AIReport(db.Model):
    __tablename__ = "ai_reports"

    id = db.Column(db.Integer, primary_key=True)

    investigation_id = db.Column(
        db.Integer,
        db.ForeignKey("investigations.id"),
        nullable=False,
        index=True
    )

    provider = db.Column(db.String(100), nullable=True)

    model_name = db.Column(db.String(150), nullable=True)

    prompt_version = db.Column(db.String(50), nullable=True)

    report_type = db.Column(
        db.String(50),
        nullable=False,
        default="analysis"
    )

    input_evidence = db.Column(db.JSON, nullable=False)

    generated_content = db.Column(db.Text, nullable=True)

    status = db.Column(
        db.String(30),
        nullable=False,
        default="pending"
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    investigation = db.relationship(
        "Investigation",
        back_populates="ai_reports"
    )


class SavedMap(db.Model):
    __tablename__ = "saved_maps"

    id = db.Column(db.Integer, primary_key=True)

    investigation_id = db.Column(
        db.Integer,
        db.ForeignKey("investigations.id"),
        nullable=False,
        index=True
    )

    title = db.Column(db.String(150), nullable=False)

    map_configuration = db.Column(db.JSON, nullable=False)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    investigation = db.relationship(
        "Investigation",
        back_populates="saved_maps"
    )


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
