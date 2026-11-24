import numpy as np
import pytest
from PIL import Image

from app.services.territory_analytics_service import TerritoryAnalyticsService


SYMMETRIC_BOUNDS = (-1000, -1000, 1000, 1000)


def raster(rows):
    return Image.fromarray(np.asarray(rows, dtype=np.uint8), mode="RGBA")


def test_summarize_ndvi_ignores_transparent_pixels_and_reports_coverage():
    image = raster([
        [[10, 20, 30, 255], [10, 20, 30, 255]],
        [[40, 50, 60, 255], [0, 0, 0, 0]]
    ])
    color_map = {
        (10, 20, 30): 0.2,
        (40, 50, 60): 0.8
    }

    summary = TerritoryAnalyticsService._summarize_ndvi(
        image,
        SYMMETRIC_BOUNDS,
        color_map
    )

    assert summary["mean_ndvi"] == pytest.approx(0.4)
    assert summary["minimum_ndvi"] == pytest.approx(0.2)
    assert summary["maximum_ndvi"] == pytest.approx(0.8)
    assert summary["valid_pixels"] == 3
    assert summary["coverage_percentage"] == 75


def test_land_cover_summary_and_comparison_report_sampled_change():
    tree = [0, 100, 0, 255]
    water = [0, 100, 200, 255]
    first = raster([[tree, tree], [water, water]])
    second = raster([[tree, water], [water, water]])

    first_summary = TerritoryAnalyticsService._summarize_land_cover(
        first,
        SYMMETRIC_BOUNDS,
        2020
    )
    second_summary = TerritoryAnalyticsService._summarize_land_cover(
        second,
        SYMMETRIC_BOUNDS,
        2021
    )
    comparison = TerritoryAnalyticsService._compare_land_cover(
        first_summary,
        second_summary,
        SYMMETRIC_BOUNDS
    )

    assert first_summary["water_percentage"] == pytest.approx(50)
    assert sum(
        item["percentage"] for item in first_summary["classes"]
    ) == pytest.approx(100)
    assert comparison["changed_sample_percentage"] == pytest.approx(25)
    assert comparison["leading_class_transitions"][0]["from_code"] == 10
    assert comparison["leading_class_transitions"][0]["to_code"] == 80


def test_project_selection_rejects_areas_exceeding_the_analysis_limit():
    with pytest.raises(ValueError, match="demasiado extensa"):
        TerritoryAnalyticsService._project_selection({
            "type": "area",
            "south": -1,
            "north": 1,
            "west": -30,
            "east": 30
        })


def test_cached_analysis_uses_the_current_selection_name(monkeypatch):
    monkeypatch.setattr(TerritoryAnalyticsService, "_cache", {})
    selection = {
        "type": "point",
        "name": "Córdoba",
        "latitude": -31.4,
        "longitude": -64.2
    }
    bounds = TerritoryAnalyticsService._project_selection(selection)
    cache_key = (
        tuple(round(value, 1) for value in bounds),
        "2020-06-15",
        None
    )
    TerritoryAnalyticsService._store_cached(cache_key, {
        "selection": {
            "type": "point",
            "name": "Localidad anterior"
        },
        "vegetation": None,
        "land_cover": {"maps": []}
    })

    result = TerritoryAnalyticsService.analyze(
        selection,
        "2020-06-15"
    )

    assert result["selection"] == {
        "type": "point",
        "name": "Córdoba"
    }
