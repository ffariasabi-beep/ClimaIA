from unittest.mock import patch

from app.services.weather_service import WeatherService


def test_weather_keeps_hourly_precipitation_separate_from_daily_total():
    response = {
        "current": {
            "time": "2024-01-02T12:00",
            "temperature_2m": 22.0,
            "relative_humidity_2m": 76,
            "apparent_temperature": 25.0,
            "precipitation": 0.2,
            "weather_code": 61,
            "wind_speed_10m": 10.0
        },
        "current_units": {
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "apparent_temperature": "°C",
            "precipitation": "mm",
            "wind_speed_10m": "km/h"
        },
        "daily": {
            "time": ["2024-01-01", "2024-01-02"],
            "temperature_2m_max": [24.0, 27.0],
            "temperature_2m_min": [18.0, 20.0],
            "precipitation_sum": [4.0, 30.1],
            "precipitation_probability_max": [30, 90]
        },
        "daily_units": {"precipitation_sum": "mm"},
        "timezone": "America/Argentina/Cordoba"
    }

    with patch.object(WeatherService, "_request_json", return_value=response):
        weather = WeatherService.get_weather(-31.4, -64.2)

    assert weather["current"]["temperature"] == 22.0
    assert weather["current"]["feels_like"] == 25.0
    assert weather["current"]["precipitation"] == 0.2
    assert weather["current"]["precipitation_today"] == 30.1
    assert weather["current"]["wind_speed"] == 10.0
    assert weather["current"]["humidity"] == 76
