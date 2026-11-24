from datetime import date
from unittest.mock import Mock

import pytest

from app import create_app
from app.extensions import login_manager
from app.routes import api as api_routes
from app.services.weather_service import WeatherRateLimitError


class AuthenticatedTestUser:
    is_authenticated = True
    is_active = True
    is_anonymous = False

    def get_id(self):
        return "territory-test-user"


@pytest.fixture
def territory_client(monkeypatch):
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
    return app.test_client()


def test_territory_page_requires_authentication(territory_client):
    response = territory_client.get("/territory/")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_territory_page_renders_satellite_explorer(territory_client):
    with territory_client.session_transaction() as session:
        session["_user_id"] = "territory-test-user"
        session["_fresh"] = True

    response = territory_client.get("/territory/")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "MODIS Aqua" in page
    assert "territory-map" in page
    assert "NASA GIBS" in page
    assert "territory-compare-date" in page
    assert "/api/locations/search" in page
    assert "Investigá el territorio" in page
    assert "territory-question-form" in page
    assert "/api/territory/analytics" in page
    assert "territory-analysis-layer" in page


def test_territory_analytics_validates_and_forwards_selection(
    territory_client,
    monkeypatch
):
    with territory_client.session_transaction() as session:
        session["_user_id"] = "territory-test-user"
        session["_fresh"] = True
    analysis = {"vegetation": None, "land_cover": {"maps": []}}
    analyze = Mock(return_value=analysis)
    monkeypatch.setattr(
        api_routes.TerritoryAnalyticsService,
        "analyze",
        analyze
    )

    invalid_response = territory_client.post(
        "/api/territory/analytics",
        json={
            "selection": {
                "type": "point",
                "latitude": -31.4,
                "longitude": -64.2
            },
            "date": "2020-06-15",
            "compare_active": True,
            "comparison_date": "2020-06-15"
        }
    )

    assert invalid_response.status_code == 400
    analyze.assert_not_called()

    response = territory_client.post(
        "/api/territory/analytics",
        json={
            "selection": {
                "type": "point",
                "name": "Córdoba",
                "latitude": -31.4,
                "longitude": -64.2
            },
            "date": "2020-06-15",
            "compare_active": True,
            "comparison_date": "2019-06-15"
        }
    )

    assert response.status_code == 200
    assert response.json == {"success": True, "analysis": analysis}
    analyze.assert_called_once_with(
        selection={
            "type": "point",
            "name": "Córdoba",
            "latitude": -31.4,
            "longitude": -64.2
        },
        primary_date="2020-06-15",
        comparison_date="2019-06-15"
    )


def test_territory_research_rejects_invalid_selection(territory_client):
    with territory_client.session_transaction() as session:
        session["_user_id"] = "territory-test-user"
        session["_fresh"] = True

    response = territory_client.post(
        "/api/territory/research",
        json={"question": "¿Qué se observa?", "selection": None}
    )

    assert response.status_code == 400
    assert response.json["success"] is False


def test_territory_research_requires_a_provider_before_data_fetch(
    territory_client,
    monkeypatch
):
    with territory_client.session_transaction() as session:
        session["_user_id"] = "territory-test-user"
        session["_fresh"] = True
    territory_client.application.config.update(
        GROQ_API_KEY=""
    )
    climate_fetch = Mock()
    monkeypatch.setattr(
        api_routes.ClimateAnomalyService,
        "fetch_regional_annual_profile",
        climate_fetch
    )

    response = territory_client.post(
        "/api/territory/research",
        json={
            "question": "¿Qué conviene investigar?",
            "selection": {
                "type": "point",
                "latitude": -31.4,
                "longitude": -64.2
            },
            "date": "2020-06-15"
        }
    )

    assert response.status_code == 503
    assert "GROQ_API_KEY y GROQ_MODEL" in response.json["error"]
    climate_fetch.assert_not_called()


