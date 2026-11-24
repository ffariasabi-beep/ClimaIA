
import json

from flask import current_app

from app.services.ai_provider_service import AIProviderService


class AIService:

    @staticmethod
    def _generate_report(
        system_prompt,
        user_prompt,
        conversation_history=None,
        max_completion_tokens=1500
    ):

        model = current_app.config.get("GROQ_MODEL")

        payload = {
            "model": model,
            "max_completion_tokens": max_completion_tokens,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                *(conversation_history or []),
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]
        }

        result, _, _ = AIProviderService.complete_chat(
            payload,
            timeout=45,
            require_text=True
        )
        return result.choices[0].message.content.strip()

    @staticmethod
    def generate_similarity_report(similarity_result):
        locations = []

        for result in similarity_result.get("results", [])[:5]:
            location = result.get("location", {})
            monthly_comparison = result.get(
                "comparison", {}
            ).get("monthly_comparison", [])

            locations.append({
                "localidad": location.get("name"),
                "pais": location.get("country"),
                "distancia_climatica_normalizada": result.get(
                    "distance_index"
                ),
                "RMSE_temperatura_C": result.get("temperature_rmse"),
                "RMSE_precipitacion_diaria_mm": result.get(
                    "precipitation_rmse"
                ),
                "comparacion_mensual": [
                    {
                        "mes": month.get("name") or month.get("month"),
                        "temperatura_referencia_C": month.get(
                            "first_temperature"
                        ),
                        "temperatura_localidad_similar_C": month.get(
                            "second_temperature"
                        ),
                        "precipitacion_referencia_mm_dia": month.get(
                            "first_precipitation_daily"
                        ),
                        "precipitacion_localidad_similar_mm_dia": month.get(
                            "second_precipitation_daily"
                        )
                    }
                    for month in monthly_comparison
                ]
            })

        target = similarity_result.get("target", {})
        context = {
            "localidad_de_referencia": {
                "localidad": target.get("name"),
                "pais": target.get("country")
            },
            "periodo": similarity_result.get("period"),
            "metodo": similarity_result.get("method"),
            "localidades_mas_similares": locations
        }

        system_prompt = """
Sos un asistente especializado en análisis climático.
Interpretá exclusivamente los perfiles y métricas proporcionados.
La distancia climática normalizada es un índice relativo: menor valor
indica perfiles más parecidos y no representa un porcentaje.
Los RMSE de temperatura se expresan en °C y los de precipitación
diaria en mm. No afirmes causalidades ni tendencias que estos promedios
mensuales no demuestren. No inventes datos, ubicaciones ni mediciones.
Escribí en español claro y conciso, destacando similitudes estacionales
y explicando las limitaciones de comparar promedios históricos.
"""

        user_prompt = (
            "Interpretá estos resultados de similitud climática:\n\n"
            f"{json.dumps(context, ensure_ascii=False)}"
        )

        return AIService._generate_report(
            system_prompt,
            user_prompt
        )

    @staticmethod
    def generate_observatory_insight(region, local_climate):
        context = {
            "ubicacion_seleccionada": {
                "localidad": region.get("city"),
                "provincia_o_region": region.get("region"),
                "pais": region.get("country"),
                "latitud": region.get("latitude"),
                "longitud": region.get("longitude")
            },
            "condiciones_meteorologicas_actuales": {
                "temperatura_C": region.get("temperature"),
                "sensacion_termica_C": region.get("feels_like"),
                "humedad_porcentaje": region.get("humidity"),
                "precipitacion_ultima_hora_mm": region.get("precipitation"),
                "precipitacion_acumulada_hoy_mm": region.get(
                    "precipitation_today"
                ),
                "viento_km_h": region.get("wind_speed"),
                "hora_local": region.get("time"),
                "fuente": "Open-Meteo · condiciones actuales del modelo"
            },
            "clima_historico_local": local_climate
        }

        system_prompt = """
Sos el asistente de observación climática local de ClimaIA. Interpretá
exclusivamente los datos recibidos para la localidad seleccionada. No
interpretes condiciones de otras ciudades ni anomalías globales.

Separá claramente el tiempo meteorológico actual de la evolución climática
histórica. Si se proporciona un perfil ERA5 local, describí sus tendencias
calculadas y su referencia 1991-2020; es un punto regional y no representa
automáticamente a todo el país. Si falta el perfil, decí que no hay evidencia
suficiente para concluir sobre calentamiento o tendencias. En ese caso,
interpretá de todos modos las condiciones actuales que sí estén disponibles
y explicá brevemente qué significan, sin presentarlas como tendencias.
Si el perfil disponible es una normal mensual 1991-2020, describí únicamente
ese patrón de referencia y no afirmes tendencias anuales. No infieras una
tendencia climática a partir del tiempo de un solo día.

La precipitación actual representa el registro horario del modelo; el
acumulado diario es otra medida. Diferencialos si ambos están disponibles.
Usá exclusivamente los valores recibidos, sin inventar causas ni mediciones.
Si la fuente histórica está limitada o no disponible, mencioná esa limitación
en una sola frase y no confundas ese problema con la disponibilidad de Groq.
Respondé en español con una lectura breve, clara y centrada en este lugar.
"""

        user_prompt = (
            "Interpretá la observación climática de la localidad seleccionada. "
            "Incluí tendencias históricas locales solo si están disponibles; "
            "no extrapoles al país entero:\n\n"
            f"{json.dumps(context, ensure_ascii=False)}"
        )

        return AIService._generate_report(
            system_prompt,
            user_prompt,
            max_completion_tokens=650
        )

    @staticmethod
    def generate_territory_research_answer(
        question,
        selection,
        climate_profile,
        satellite_images,
        conversation_history
    ):
        context = {
            "seleccion_geografica": selection,
            "producto_satelital": (
                "NASA GIBS · MODIS Aqua Corrected Reflectance · color real"
            ),
            "fechas_de_los_mosaicos": [
                image["date"] for image in satellite_images
            ],
            "contexto_climatico": climate_profile,
            "pregunta_de_investigacion": question
        }

        system_prompt = """
Sos el asistente de investigación territorial de ClimaIA. Ayudás a explorar
preguntas sobre la relación entre el territorio, sus observaciones satelitales
y su historia climática. Respondé la pregunta concreta en tono conversacional;
no uses una plantilla fija de informe.

Integrá la evidencia disponible y distinguí sus límites:
- Los mosaicos adjuntos son imágenes diarias NASA MODIS Aqua de color real.
  Son una vista de referencia de la zona central seleccionada, pueden tener
  nubes o huecos y no prueban por sí solos un cambio en el terreno.
- El contexto climático puede ser una serie anual de Open-Meteo o una normal
  mensual local de la base de ClimaIA, ambas con referencia 1991-2020. La
  normal mensual no permite inferir tendencias anuales ni cambios posteriores
  a 2020; si corresponde a una localidad cercana, indicá cuál y su distancia.
- Si el contexto informa que no hay perfil disponible, decilo explícitamente.
  Respondé lo que permita la evidencia satelital y la pregunta, pero no
  inventes datos climáticos ni tendencias ni presentes una lectura visual
  como análisis climático histórico.

Relacioná ambas fuentes solo cuando los datos lo permitan. Separá observación,
interpretación e hipótesis; no afirmes causalidad, clasificación de cobertura,
NDVI/NDWI ni cambios cuantificados. No inventes datos, tendencias o
características geográficas. Si falta evidencia, decilo y sugerí qué dato o
período sería útil para continuar la investigación. No te limites a describir
la imagen: conectá la pregunta con el contexto climático disponible.
"""

        user_prompt = (
            "Contexto de esta consulta:\n\n"
            f"{json.dumps(context, ensure_ascii=False)}\n\n"
            "Considerá los mosaicos adjuntos de las fechas indicadas y respondé "
            "la pregunta usando conjuntamente la evidencia visual disponible "
            "y el perfil climático, sin exceder sus limitaciones."
        )
        content = [{"type": "text", "text": user_prompt}]

        for image in satellite_images:
            content.append({
                "type": "text",
                "text": (
                    "Mosaico NASA MODIS Aqua de color real, fecha "
                    f"{image['date']}; corresponde al tile central de la "
                    "selección geográfica."
                )
            })
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{image['media_type']};base64,"
                        f"{image['data']}"
                    )
                }
            })

        return AIService._generate_report(
            system_prompt,
            content,
            conversation_history=conversation_history,
            max_completion_tokens=900
        )

    @staticmethod
    def generate_climate_report(
        visual_comparison,
        first_weather=None,
        second_weather=None,
        weather_comparison=None
    ):

        context = {
            "analisis_visual": visual_comparison,
            "meteorologia_fecha_1": first_weather,
            "meteorologia_fecha_2": second_weather,
            "diferencias_meteorologicas": weather_comparison
        }

        system_prompt = """
Sos un asistente especializado en análisis climático y ambiental.

Analizá los resultados visuales y meteorológicos proporcionados.

Organizá el informe en estos apartados:

1. OBSERVACIONES VISUALES
Interpretá los porcentajes y diferencias de color.

2. ANÁLISIS METEOROLÓGICO
Interpretá las diferencias de temperatura, precipitaciones
y viento cuando los datos estén disponibles.

3. POSIBLES RELACIONES
Explicá posibles relaciones entre los resultados sin afirmar
causalidades que los datos no demuestren.

4. LIMITACIONES
Aclarar que los porcentajes de color no identifican por sí solos
vegetación, sequía, contaminación ni cambios climáticos.
El índice RGB experimental no equivale al NDVI satelital.

5. CONCLUSIÓN
Presentá una conclusión basada exclusivamente en los datos.

No inventes mediciones, fechas ni ubicaciones.
No confundas variaciones meteorológicas puntuales con
tendencias de cambio climático.

Escribí en español, con lenguaje claro, formal y ordenado.
Utilizá títulos, párrafos, listas y tablas Markdown cuando sean útiles.
"""

        user_prompt = (
            "Elaborá un informe climático a partir de estos resultados:\n\n"
            f"{context}"
        )

        return AIService._generate_report(
            system_prompt,
            user_prompt
        )

    @staticmethod
    def generate_single_image_report(visual_analysis):

        system_prompt = """
Sos un asistente especializado en análisis visual aplicado
a investigaciones climáticas y ambientales.

Recibís resultados numéricos obtenidos mediante procesamiento
digital de una única fotografía.

Elaborá un informe con estos apartados:

1. CARACTERÍSTICAS DE LA IMAGEN
Describí las dimensiones y los elementos técnicos disponibles.

2. DISTRIBUCIÓN VISUAL
Interpretá la cobertura verde estimada, el índice RGB experimental
y los grupos de colores detectados, si están disponibles.

3. POSIBLE INTERÉS AMBIENTAL
Explicá qué aspectos visuales podrían ser útiles para una
investigación ambiental o climática, sin asegurar que representen
vegetación real, sequía, contaminación o cambios del clima.

4. LIMITACIONES
Aclarar que el análisis se basa en colores de píxeles.
No equivale a una clasificación semántica, una medición satelital
NDVI ni una observación meteorológica.

5. CONCLUSIÓN
Resumí qué información aporta la fotografía y qué información
adicional sería necesaria para realizar una investigación climática.

No inventes ubicación, fecha, condiciones meteorológicas,
especies vegetales ni causas ambientales.
No afirmes que una sola imagen demuestra un cambio climático.

Escribí en español, con lenguaje claro y formal.
Utilizá títulos y listas Markdown cuando sean útiles.
"""

        user_prompt = (
            "Analizá los resultados de esta única imagen:\n\n"
            f"{visual_analysis}"
        )

        return AIService._generate_report(
            system_prompt,
            user_prompt
        )

    @staticmethod
    def generate_weather_comparison_report(
        first_weather,
        second_weather,
        weather_comparison
    ):

        context = {
            "primera_fecha": first_weather,
            "segunda_fecha": second_weather,
            "diferencias": weather_comparison
        }

        system_prompt = """
Sos un asistente especializado en análisis meteorológico y climático.

Tu tarea es comparar registros meteorológicos históricos
de dos fechas de una misma ubicación.

Organizá el informe en estos apartados:

1. COMPARACIÓN DE TEMPERATURAS
Interpretá temperatura media, máxima y mínima.

2. COMPORTAMIENTO DE LAS PRECIPITACIONES
Compará las precipitaciones registradas.

3. COMPORTAMIENTO DEL VIENTO
Interpretá las velocidades máximas registradas.

4. INTERPRETACIÓN GENERAL
Explicá las principales diferencias entre las dos fechas.
No afirmes relaciones causales que los datos no demuestren.

5. LIMITACIONES
Aclarar que dos fechas representan observaciones puntuales
y no permiten establecer tendencias de cambio climático.

6. CONCLUSIÓN
Resumí los cambios meteorológicos más relevantes.

No inventes valores, fechas ni ubicaciones.
Utilizá exclusivamente los registros proporcionados.
No incluyas análisis de fotografías ni de colores.

Escribí en español, con lenguaje claro y formal.
Utilizá títulos, párrafos y tablas Markdown cuando sean útiles.
"""

        user_prompt = (
            "Elaborá un informe comparativo exclusivamente meteorológico "
            "con estos registros:\n\n"
            f"{context}"
        )

        return AIService._generate_report(
            system_prompt,
            user_prompt
        )
