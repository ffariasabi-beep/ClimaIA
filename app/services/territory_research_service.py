import base64
import math

import requests


class TerritoryResearchService:

    GIBS_TILE_URL = (
        "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
        "MODIS_Aqua_CorrectedReflectance_TrueColor/default/{date}/"
        "GoogleMapsCompatible_Level9/{zoom}/{y}/{x}.jpeg"
    )
    TILE_ZOOM = 9
    MAX_TILE_BYTES = 2 * 1024 * 1024

    @classmethod
    def fetch_satellite_tiles(cls, latitude, longitude, dates):
        x, y = cls._tile_coordinates(latitude, longitude, cls.TILE_ZOOM)
        images = []

        for date_text in dates:
            url = cls.GIBS_TILE_URL.format(
                date=date_text,
                zoom=cls.TILE_ZOOM,
                x=x,
                y=y
            )

            try:
                response = requests.get(url, timeout=20)
                response.raise_for_status()
            except requests.Timeout as error:
                raise RuntimeError(
                    "NASA GIBS tardó demasiado en entregar la imagen "
                    f"del {date_text}."
                ) from error
            except requests.RequestException as error:
                raise RuntimeError(
                    "No se pudo obtener el mosaico NASA GIBS "
                    f"del {date_text}."
                ) from error

            media_type = (
                response.headers.get("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if media_type != "image/jpeg":
                raise RuntimeError(
                    "NASA GIBS no devolvió una imagen JPEG válida "
                    f"para el {date_text}."
                )
            if len(response.content) > cls.MAX_TILE_BYTES:
                raise RuntimeError(
                    "El mosaico NASA GIBS superó el tamaño permitido."
                )

            images.append({
                "date": date_text,
                "media_type": media_type,
                "data": base64.b64encode(response.content).decode("ascii")
            })

        return images

    @staticmethod
    def _tile_coordinates(latitude, longitude, zoom):
        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            raise ValueError("Las coordenadas geográficas no son válidas.")

        latitude = min(max(latitude, -85.05112878), 85.05112878)
        tile_count = 2 ** zoom
        x = int((longitude + 180) / 360 * tile_count) % tile_count
        latitude_radians = math.radians(latitude)
        y = int(
            (
                1
                - math.asinh(math.tan(latitude_radians)) / math.pi
            )
            / 2
            * tile_count
        )
        y = min(max(y, 0), tile_count - 1)
        return x, y
