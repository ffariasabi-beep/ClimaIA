from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import date
from io import BytesIO
import math
import re
import threading
import time
import xml.etree.ElementTree as ET

import numpy as np
import requests
from PIL import Image


class TerritoryAnalyticsError(RuntimeError):
    pass


class TerritoryAnalyticsService:
    NASA_WMS_URL = (
        "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/"
    )
    NASA_NDVI_LAYER = "MODIS_Terra_L3_NDVI_Monthly"
    NASA_NDVI_COLOR_MAP_URL = (
        "https://gibs.earthdata.nasa.gov/colormaps/v1.0/"
        "MODIS_L3_NDVI.xml"
    )
    TERRASCOPE_WMS_URL = "https://titiler.terrascope.be/wms"
    IMAGE_SIZE = 256
    POINT_HALF_SIZE_METERS = 2500
    MAX_AREA_SPAN_METERS = 2_000_000
    CACHE_SECONDS = 6 * 60 * 60
    MAX_CACHE_ENTRIES = 128
    EARTH_RADIUS_METERS = 6_378_137

    WORLD_COVER_CLASSES = (
        (10, "Cobertura arbórea", (0, 100, 0), "#006400"),
        (20, "Matorral", (255, 187, 34), "#FFBB22"),
        (30, "Pastizal", (255, 255, 76), "#FFFF4C"),
        (40, "Cultivos", (240, 150, 255), "#F096FF"),
        (50, "Área construida", (250, 0, 0), "#FA0000"),
        (60, "Suelo desnudo o escasa vegetación", (180, 180, 180), "#B4B4B4"),
        (70, "Nieve o hielo", (240, 240, 240), "#F0F0F0"),
        (80, "Agua permanente", (0, 100, 200), "#0064C8"),
        (90, "Humedal herbáceo", (0, 150, 160), "#0096A0"),
        (95, "Manglar", (0, 207, 117), "#00CF75"),
        (100, "Musgo o líquenes", (250, 230, 160), "#FAE6A0"),
    )

    _cache = {}
    _cache_lock = threading.Lock()
    _color_map = None
    _color_map_lock = threading.Lock()

    @classmethod
    def analyze(cls, selection, primary_date, comparison_date=None):
        bounds = cls._project_selection(selection)
        selection_summary = {
            "name": selection.get("name") or (
                "Punto seleccionado"
                if selection.get("type") == "point"
                else "Área seleccionada"
            ),
            "type": selection.get("type")
        }
        cache_key = (
            tuple(round(value, 1) for value in bounds),
            primary_date,
            comparison_date
        )
        cached = cls._get_cached(cache_key)
        if cached is not None:
            cached["selection"] = selection_summary
            return cached

        with ThreadPoolExecutor(max_workers=4) as executor:
            vegetation_future = executor.submit(
                cls._vegetation_analysis,
                bounds,
                primary_date,
                comparison_date
            )
            land_cover_futures = {
                year: executor.submit(cls._land_cover_map, bounds, year)
                for year in (2020, 2021)
            }

            vegetation, vegetation_error = cls._run_product(
                vegetation_future
            )
            land_cover = {}
            land_cover_errors = {}
            for year, future in land_cover_futures.items():
                land_cover[year], land_cover_errors[year] = (
                    cls._run_product(future)
                )

        warnings = [
            error for error in (
                vegetation_error,
                *land_cover_errors.values()
            )
            if error
        ]
        available_products = [
            product for product in (
                vegetation,
                *land_cover.values()
            )
            if product is not None
        ]
        if not available_products:
            raise TerritoryAnalyticsError(
                "NASA GIBS y ESA WorldCover no devolvieron datos "
                "analizables. Intentá nuevamente más tarde."
            )

        cover_2020 = land_cover.get(2020)
        cover_2021 = land_cover.get(2021)
        land_cover_comparison = None
        if cover_2020 and cover_2021:
            land_cover_comparison = cls._compare_land_cover(
                cover_2020,
                cover_2021,
                bounds
            )

        result = {
            "selection": selection_summary,
            "vegetation": vegetation,
            "land_cover": {
                "maps": [
                    cls._public_land_cover(item)
                    for item in (cover_2020, cover_2021)
                    if item is not None
                ],
                "comparison": land_cover_comparison,
                "comparison_note": (
                    "WorldCover 2020 v100 y 2021 v200 usan versiones "
                    "distintas del algoritmo. Las diferencias de clase "
                    "son cambios cartográficos observados y no prueban "
                    "por sí solas una transformación real del terreno."
                )
            },
            "warnings": warnings,
            "sources": [
                {
                    "name": "NASA MODIS Terra L3 NDVI mensual",
                    "url": "https://gibs.earthdata.nasa.gov/"
                },
                {
                    "name": "ESA WorldCover 2020 v100 / 2021 v200",
                    "url": "https://esa-worldcover.org/en/data-access"
                }
            ],
            "method_note": (
                "NDVI se estima al decodificar la escala cromática oficial "
                "de NASA en una imagen de 256 × 256 píxeles. La composición "
                "de cobertura se estima a partir de la paleta categórica "
                "WorldCover en la misma malla. Son resúmenes de vista "
                "remuestreados, no estadísticas de píxeles nativos de 10 m."
            )
        }
        cls._store_cached(cache_key, result)
        return result

    @classmethod
    def _vegetation_analysis(
        cls,
        bounds,
        primary_date,
        comparison_date
    ):
        color_map = cls._get_ndvi_color_map()
        primary, primary_warning = cls._ndvi_period(
            bounds,
            primary_date,
            color_map
        )
        comparison = None
        warnings = [primary_warning] if primary_warning else []
        if comparison_date:
            comparison, comparison_warning = cls._ndvi_period(
                bounds,
                comparison_date,
                color_map
            )
            if comparison_warning:
                warnings.append(comparison_warning)

        delta = None
        if primary and comparison:
            delta = round(
                comparison["mean_ndvi"] - primary["mean_ndvi"],
                3
            )

        return {
            "available": primary is not None,
            "unit": "NDVI (adimensional)",
            "primary": primary,
            "comparison": comparison,
            "delta_mean": delta,
            "warnings": warnings,
            "source": (
                "NASA MODIS Terra L3 NDVI mensual · resolución nativa "
                "aproximada de 1 km"
            )
        }

    @classmethod
    def _ndvi_period(cls, bounds, requested_date, color_map):
        month = date.fromisoformat(requested_date[:10]).replace(day=1)
        for offset in range(4):
            image_date = cls._subtract_months(month, offset)
            raster = cls._get_map(
                cls.NASA_WMS_URL,
                {
                    "SERVICE": "WMS",
                    "VERSION": "1.3.0",
                    "REQUEST": "GetMap",
                    "LAYERS": cls.NASA_NDVI_LAYER,
                    "STYLES": "default",
                    "CRS": "EPSG:3857",
                    "BBOX": cls._format_bounds(bounds),
                    "WIDTH": cls.IMAGE_SIZE,
                    "HEIGHT": cls.IMAGE_SIZE,
                    "FORMAT": "image/png",
                    "TRANSPARENT": "TRUE",
                    "TIME": image_date.isoformat()
                },
                "NASA MODIS Terra NDVI"
            )
            summary = cls._summarize_ndvi(raster, bounds, color_map)
            if summary["valid_pixels"]:
                summary.update({
                    "requested_date": month.isoformat(),
                    "date": image_date.isoformat()
                })
                warning = (
                    None if offset == 0 else
                    "NASA no tenía cobertura NDVI utilizable para "
                    f"{month.isoformat()}; se usó "
                    f"{image_date.isoformat()}."
                )
                return summary, warning

        raise TerritoryAnalyticsError(
            "NASA MODIS Terra no tiene píxeles NDVI válidos para "
            f"{month.isoformat()} ni para los tres meses anteriores "
            "en esta zona."
        )

    @classmethod
    def _summarize_ndvi(cls, raster, bounds, color_map):
        pixels = np.asarray(raster.convert("RGBA"))
        rgb = pixels[:, :, :3]
        alpha = pixels[:, :, 3] > 0
        values = np.full(alpha.shape, np.nan, dtype=np.float32)

        for color, value in color_map.items():
            matches = np.all(rgb == color, axis=2) & alpha
            values[matches] = value

        valid = np.isfinite(values)
        valid_pixels = int(np.count_nonzero(valid))
        total_pixels = int(values.size)
        if not valid_pixels:
            return {
                "mean_ndvi": None,
                "minimum_ndvi": None,
                "maximum_ndvi": None,
                "coverage_percentage": 0.0,
                "valid_pixels": 0,
                "sample_pixels": total_pixels
            }

        row_weights = cls._row_area_weights(bounds, values.shape[0])
        weighted_values = np.where(valid, values, 0) * row_weights[:, None]
        valid_weights = np.where(valid, row_weights[:, None], 0)
        return {
            "mean_ndvi": round(
                float(np.sum(weighted_values) / np.sum(valid_weights)),
                3
            ),
            "minimum_ndvi": round(float(np.nanmin(values)), 3),
            "maximum_ndvi": round(float(np.nanmax(values)), 3),
            "coverage_percentage": round(
                valid_pixels / total_pixels * 100,
                1
            ),
            "valid_pixels": valid_pixels,
            "sample_pixels": total_pixels
        }

    @classmethod
    def _land_cover_map(cls, bounds, year):
        version = "v1" if year == 2020 else "v2"
        layer = f"esa-worldcover-map-10m-{year}-{version}_map"
        raster = cls._get_map(
            cls.TERRASCOPE_WMS_URL,
            {
                "SERVICE": "WMS",
                "VERSION": "1.3.0",
                "REQUEST": "GetMap",
                "LAYERS": layer,
                "STYLES": "",
                "CRS": "EPSG:3857",
                "BBOX": cls._format_bounds(bounds),
                "WIDTH": cls.IMAGE_SIZE,
                "HEIGHT": cls.IMAGE_SIZE,
                "FORMAT": "image/tiff; application=geotiff",
                "TRANSPARENT": "TRUE",
                "TIME": f"{year}-01-01"
            },
            f"ESA WorldCover {year}"
        )
        return cls._summarize_land_cover(raster, bounds, year)

    @classmethod
    def _summarize_land_cover(cls, raster, bounds, year):
        pixels = np.asarray(raster.convert("RGBA"))
        rgb = pixels[:, :, :3]
        alpha = pixels[:, :, 3] > 0
        classes = np.zeros(alpha.shape, dtype=np.uint8)
        row_weights = cls._row_area_weights(bounds, pixels.shape[0])

        for code, _, color, _ in cls.WORLD_COVER_CLASSES:
            classes[np.all(rgb == color, axis=2) & alpha] = code

        known = (classes > 0) & alpha
        weights = row_weights[:, None]
        total_weight = float(np.sum(np.where(known, weights, 0)))
        known_pixels = int(np.count_nonzero(known))
        if not known_pixels or total_weight <= 0:
            raise TerritoryAnalyticsError(
                f"ESA WorldCover {year} no devolvió clases reconocibles "
                "para la zona seleccionada."
            )

        categories = []
        percentages = {}
        for code, label, _, color_hex in cls.WORLD_COVER_CLASSES:
            class_mask = classes == code
            area_weight = float(
                np.sum(np.where(class_mask, weights, 0))
            )
            if area_weight <= 0:
                continue
            percentage = round(area_weight / total_weight * 100, 2)
            percentages[code] = percentage
            categories.append({
                "code": code,
                "label": label,
                "percentage": percentage,
                "color": color_hex
            })

        categories.sort(
            key=lambda category: category["percentage"],
            reverse=True
        )
        nontransparent = int(np.count_nonzero(alpha))
        return {
            "year": year,
            "version": "v100" if year == 2020 else "v200",
            "classes": categories,
            "water_percentage": percentages.get(80, 0.0),
            "classified_pixels": known_pixels,
            "sample_pixels": int(classes.size),
            "classified_coverage_percentage": round(
                known_pixels / max(1, nontransparent) * 100,
                1
            ),
            "class_percentages_by_code": percentages,
            "source": (
                f"ESA WorldCover {year} 10 m · muestra WMS remuestreada"
            ),
            "_class_grid": classes
        }

    @classmethod
    def _get_ndvi_color_map(cls):
        with cls._color_map_lock:
            if cls._color_map is not None:
                return cls._color_map
            try:
                response = requests.get(
                    cls.NASA_NDVI_COLOR_MAP_URL,
                    timeout=20
                )
                response.raise_for_status()
            except requests.RequestException as error:
                raise TerritoryAnalyticsError(
                    "No se pudo consultar la escala NDVI oficial de NASA."
                ) from error

            try:
                root = ET.fromstring(response.content)
            except ET.ParseError as error:
                raise TerritoryAnalyticsError(
                    "NASA devolvió una escala NDVI con formato inválido."
                ) from error

            color_map = {}
            value_pattern = re.compile(
                r"^\[\s*(-?\d+(?:\.\d+)?)\s*,\s*"
                r"(-?\d+(?:\.\d+)?)\s*\)"
            )
            for entry in root.iter():
                if not entry.tag.endswith("ColorMapEntry"):
                    continue
                if entry.attrib.get("transparent", "").lower() == "true":
                    continue
                rgb_text = entry.attrib.get("rgb", "")
                value_text = entry.attrib.get("value", "")
                match = value_pattern.match(value_text)
                if not match:
                    continue
                try:
                    color = tuple(int(value) for value in rgb_text.split(","))
                    low, high = map(float, match.groups())
                except (TypeError, ValueError):
                    continue
                if len(color) == 3 and high > low:
                    color_map[color] = (low + high) / 2

            if not color_map:
                raise TerritoryAnalyticsError(
                    "La escala oficial de NASA no contiene valores NDVI "
                    "utilizables."
                )
            cls._color_map = color_map
            return color_map

    @classmethod
    def _get_map(cls, url, params, product_name):
        try:
            response = requests.get(url, params=params, timeout=45)
            response.raise_for_status()
        except requests.Timeout as error:
            raise TerritoryAnalyticsError(
                f"{product_name} tardó demasiado en responder."
            ) from error
        except requests.RequestException as error:
            raise TerritoryAnalyticsError(
                f"No se pudo consultar {product_name}."
            ) from error

        content_type = (
            response.headers.get("Content-Type", "")
            .split(";", 1)[0]
            .strip()
            .lower()
        )
        if content_type not in ("image/png", "image/tiff", "image/jpeg"):
            raise TerritoryAnalyticsError(
                f"{product_name} no devolvió una imagen raster válida."
            )
        try:
            with Image.open(BytesIO(response.content)) as image:
                raster = image.convert("RGBA")
        except (OSError, ValueError) as error:
            raise TerritoryAnalyticsError(
                f"No se pudo interpretar el raster de {product_name}."
            ) from error
        if raster.size != (cls.IMAGE_SIZE, cls.IMAGE_SIZE):
            raise TerritoryAnalyticsError(
                f"{product_name} devolvió una imagen con dimensiones "
                "inesperadas."
            )
        return raster

    @staticmethod
    def _run_product(future):
        try:
            return future.result(), None
        except TerritoryAnalyticsError as error:
            return None, str(error)

    @classmethod
    def _project_selection(cls, selection):
        selection_type = selection.get("type")
        if selection_type == "point":
            latitude = float(selection["latitude"])
            longitude = float(selection["longitude"])
            if not -85.05112878 <= latitude <= 85.05112878:
                raise ValueError(
                    "El análisis satelital con proyección Web Mercator "
                    "no cubre latitudes polares."
                )
            center_x, center_y = cls._project(longitude, latitude)
            half_size = cls.POINT_HALF_SIZE_METERS
            return (
                center_x - half_size,
                center_y - half_size,
                center_x + half_size,
                center_y + half_size
            )
        if selection_type != "area":
            raise ValueError("Seleccioná un punto o un área para analizar.")

        south = float(selection["south"])
        north = float(selection["north"])
        west = float(selection["west"])
        east = float(selection["east"])
        if south < -85.05112878 or north > 85.05112878:
            raise ValueError(
                "El análisis satelital con proyección Web Mercator "
                "no cubre latitudes polares."
            )
        min_x, min_y = cls._project(west, south)
        max_x, max_y = cls._project(east, north)
        if (
            max_x - min_x > cls.MAX_AREA_SPAN_METERS
            or max_y - min_y > cls.MAX_AREA_SPAN_METERS
        ):
            raise ValueError(
                "El área es demasiado extensa para un resumen satelital. "
                "Acercá el mapa y seleccioná una zona menor."
            )
        return min_x, min_y, max_x, max_y

    @classmethod
    def _project(cls, longitude, latitude):
        latitude = min(max(latitude, -85.05112878), 85.05112878)
        x = cls.EARTH_RADIUS_METERS * math.radians(longitude)
        y = cls.EARTH_RADIUS_METERS * math.log(
            math.tan(math.pi / 4 + math.radians(latitude) / 2)
        )
        return x, y

    @staticmethod
    def _format_bounds(bounds):
        return ",".join(f"{value:.2f}" for value in bounds)

    @classmethod
    def _row_area_weights(cls, bounds, height):
        min_y, max_y = bounds[1], bounds[3]
        projected_y = max_y - (
            (np.arange(height, dtype=np.float64) + 0.5)
            / height
        ) * (max_y - min_y)
        latitudes = (
            2 * np.arctan(np.exp(projected_y / cls.EARTH_RADIUS_METERS))
            - math.pi / 2
        )
        return np.cos(latitudes) ** 2

    @staticmethod
    def _subtract_months(value, months):
        month_index = value.year * 12 + value.month - 1 - months
        year, month = divmod(month_index, 12)
        return date(year, month + 1, 1)

    @classmethod
    def _compare_land_cover(cls, first, second, bounds):
        first_grid = first["_class_grid"]
        second_grid = second["_class_grid"]
        valid = (first_grid > 0) & (second_grid > 0)
        row_weights = cls._row_area_weights(bounds, first_grid.shape[0])
        valid_pixels = int(np.count_nonzero(valid))
        if not valid_pixels:
            return None

        changed = valid & (first_grid != second_grid)
        weights = row_weights[:, None]
        valid_weight = float(np.sum(np.where(valid, weights, 0)))
        changed_weight = float(np.sum(np.where(changed, weights, 0)))
        changed_percentage = round(
            changed_weight / valid_weight * 100,
            2
        )
        transitions = []
        if np.any(changed):
            labels = {
                code: label
                for code, label, _, _ in cls.WORLD_COVER_CLASSES
            }
            transition_counts = {}
            for row, column in np.argwhere(changed):
                pair = (
                    int(first_grid[row, column]),
                    int(second_grid[row, column])
                )
                transition_counts[pair] = (
                    transition_counts.get(pair, 0)
                    + float(row_weights[row])
                )
            for pair, area_weight in transition_counts.items():
                transitions.append({
                    "from_code": pair[0],
                    "from_label": labels[pair[0]],
                    "to_code": pair[1],
                    "to_label": labels[pair[1]],
                    "sample_pixels": int(
                        np.count_nonzero(
                            changed
                            & (first_grid == pair[0])
                            & (second_grid == pair[1])
                        )
                    ),
                    "percentage_of_sample": round(
                        area_weight / valid_weight * 100,
                        2
                    )
                })
            transitions.sort(
                key=lambda transition: transition["sample_pixels"],
                reverse=True
            )

        return {
            "from_year": first["year"],
            "to_year": second["year"],
            "changed_sample_percentage": changed_percentage,
            "compared_pixels": valid_pixels,
            "leading_class_transitions": transitions[:5],
            "interpretation": (
                "Diferencia entre mapas de clasificación; no equivale a "
                "cambio real confirmado en terreno."
            )
        }

    @staticmethod
    def _public_land_cover(item):
        return {
            key: value
            for key, value in item.items()
            if not key.startswith("_") and key != "class_percentages_by_code"
        }

    @classmethod
    def _get_cached(cls, key):
        now = time.monotonic()
        with cls._cache_lock:
            cached = cls._cache.get(key)
            if cached is None or now - cached["timestamp"] >= cls.CACHE_SECONDS:
                return None
            return copy.deepcopy(cached["result"])

    @classmethod
    def _store_cached(cls, key, result):
        with cls._cache_lock:
            if len(cls._cache) >= cls.MAX_CACHE_ENTRIES:
                oldest_key = min(
                    cls._cache,
                    key=lambda item: cls._cache[item]["timestamp"]
                )
                cls._cache.pop(oldest_key, None)
            cls._cache[key] = {
                "timestamp": time.monotonic(),
                "result": copy.deepcopy(result)
            }
