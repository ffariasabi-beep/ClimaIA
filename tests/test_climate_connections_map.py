from unittest.mock import Mock

import pytest

from app import create_app
from app.extensions import login_manager
from app.routes import main as main_routes


class AuthenticatedTestUser:
    is_authenticated = True
    is_active = True
    is_anonymous = False

    def get_id(self):
        return "connections-test-user"


@pytest.fixture
def connections_client(monkeypatch):
    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False
    )
    monkeypatch.setattr(
        login_manager,
        "_user_callback",
        lambda user_id: AuthenticatedTestUser()
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = "connections-test-user"
        session["_fresh"] = True
    return client


def test_connections_results_render_map_with_target_and_match_data(
    connections_client,
    monkeypatch
):
    monthly_comparison = [{
        "month": month,
        "name": f"Mes {month}",
        "first_temperature": 10.0,
        "second_temperature": 11.0,
        "first_precipitation_daily": 1.0,
        "second_precipitation_daily": 1.2
    } for month in range(1, 13)]
    similarity_result = {
        "target": {
            "name": "Córdoba",
            "country": "Argentina",
            "latitude": -31.4,
            "longitude": -64.2
        },
        "period": {"start": "1991-01-01", "end": "2020-12-31"},
        "count": 1,
        "results": [{
            "location": {
                "name": "Istanbul",
                "country": "Turquía",
                "latitude": 41.0,
                "longitude": 29.0
            },
            "distance_index": 0.25,
            "temperature_rmse": 1.2,
            "precipitation_rmse": 0.4,
            "comparison": {
                "monthly_comparison": monthly_comparison
            }
        }],
        "method": "Distancia normalizada.",
        "message": None
    }
    monkeypatch.setattr(
        main_routes.LocationService,
        "get_by_geoname_id",
        Mock(return_value={
            "name": "Córdoba",
            "geoname_id": 3860259
        })
    )
    monkeypatch.setattr(
        main_routes.SimilarityService,
        "find_similar_locations",
        Mock(return_value=similarity_result)
    )
    monkeypatch.setattr(
        main_routes.AIService,
        "generate_similarity_report",
        Mock(return_value=None)
    )

    response = connections_client.post(
        "/climate-connections",
        data={
            "action": "find_similar",
            "selected_geoname_id": "3860259"
        }
    )

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'id="climate-connections-map"' in page
    assert 'data-target-lat="-31.4"' in page
    assert 'data-target-lon="-64.2"' in page
    assert 'data-lat="41.0"' in page
    assert 'data-lon="29.0"' in page
    assert "leaflet@1.9.4/dist/leaflet.js" in page
