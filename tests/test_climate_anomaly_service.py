from unittest.mock import Mock, patch

import pytest
from requests import HTTPError

from app.services.climate_anomaly_service import ClimateAnomalyService
from app.services.weather_service import (
    WeatherRateLimitError,
    WeatherService
)


def test_aggregate_daily_records_calculates_annual_means_and_totals():
    annual = ClimateAnomalyService._aggregate_daily_records({
        "time": ["2020-01-01", "2020-01-02", "2021-01-01"],
        "temperature_2m_mean": [10, 14, 12],
        "precipitation_sum": [2, None, 3]
    })

    assert annual == [
        {
            "year": 2020,
            "temperature_mean": 12,
            "precipitation_total": 2
        },
        {
            "year": 2021,
            "temperature_mean": 12,
            "precipitation_total": 3
        }
    ]


def test_regional_fetch_requests_only_variables_used_by_atlas():
    response = {
        "daily": {
            "time": ["2020-01-01", "2020-01-02"],
            "temperature_2m_mean": [10, 14],
            "precipitation_sum": [2, 4]
        }
    }

    with patch.object(
        WeatherService,
        "_request_json",
        return_value=response
    ) as request:
        profile = ClimateAnomalyService.fetch_regional_annual_profile(
            latitude=-31.4,
            longitude=-64.2,
            end_year=2020
        )

    assert profile["annual_profile"] == [{
        "year": 2020,
        "temperature_mean": 12,
        "precipitation_total": 6
    }]
    assert request.call_args.args[1]["daily"] == (
        "temperature_2m_mean,precipitation_sum"
    )


def test_global_fetch_splits_grid_to_fit_archive_request_limits():
    daily = {
        "time": ["1991-01-01"],
        "temperature_2m_mean": [10],
        "precipitation_sum": [2]
    }

    def request_batch(_url, params, timeout):
        latitudes = params["latitude"].split(",")
        longitudes = params["longitude"].split(",")
        assert len(latitudes) == len(longitudes)
        assert len(latitudes) <= (
            ClimateAnomalyService.MAX_LOCATIONS_PER_ARCHIVE_REQUEST
        )
        assert timeout == 120
        return [{"daily": daily} for _ in latitudes]

    with patch.object(
        WeatherService,
        "_request_json",
        side_effect=request_batch
    ) as request:
        profiles = ClimateAnomalyService.fetch_global_annual_profiles(1991)

    assert request.call_count == 3
    assert len(profiles) == len(ClimateAnomalyService.grid_coordinates())
    assert profiles[0]["annual"] == [{
        "year": 1991,
        "temperature_mean": 10,
        "precipitation_total": 2
    }]


def test_weather_service_preserves_open_meteo_retry_after_on_429():
    response = Mock()
    response.status_code = 429
    response.text = "Rate limited"
    response.headers = {"Retry-After": "120"}
    response.raise_for_status.side_effect = HTTPError(response=response)

    with patch(
        "app.services.weather_service.requests.get",
        return_value=response
    ):
        with pytest.raises(WeatherRateLimitError) as error:
            WeatherService._request_json("https://example.test", {})

    assert error.value.retry_after == 120


def test_weather_service_uses_hourly_cooldown_when_rate_limited():
    response = Mock()
    response.status_code = 429
    response.text = "Hourly API request limit exceeded"
    response.headers = {}
    response.json.return_value = {
        "reason": "Hourly API request limit exceeded. Try again next hour."
    }
    response.raise_for_status.side_effect = HTTPError(response=response)

    with patch(
        "app.services.weather_service.requests.get",
        return_value=response
    ):
        with pytest.raises(WeatherRateLimitError) as error:
            WeatherService._request_json("https://example.test", {})

    assert error.value.retry_after == 3600


def test_grid_summary_calculates_temperature_and_precipitation_anomalies():
    annual = [
        {
            "year": year,
            "temperature_mean": 10,
            "precipitation_total": 100
        }
        for year in range(1991, 2021)
    ]
    annual.append({
        "year": 2021,
        "temperature_mean": 12,
        "precipitation_total": 60
    })

    points = ClimateAnomalyService.summarize_grid_year(
        [{
            "latitude": -30,
            "longitude": -60,
            "annual": annual
        }],
        2021
    )

    assert points[0]["temperature_anomaly"] == 2
    assert points[0]["precipitation_anomaly_pct"] == -40
    assert points[0]["reference_temperature_mean"] == 10
    assert points[0]["reference_precipitation_total"] == 100


def test_regional_summary_provides_annual_and_decadal_trends():
    annual = [
        {
            "year": year,
            "temperature_mean": 10 + (year - 1991) * 0.1,
            "precipitation_total": 1000
        }
        for year in range(1991, 2021)
    ]

    result = ClimateAnomalyService.summarize_regional_profile(
        {"annual_profile": annual},
        1991,
        2020
    )

    assert len(result["annual"]) == 30
    assert result["reference"]["temperature_mean"] == 11.45
    assert result["trends"]["temperature_per_decade"] == 1
    assert result["trends"]["precipitation_pct_per_decade"] == 0
    assert result["extremes"]["warmest"]["year"] == 2020
    assert result["extremes"]["coolest"]["year"] == 1991