def test_territory_research_combines_climate_profile_and_satellite_tiles(
    territory_client,
    monkeypatch
):
    with territory_client.session_transaction() as session:
        session["_user_id"] = "territory-test-user"
        session["_fresh"] = True

    app = territory_client.application
    app.config.update(
        GROQ_API_KEY="test-groq-key",
        GROQ_MODEL="qwen/qwen3.8-27b"
    )
    monkeypatch.setattr(api_routes, "ATLAS_REGION_PROFILE_CACHE", {})
    monkeypatch.setattr(api_routes, "ATLAS_ARCHIVE_COOLDOWN", {"until": 0})
    monkeypatch.setattr(
        api_routes,
        "_find_stored_climate_profile",
        Mock(return_value=None)
    )

    latest_complete_year = date.today().year - 1
    annual_profile = {
        "annual_profile": [
            {
                "year": year,
                "temperature_mean": 12 + (year - 1991) * 0.02,
                "precipitation_total": 700 + (year - 1991)
            }
            for year in range(1991, latest_complete_year + 1)
        ]
    }
    climate_fetch = Mock(return_value=annual_profile)
    satellite_images = [{
        "date": "2020-06-15",
        "media_type": "image/jpeg",
        "data": "dGVzdA=="
    }, {
        "date": "2019-06-15",
        "media_type": "image/jpeg",
        "data": "dGVzdA=="
    }]
    satellite_fetch = Mock(return_value=satellite_images)
    answer = Mock(return_value="Respuesta integrada.")
    monkeypatch.setattr(
        api_routes.ClimateAnomalyService,
        "fetch_regional_annual_profile",
        climate_fetch
    )
    monkeypatch.setattr(
        api_routes.TerritoryResearchService,
        "fetch_satellite_tiles",
        satellite_fetch
    )
    monkeypatch.setattr(
        api_routes.AIService,
        "generate_territory_research_answer",
        answer
    )

    response = territory_client.post(
        "/api/territory/research",
        json={
            "question": "¿Qué conviene investigar en esta zona?",
            "selection": {
                "type": "area",
                "name": "Área seleccionada",
                "south": -32,
                "north": -30,
                "west": -65,
                "east": -63
            },
            "date": "2020-06-15",
            "compare_active": True,
            "comparison_date": "2019-06-15",
            "conversation_history": [
                {"role": "user", "content": "¿Cuál es la referencia?"},
                {"role": "assistant", "content": "1991-2020."}
            ]
        }
    )

    assert response.status_code == 200
    assert response.json["answer"] == "Respuesta integrada."
    assert response.json["climate_available"] is True
    assert response.json["climate_profile_type"] == "annual_series"
    assert response.json["climate_period"]["start_year"] == 1991
    climate_fetch.assert_called_once_with(
        latitude=-31.0,
        longitude=-64.0,
        end_year=latest_complete_year
    )
    satellite_fetch.assert_called_once_with(
        -31.0,
        -64.0,
        ["2020-06-15", "2019-06-15"]
    )
    answer.assert_called_once()
    assert answer.call_args.kwargs["climate_profile"]["reference"][
        "start_year"
    ] == 1991
    assert answer.call_args.kwargs["satellite_images"] == satellite_images
    assert len(answer.call_args.kwargs["conversation_history"]) == 2


def test_territory_research_uses_local_profile_during_archive_cooldown(
    territory_client,
    monkeypatch
):
    with territory_client.session_transaction() as session:
        session["_user_id"] = "territory-test-user"
        session["_fresh"] = True
    territory_client.application.config.update(
        GROQ_API_KEY="test-groq-key",
        GROQ_MODEL="qwen/qwen3.8-27b"
    )

    local_profile = {
        "availability": "available",
        "profile_type": "monthly_normal",
        "source": "Base de datos local de ClimaIA · era5",
        "reference_period": "1991-2020",
        "reference_location": {
            "name": "Córdoba",
            "country_code": "ES",
            "distance_km": 0
        },
        "monthly_profile": [{"month": 1, "temperature_mean": 8}],
        "summary_statistics": {}
    }
    monkeypatch.setattr(
        api_routes,
        "_find_stored_climate_profile",
        Mock(return_value=local_profile)
    )
    monkeypatch.setattr(
        api_routes,
        "_get_or_fetch_atlas_region_profile",
        Mock(return_value=(None, False, (None, 429)))
    )
    satellite_images = [{
        "date": "2020-06-15",
        "media_type": "image/jpeg",
        "data": "dGVzdA=="
    }]
    monkeypatch.setattr(
        api_routes.TerritoryResearchService,
        "fetch_satellite_tiles",
        Mock(return_value=satellite_images)
    )
    answer = Mock(return_value="Respuesta basada en la normal local.")
    monkeypatch.setattr(
        api_routes.AIService,
        "generate_territory_research_answer",
        answer
    )

    response = territory_client.post(
        "/api/territory/research",
        json={
            "question": "¿Cómo es el patrón climático?",
            "selection": {
                "type": "point",
                "name": "Córdoba, España",
                "latitude": 37.8882,
                "longitude": -4.7794
            },
            "date": "2020-06-15"
        }
    )

    assert response.status_code == 200
    assert response.json["climate_available"] is True
    assert response.json["climate_profile_type"] == "monthly_normal"
    assert response.json["climate_period"]["end_year"] == 2020
    assert local_profile["source"] in response.json["sources"]
    assert answer.call_args.kwargs["climate_profile"] == local_profile


