import base64
from unittest.mock import Mock, patch

import pytest

from app.services.territory_research_service import TerritoryResearchService


def test_tile_coordinates_maps_longitude_and_latitude_to_gibs_level():
    assert TerritoryResearchService._tile_coordinates(0, 0, 9) == (256, 256)


def test_fetch_satellite_tiles_requests_real_gibs_tile_and_encodes_it():
    response = Mock()
    response.headers = {"Content-Type": "image/jpeg"}
    response.content = b"jpeg-tile"

    with patch(
        "app.services.territory_research_service.requests.get",
        return_value=response
    ) as get:
        images = TerritoryResearchService.fetch_satellite_tiles(
            -31.4,
            -64.2,
            ["2020-06-15"]
        )

    expected_x, expected_y = TerritoryResearchService._tile_coordinates(
        -31.4,
        -64.2,
        TerritoryResearchService.TILE_ZOOM
    )
    request_url = get.call_args.args[0]
    assert request_url.endswith(
        f"/9/{expected_y}/{expected_x}.jpeg"
    )
    assert images == [{
        "date": "2020-06-15",
        "media_type": "image/jpeg",
        "data": base64.b64encode(b"jpeg-tile").decode("ascii")
    }]


def test_fetch_satellite_tiles_rejects_non_image_responses():
    response = Mock()
    response.headers = {"Content-Type": "application/json"}
    response.content = b'{"error":"missing"}'

    with patch(
        "app.services.territory_research_service.requests.get",
        return_value=response
    ):
        with pytest.raises(RuntimeError, match="no devolvió una imagen JPEG"):
            TerritoryResearchService.fetch_satellite_tiles(
                0,
                0,
                ["2020-06-15"]
            )
