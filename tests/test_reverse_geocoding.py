from unittest.mock import Mock, patch

import pytest
from flask import Flask

from app.extensions import login_manager
from app.routes.api import api_bp
from app.services.reverse_geocoding_service import ReverseGeocodingService


class AuthenticatedUser:
    is_authenticated = True
    is_active = True
    is_anonymous = False

    def get_id(self):
        return "reverse-geocoding-test-user"


@pytest.fixture
def reverse_geocoding_client(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        BIGDATACLOUD_API_KEY="test-bigdatacloud-key",
        SECRET_KEY="test-session-key"
    )
    login_manager.init_app(app)
    app.register_blueprint(api_bp)
    monkeypatch.setattr(
        login_manager,
        "_user_callback",
        lambda user_id: AuthenticatedUser()
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = "reverse-geocoding-test-user"
        session["_fresh"] = True
    return client, app


def test_reverse_geocoder_returns_locality_subdivision_and_country(
    reverse_geocoding_client
):
    _, app = reverse_geocoding_client
    ReverseGeocodingService._cache.clear()
    response = Mock()
    response.json.return_value = {
        "locality": "Yekaterinburg",
        "principalSubdivision": "Sverdlovsk Oblast",
        "countryName": "Russia"
    }

    with app.app_context(), patch(
        "app.services.reverse_geocoding_service.requests.get",
        return_value=response
    ) as get:
        location = ReverseGeocodingService.lookup(56.8389, 60.6057)

    assert location == {
        "latitude": 56.8389,
        "longitude": 60.6057,
        "locality": "Yekaterinburg",
        "province": "Sverdlovsk Oblast",
        "country": "Russia",
        "is_ocean": False,
        "display_name": (
            "Yekaterinburg, Sverdlovsk Oblast, Russia"
        )
    }
    assert get.call_args.kwargs["params"]["key"] == (
        "test-bigdatacloud-key"
    )


def test_reverse_geocoder_identifies_ocean_coordinates(
    reverse_geocoding_client
):
    _, app = reverse_geocoding_client
    ReverseGeocodingService._cache.clear()
    response = Mock()
    response.json.return_value = {
        "locality": "",
        "principalSubdivision": "",
        "countryName": ""
    }

    with app.app_context(), patch(
        "app.services.reverse_geocoding_service.requests.get",
        return_value=response
    ):
        location = ReverseGeocodingService.lookup(-30, -40)

    assert location["is_ocean"] is True
    assert location["display_name"] == "Mar u océano"


def test_reverse_geocoder_requires_an_api_key(reverse_geocoding_client):
    _, app = reverse_geocoding_client
    app.config["BIGDATACLOUD_API_KEY"] = ""

    with app.app_context(), pytest.raises(
        RuntimeError,
        match="BIGDATACLOUD_API_KEY"
    ):
        ReverseGeocodingService.lookup(12, 34)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        ("bad", "20"),
        ("91", "20"),
        ("40", "181")
    ]
)
def test_reverse_geocoding_route_rejects_invalid_coordinates(
    reverse_geocoding_client,
    latitude,
    longitude
):
    client, _ = reverse_geocoding_client

    response = client.get(
        "/api/geocoding/reverse",
        query_string={"latitude": latitude, "longitude": longitude}
    )

    assert response.status_code == 400
    assert response.json["success"] is False


def test_reverse_geocoding_route_uses_the_geocoding_service(
    reverse_geocoding_client,
    monkeypatch
):
    client, _ = reverse_geocoding_client
    result = {
        "latitude": 56.8,
        "longitude": 60.6,
        "locality": "Yekaterinburg",
        "province": "Sverdlovsk Oblast",
        "country": "Russia",
        "is_ocean": False,
        "display_name": "Yekaterinburg, Sverdlovsk Oblast, Russia"
    }
    lookup = Mock(return_value=result)
    monkeypatch.setattr(ReverseGeocodingService, "lookup", lookup)

    response = client.get(
        "/api/geocoding/reverse",
        query_string={"latitude": "56.8", "longitude": "60.6"}
    )

    assert response.status_code == 200
    assert response.json == {"success": True, "location": result}
    lookup.assert_called_once_with(56.8, 60.6)