def test_territory_research_answers_with_satellite_when_no_climate_cache(
    territory_client,
    monkeypatch
):
    with territory_client.session_transaction() as session:
        session["_user_id"] = "territory-test-user"
        session["_fresh"] = True
    territory_client.application.config.update(
        GROQ_API_KEY="test-groq-key",
        GROQ_MODEL="qwen/qwen3.8-27b"
    )

    monkeypatch.setattr(
        api_routes,
        "_find_stored_climate_profile",
        Mock(return_value=None)
    )
    monkeypatch.setattr(
        api_routes,
        "_get_or_fetch_atlas_region_profile",
        Mock(side_effect=WeatherRateLimitError())
    )
    monkeypatch.setattr(api_routes, "_record_atlas_rate_limit", Mock())
    satellite_images = [{
        "date": "2020-06-15",
        "media_type": "image/jpeg",
        "data": "dGVzdA=="
    }]
    monkeypatch.setattr(
        api_routes.TerritoryResearchService,
        "fetch_satellite_tiles",
        Mock(return_value=satellite_images)
    )
    answer = Mock(return_value="Respuesta con la evidencia disponible.")
    monkeypatch.setattr(
        api_routes.AIService,
        "generate_territory_research_answer",
        answer
    )

    response = territory_client.post(
        "/api/territory/research",
        json={
            "question": "¿Qué se observa?",
            "selection": {
                "type": "point",
                "latitude": -31.4,
                "longitude": -64.2
            },
            "date": "2020-06-15"
        }
    )

    assert response.status_code == 200
    assert response.json["answer"] == "Respuesta con la evidencia disponible."
    assert response.json["climate_available"] is False
    assert response.json["climate_period"] is None
    assert all("Open-Meteo" not in source for source in response.json["sources"])
    assert (
        answer.call_args.kwargs["climate_profile"]["availability"]
        == "unavailable"
    )


def test_atlas_region_profile_endpoint_keeps_its_response_contract(
    territory_client,
    monkeypatch
):
    with territory_client.session_transaction() as session:
        session["_user_id"] = "territory-test-user"
        session["_fresh"] = True

    annual_profile = {
        "annual_profile": [
            {
                "year": year,
                "temperature_mean": 10 + (year - 1991) * 0.1,
                "precipitation_total": 500 + year - 1991
            }
            for year in range(1991, 2021)
        ]
    }
    monkeypatch.setattr(api_routes, "ATLAS_REGION_PROFILE_CACHE", {})
    monkeypatch.setattr(api_routes, "ATLAS_ARCHIVE_COOLDOWN", {"until": 0})
    climate_fetch = Mock(return_value=annual_profile)
    monkeypatch.setattr(
        api_routes.ClimateAnomalyService,
        "fetch_regional_annual_profile",
        climate_fetch
    )

    response = territory_client.get(
        "/api/atlas/region-profile"
        "?latitude=-31.4&longitude=-64.2&start_year=1991&end_year=2020"
    )

    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["profile"]["reference"]["start_year"] == 1991
    assert response.json["profile"]["reference"]["end_year"] == 2020
    climate_fetch.assert_called_once()
