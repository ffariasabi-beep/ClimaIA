
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from sklearn.cluster import MiniBatchKMeans


class ImageAnalysisService:
    """
    Motor de análisis visual de ClimaIA.

    Combina procesamiento digital de imágenes
    con aprendizaje automático no supervisado.
    """

    @staticmethod
    def load_image(image_path):
        path = Path(image_path)

        if not path.exists():
            raise FileNotFoundError(
                f"No se encontró la imagen: {image_path}"
            )

        with Image.open(path) as image:
            image = image.convert("RGB")
            return np.array(image)

    @staticmethod
    def prepare_image(image, max_dimension=1200):
        height, width = image.shape[:2]

        if max(height, width) > max_dimension:
            scale = max_dimension / max(height, width)

            new_width = int(width * scale)
            new_height = int(height * scale)

            image = cv2.resize(
                image,
                (new_width, new_height),
                interpolation=cv2.INTER_AREA
            )

        return image

    @staticmethod
    def calculate_vegetation_index(image):
        """
        Indicador experimental basado en los canales
        verde y rojo de una imagen RGB.

        No representa el NDVI satelital real.
        """

        image_float = image.astype(np.float32)

        red = image_float[:, :, 0]
        green = image_float[:, :, 1]

        index = (
            (green - red) /
            (green + red + 1e-6)
        )

        return index

    @staticmethod
    def calculate_green_coverage(image):
        """
        Estima el porcentaje de píxeles con tonalidades verdes.
        No confirma por sí solo la presencia de vegetación.
        """

        hsv = cv2.cvtColor(
            image,
            cv2.COLOR_RGB2HSV
        )

        lower_green = np.array([30, 35, 25])
        upper_green = np.array([95, 255, 255])

        mask = cv2.inRange(
            hsv,
            lower_green,
            upper_green
        )

        total_pixels = mask.size
        green_pixels = cv2.countNonZero(mask)

        percentage = (
            green_pixels / total_pixels
        ) * 100

        return round(float(percentage), 2)


    @staticmethod
    def calculate_color_distribution(image):
        """
        Calcula la proporción de píxeles verdes,
        azules y otros tonos de una imagen.
        """

        hsv = cv2.cvtColor(
            image,
            cv2.COLOR_RGB2HSV
        )

        # Identificación de tonalidades verdes.
        green_mask = cv2.inRange(
            hsv,
            np.array([30, 35, 25]),
            np.array([95, 255, 255])
        )

        # Identificación de tonalidades azules.
        blue_mask = cv2.inRange(
            hsv,
            np.array([96, 35, 25]),
            np.array([130, 255, 255])
        )

        total_pixels = hsv.shape[0] * hsv.shape[1]

        green_pixels = cv2.countNonZero(green_mask)
        blue_pixels = cv2.countNonZero(blue_mask)

        # Los píxeles restantes pertenecen a otros tonos.
        other_pixels = total_pixels - green_pixels - blue_pixels

        return {
            "Tonalidades verdes": round(
                green_pixels / total_pixels * 100, 2
            ),
            "Tonalidades azules": round(
                blue_pixels / total_pixels * 100, 2
            ),
            "Otros tonos": round(
                other_pixels / total_pixels * 100, 2
            )
        }

    @staticmethod
    def segment_image(image, clusters=5):
        """
        Aplica K-Means no supervisado para agrupar
        píxeles según sus características de color.

        Los grupos permiten estudiar la distribución
        de diferentes regiones visuales de la imagen.
        """

        height, width = image.shape[:2]

        pixels = image.reshape(-1, 3)

        # Se utiliza una muestra para entrenar el algoritmo.
        rng = np.random.default_rng(42)

        sample_size = min(30000, len(pixels))

        sample_indices = rng.choice(
            len(pixels),
            size=sample_size,
            replace=False
        )

        sample = pixels[sample_indices]

        unique_colors = np.unique(sample, axis=0)
        cluster_count = min(clusters, len(unique_colors))

        model = MiniBatchKMeans(
            n_clusters=cluster_count,
            random_state=42,
            batch_size=2048,
            n_init=3,
            max_iter=100
        )

        model.fit(sample)

        # Cada píxel recibe el grupo de color más cercano.
        labels = model.predict(pixels)

        centers = model.cluster_centers_.astype(np.uint8)

        segments = []

        for cluster_id in range(cluster_count):

            pixel_count = int(
                np.sum(labels == cluster_id)
            )

            percentage = (
                pixel_count / len(pixels)
            ) * 100

            color = centers[cluster_id].reshape(1, 1, 3)

            hsv_color = cv2.cvtColor(
                color,
                cv2.COLOR_RGB2HSV
            )[0, 0]

            hue, saturation, value = hsv_color

            if (
                30 <= hue <= 95
                and saturation >= 35
                and value >= 25
            ):
                category = "Tonalidades verdes"

            elif (
                90 <= hue <= 130
                and saturation >= 40
            ):
                category = "Tonalidades azules"

            else:
                category = "Otros tonos"

            segments.append({
                "cluster": cluster_id + 1,
                "category": category,
                "percentage": round(float(percentage), 2),
                "pixels": pixel_count,
                "color_rgb": [
                    int(value) for value in centers[cluster_id]
                ]
            })

        segments.sort(
            key=lambda segment: segment["percentage"],
            reverse=True
        )

        return {
            "algorithm": "MiniBatch K-Means",
            "clusters": cluster_count,
            "segments": segments,
            "processed_pixels": int(height * width)
        }

    @staticmethod
    def analyze_image(image_path):
        """
        Ejecuta el análisis completo de una imagen.
        """

        original = ImageAnalysisService.load_image(
            image_path
        )

        original_height, original_width = original.shape[:2]

        image = ImageAnalysisService.prepare_image(original)

        vegetation_index = (
            ImageAnalysisService.calculate_vegetation_index(
                image
            )
        )

        green_coverage = (
            ImageAnalysisService.calculate_green_coverage(
                image
            )
        )

        segmentation = (
            ImageAnalysisService.segment_image(image)
        )

        return {
            "width": int(original_width),
            "height": int(original_height),
            "green_coverage_percentage": green_coverage,
            "average_vegetation_index": round(
                float(np.mean(vegetation_index)),
                4
            ),
            "analyzed_pixels": int(
                image.shape[0] * image.shape[1]
            ),
            "segmentation": segmentation,
            "analysis_type": (
                "Procesamiento digital y aprendizaje "
                "automático no supervisado"
            )
        }


    @staticmethod
    def compare_images(first_image_path, second_image_path):
        """
        Compara la distribución de colores de dos imágenes
        de una misma región.
        """

        first_image = ImageAnalysisService.load_image(
            first_image_path
        )

        second_image = ImageAnalysisService.load_image(
            second_image_path
        )

        first_image = ImageAnalysisService.prepare_image(
            first_image
        )

        second_image = ImageAnalysisService.prepare_image(
            second_image
        )

        if first_image.shape != second_image.shape:
            second_image = cv2.resize(
                second_image,
                (first_image.shape[1], first_image.shape[0])
            )

        # Distribución de colores de cada fotografía.
        first_distribution = (
            ImageAnalysisService.calculate_color_distribution(
                first_image
            )
        )

        second_distribution = (
            ImageAnalysisService.calculate_color_distribution(
                second_image
            )
        )

        category_comparison = []

        for category in first_distribution:

            first_value = first_distribution[category]
            second_value = second_distribution[category]

            difference = round(
                second_value - first_value,
                2
            )

            category_comparison.append({
                "category": category,
                "first_percentage": first_value,
                "second_percentage": second_value,
                "difference": difference
            })

        # Conservamos el indicador verde para compatibilidad
        # con los resultados que ya muestra el HTML.
        first_coverage = first_distribution[
            "Tonalidades verdes"
        ]

        second_coverage = second_distribution[
            "Tonalidades verdes"
        ]

        difference = round(
            second_coverage - first_coverage,
            2
        )

        if difference > 0:
            interpretation = "Aumento de tonalidades verdes"

        elif difference < 0:
            interpretation = "Disminución de tonalidades verdes"

        else:
            interpretation = "Sin diferencias en la cobertura verde"

        return {
            "first_coverage": first_coverage,
            "second_coverage": second_coverage,
            "difference_percentage_points": difference,
            "interpretation": interpretation,
            "category_comparison": category_comparison
        }
