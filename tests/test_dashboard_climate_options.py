from pathlib import Path


def test_dashboard_keeps_only_supported_current_climate_map_options():
    template = (
        Path(__file__).parents[1]
        / "app"
        / "templates"
        / "dashboard.html"
    ).read_text(encoding="utf-8")

    assert '<option value="temperature">Temperatura actual</option>' in template
    assert '<option value="humidity">Humedad relativa</option>' in template
    assert '<option value="wind_speed">Velocidad del viento</option>' in template
    assert '<option value="precipitation">Precipitación actual</option>' not in template
    assert '<option value="temperature_anomaly">' not in template
    assert '<option value="temperature_trend">' not in template
    assert '<option value="precipitation_trend">' not in template


def test_temperature_map_palette_has_multiple_stops():
    template = (
        Path(__file__).parents[1]
        / "app"
        / "templates"
        / "dashboard.html"
    ).read_text(encoding="utf-8")

    assert "#3496d6" in template
    assert "#49beb5" in template
    assert "#f4cc5e" in template
    assert "#f1974b" in template
    assert "#99304a" in template
