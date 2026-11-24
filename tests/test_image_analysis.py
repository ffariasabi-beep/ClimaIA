
import numpy as np
from PIL import Image

from app.services.image_analysis_service import ImageAnalysisService


def test_image_analysis():
    # Creamos una imagen artificial de prueba.
    image = np.zeros((100, 100, 3), dtype=np.uint8)

    # Agregamos una región verde.
    image[0:50, 0:100] = [40, 180, 60]

    # Guardamos la imagen temporalmente.
    image_path = "tests/test_climate_image.png"
    Image.fromarray(image).save(image_path)

    # Ejecutamos el análisis.
    result = ImageAnalysisService.analyze_image(image_path)

    assert result["width"] == 100
    assert result["height"] == 100
    assert result["analyzed_pixels"] == 10000
    assert result["green_coverage_percentage"] == 50.0
    assert "average_vegetation_index" in result


def test_compare_images():
    # Imagen inicial: 30% de píxeles verdes.
    first = np.zeros((100, 100, 3), dtype=np.uint8)
    first[0:30, :] = [40, 180, 60]

    # Imagen posterior: 60% de píxeles verdes.
    second = np.zeros((100, 100, 3), dtype=np.uint8)
    second[0:60, :] = [40, 180, 60]

    first_path = "tests/first_image.png"
    second_path = "tests/second_image.png"

    Image.fromarray(first).save(first_path)
    Image.fromarray(second).save(second_path)

    result = ImageAnalysisService.compare_images(
        first_path,
        second_path
    )

    assert result["first_coverage"] == 30.0
    assert result["second_coverage"] == 60.0
    assert result["difference_percentage_points"] == 30.0
