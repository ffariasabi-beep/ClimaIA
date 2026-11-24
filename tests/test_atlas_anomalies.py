import time
from datetime import date, datetime, timedelta, timezone

from flask import Flask

from app.extensions import login_manager
from app.routes import api as api_routes
from app.routes.api import api_bp


class AuthenticatedUser:
    is_authenticated = True
    is_active = True
    is_anonymous = False

    def get_id(self):
        return "atlas-anomaly-test-user"


def _annual_profile(end_year):
    annual = [
        {
            "year": year,
            "temperature_mean": 10.0,
            "precipitation_total": 100.0
        }
        for year in range(1991, 2021)
    ]
    annual.append({
        "year": end_year,
        "temperature_mean": 12.0,
        "precipitation_total": 120.0
    })
    return [{
        "latitude": 15,
        "longitude": 15,
        "annual": annual
    }]


def test_anomaly_route_serves_persisted_colors_while_archive_is_rate_limited(
    tmp_path,
    monkeypatch
):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="atlas-test-session-key"
    )
    app.instance_path = str(tmp_path)
    login_manager.init_app(app)
    monkeypatch.setattr(
        login_manager,
        "_user_callback",
        lambda user_id: AuthenticatedUser()
    )
    app.register_blueprint(api_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = "atlas-anomaly-test-user"
        session["_fresh"] = True

    latest_complete_year = date.today().year - 1
    stale_timestamp = (
        datetime.now(timezone.utc) - timedelta(days=2)
    ).isoformat()
    monkeypatch.setattr(
        api_routes,
        "ATLAS_ANOMALY_CACHE",
        {
            "timestamp": time.monotonic(),
            "profiles": _annual_profile(latest_complete_year),
            "through_year": latest_complete_year,
            "fetched_at": stale_timestamp
        }
    )
    with app.app_context():
        api_routes._persist_atlas_anomaly_cache()
    monkeypatch.setattr(
        api_routes,
        "ATLAS_ANOMALY_CACHE",
        {
            "timestamp": 0,
            "profiles": None,
            "through_year": None,
            "fetched_at": None
        }
    )
    monkeypatch.setattr(
        api_routes,
        "ATLAS_ARCHIVE_COOLDOWN",
        {"until": time.monotonic() + 600}
    )

    response = client.get(
        f"/api/atlas/anomalies?year={latest_complete_year}"
    )

    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["stale"] is True
    assert response.json["points"][0]["temperature_mean"] == 12.0
    assert response.json["points"][0]["temperature_anomaly"] == 2.0
    assert response.json["warning"]
