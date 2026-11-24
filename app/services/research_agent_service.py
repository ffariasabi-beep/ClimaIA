import json
import re
import unicodedata
from datetime import date
from math import sqrt

from flask import current_app

from app.extensions import db
from app.models import (
    Investigation,
    Location,
    WeatherRecord
)
from app.services.location_service import (
    LocationService,
    country_code_for_name
)
from app.services.ai_provider_service import (
    AIProviderError,
    AIProviderService
)
from app.services.similarity_service import SimilarityService
from app.services.weather_service import WeatherService


class ResearchAgentService:
    MAX_TOOL_ROUNDS = 12
    MAX_TOOL_CALLS = 15
    MAX_PERIOD_YEARS = 50
    MAX_DAILY_DAYS = 90
    MAX_LOCATIONS = 5

    VARIABLES = {
        "temperature_mean": {
            "label": "Temperatura media",
            "unit": "°C",
            "external_field": "temperature_mean",
            "database_field": "temperature_mean",
            "aggregation": "mean"
        },
        "temperature_max": {
            "label": "Temperatura máxima diaria media",
            "unit": "°C",
            "external_field": "temperature_max",
            "database_field": "temperature_max",
            "aggregation": "mean"
        },
        "temperature_min": {
            "label": "Temperatura mínima diaria media",
            "unit": "°C",
            "external_field": "temperature_min",
            "database_field": "temperature_min",
            "aggregation": "mean"
        },
        "precipitation": {
            "label": "Precipitación acumulada",
            "unit": "mm",
            "external_field": "precipitation",
            "database_field": "precipitation_sum",
            "aggregation": "sum"
        },
        "wind_speed_max": {
            "label": "Velocidad máxima diaria media",
            "unit": "km/h",
            "external_field": "wind_speed_max",
            "database_field": "wind_speed_max",
            "aggregation": "mean"
        },
        "sunshine_duration": {
            "label": "Duración de sol",
            "unit": "s",
            "external_field": "sunshine_duration",
            "database_field": "sunshine_duration",
            "aggregation": "mean"
        }
    }

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "search_locations",
                "description": (
                    "Busca localidades en el catálogo local de ClimaIA. "
                    "Usala para resolver nombres o localidades ambiguas."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10
                        }
                    },
                    "required": ["query"],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_historical_records",
                "description": (
                    "Consulta datos meteorológicos históricos de una localidad "
                    "y prepara una serie real para graficar."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "geoname_id": {"type": "integer"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                        "variable": {
                            "type": "string",
                            "enum": list(VARIABLES.keys())
                        },
                        "aggregation": {
                            "type": "string",
                            "enum": ["annual", "monthly", "daily"]
                        }
                    },
                    "required": [
                        "geoname_id",
                        "start_date",
                        "end_date",
                        "variable"
                    ],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_location_climate_profile",
                "description": (
                    "Obtiene el perfil mensual de una localidad. Si no se "
                    "indica período, consulta la normal 1991-2020."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "geoname_id": {"type": "integer"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"}
                    },
                    "required": ["geoname_id"],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "compare_locations",
                "description": (
                    "Compara una variable entre dos y cinco localidades "
                    "durante el mismo período histórico."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "geoname_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "minItems": 2,
                            "maxItems": 5
                        },
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                        "variable": {
                            "type": "string",
                            "enum": list(VARIABLES.keys())
                        }
                    },
                    "required": [
                        "geoname_ids",
                        "start_date",
                        "end_date",
                        "variable"
                    ],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "compare_periods",
                "description": (
                    "Compara una variable en dos períodos de la misma "
                    "localidad, usando los registros disponibles."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "geoname_id": {"type": "integer"},
                        "first_start": {"type": "string"},
                        "first_end": {"type": "string"},
                        "second_start": {"type": "string"},
                        "second_end": {"type": "string"},
                        "variable": {
                            "type": "string",
                            "enum": list(VARIABLES.keys())
                        }
                    },
                    "required": [
                        "geoname_id",
                        "first_start",
                        "first_end",
                        "second_start",
                        "second_end",
                        "variable"
                    ],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "find_similar_climates",
                "description": (
                    "Busca localidades con perfiles climáticos similares "
                    "mediante el servicio de similitud existente."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "geoname_id": {"type": "integer"},
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10
                        }
                    },
                    "required": ["geoname_id"],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "calculate_climate_statistics",
                "description": (
                    "Calcula estadísticas reales de una variable histórica "
                    "para una localidad y período."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "geoname_id": {"type": "integer"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                        "variable": {
                            "type": "string",
                            "enum": list(VARIABLES.keys())
                        }
                    },
                    "required": [
                        "geoname_id",
                        "start_date",
                        "end_date",
                        "variable"
                    ],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_climate_trends",
                "description": (
                    "Calcula una tendencia lineal descriptiva a partir de "
                    "valores anuales observados; no infiere causalidad."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "geoname_id": {"type": "integer"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                        "variable": {
                            "type": "string",
                            "enum": list(VARIABLES.keys())
                        }
                    },
                    "required": [
                        "geoname_id",
                        "start_date",
                        "end_date",
                        "variable"
                    ],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "detect_climate_patterns",
                "description": (
                    "Identifica años extremos y asociaciones entre "
                    "temperatura y precipitación observadas."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "geoname_id": {"type": "integer"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"}
                    },
                    "required": [
                        "geoname_id",
                        "start_date",
                        "end_date"
                    ],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "generate_research_chart",
                "description": (
                    "Prepara un gráfico usando exclusivamente la serie de un "
                    "resultado de herramienta ya generado."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result_id": {"type": "string"},
                        "chart_type": {
                            "type": "string",
                            "enum": ["line", "bar"]
                        }
                    },
                    "required": ["result_id", "chart_type"],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "generate_comparison_table",
                "description": (
                    "Prepara una tabla usando exclusivamente los resultados "
                    "estructurados de una herramienta previa."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result_id": {"type": "string"}
                    },
                    "required": ["result_id"],
                    "additionalProperties": False
                }
            }
        }
    ]

    SAVE_TOOL = {
        "type": "function",
        "function": {
            "name": "save_research",
            "description": (
                "Guarda esta investigación solo cuando el usuario lo solicite "
                "explícitamente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"}
                },
                "required": ["title"],
                "additionalProperties": False
            }
        }
    }

    SYSTEM_PROMPT = """
Sos el agente de investigación climática del Centro de investigaciones
del Módulo 01 de ClimaIA.

Tu función es realizar investigaciones climáticas utilizando las
herramientas disponibles. No respondas solamente explicando los pasos
que deberían realizarse: ejecutá las herramientas.

REGLAS GENERALES:
- Utilizá datos reales obtenidos mediante las herramientas.
- No inventes cifras, períodos, localidades ni fuentes.
- Ejecutá una herramienta por vez.
- No repitas operaciones que ya terminaron correctamente.
- Reutilizá los IDs de localidades obtenidos anteriormente.
- Reutilizá los resultados de herramientas anteriores.
- Si una herramienta falla, explicá qué ocurrió.
- No solicites nuevamente información que ya está disponible.

BÚSQUEDA DE LOCALIDADES:
- Utilizá search_locations para encontrar las localidades.
- Buscá las localidades necesarias y recuperá sus IDs de GeoNames.
- No repitas búsquedas de localidades cuyos IDs ya conocés.
- Si una localidad es ambigua, no elijas una ubicación arbitrariamente.

COMPARACIÓN DE LOCALIDADES:
1. Buscá las localidades necesarias.
2. Ejecutá compare_locations para la primera variable.
3. Ejecutá compare_locations para la segunda variable.
4. Utilizá las tablas y gráficos incluidos en los resultados.
5. No llames a generate_comparison_table ni a
   generate_research_chart para resultados de compare_locations,
   porque esa herramienta ya genera ambos elementos.

ANÁLISIS:
- Indicá las unidades de cada variable.
- Indicá el período analizado.
- Informá las fuentes y la cantidad de registros disponibles.
- Diferenciá promedios y acumulados.
- Describí tendencias sin atribuir causalidad.
- Explicá las limitaciones y los datos faltantes.

GRÁFICOS Y TABLAS:
- Utilizá exclusivamente resultados reales de las herramientas.
- No inventes valores para completar tablas o gráficos.
- Si los resultados ya incluyen tablas y gráficos, reutilizalos.

RESPUESTA:
Organizá la investigación en:
1. Resumen.
2. Resultados comparativos.
3. Tablas y gráficos.
4. Fuentes utilizadas.
5. Limitaciones de los datos.

Respondé siempre en español claro.
"""


    @classmethod
    def run(cls, question, conversation_history, investigation_id, user_id):
        cloudflare_configured = AIProviderService.is_cloudflare_configured()
        groq_configured = AIProviderService.is_configured()
        if not cloudflare_configured and not groq_configured:
            raise RuntimeError(
                "Configurá Cloudflare Workers AI o GROQ_API_KEY y GROQ_MODEL "
                "para investigar."
            )
        use_groq = not cloudflare_configured

        state = {
            "investigation_id": investigation_id,
            "user_id": user_id,
            "question": question,
            "results": [],
            "result_index": {},
            "locations_used": {},
            "tool_errors": [],
            "tool_call_count": 0,
            "allow_save": cls._user_requested_save(question),
            "saved": False
        }

        tools = list(cls.TOOLS)
        if state["allow_save"]:
            tools.append(cls.SAVE_TOOL)

        messages = [
            {"role": "system", "content": cls.SYSTEM_PROMPT}
        ]

        messages.extend(conversation_history[-12:])
        messages.append({"role": "user", "content": question})

        tool_rounds = 0
        completed_tool_calls = {}
        force_final_answer = False

        def execute_tool(name, arguments):
            signature = (
                name,
                json.dumps(
                    arguments,
                    ensure_ascii=False,
                    sort_keys=True
                )
            )
            if signature in completed_tool_calls:
                return completed_tool_calls[signature], True

            try:
                result = cls._dispatch_tool(name, arguments, state)
            except (TypeError, ValueError, RuntimeError) as error:
                result = {"error": str(error)}

            if isinstance(result, dict) and result.get("error"):
                state["tool_errors"].append(
                    f"{name}: {result['error']}"
                )
            completed_tool_calls[signature] = result
            return result, False

        def ask_for_final_answer(message):
            nonlocal force_final_answer
            force_final_answer = True
            messages.append({"role": "user", "content": message})

        def complete_chat(payload, require_text):
            nonlocal use_groq
            if use_groq:
                return AIProviderService.complete_chat(
                    payload,
                    timeout=45,
                    require_text=require_text
                )

            try:
                return AIProviderService.complete_cloudflare_chat(
                    payload,
                    timeout=45,
                    require_text=require_text
                )
            except RuntimeError as error:
                provider_error = error.__cause__
                if not (
                    groq_configured
                    and isinstance(provider_error, AIProviderError)
                    and provider_error.provider == "Cloudflare Workers AI"
                    and provider_error.status == 429
                ):
                    raise

                current_app.logger.warning(
                    "[ClimaIA] Cloudflare alcanzó su límite; "
                    "se continuará esta investigación con Groq."
                )
                use_groq = True
                return AIProviderService.complete_chat(
                    payload,
                    timeout=45,
                    require_text=require_text
                )

        historical_fallback_attempted = (
            cls._try_historical_comparison_fallback(question, state)
            or cls._try_historical_trend_fallback(question, state)
        )
        if not historical_fallback_attempted and state["tool_errors"]:
            details = "; ".join(dict.fromkeys(state["tool_errors"]))
            raise RuntimeError(
                "No se pudieron obtener resultados climáticos. " + details
            )
        if historical_fallback_attempted:
            state["tool_call_count"] += len(state["results"])
            evidence = [
                cls._model_summary(result)
                for result in state["results"]
            ]
            ask_for_final_answer(
                "La investigación histórica ya se ejecutó con las "
                "herramientas de datos de ClimaIA. Redactá la respuesta "
                "usando exclusivamente esta evidencia; no digas que faltan "
                "resultados ni agregues fuentes externas:\n"
                + json.dumps(evidence, ensure_ascii=False, allow_nan=False)
            )

        while True:
            request_payload = {
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 1000,
                "parallel_tool_calls": False
            }

            if not force_final_answer and tool_rounds < cls.MAX_TOOL_ROUNDS:
                request_payload.update({
                    "tools": tools,
                    "tool_choice": "auto"
                })

            response, provider, model = complete_chat(
                request_payload,
                require_text=force_final_answer
            )

            if not response.choices:
                raise RuntimeError(
                    "Cloudflare no devolvió ninguna respuesta."
                )

            assistant_message = response.choices[0].message
            tool_calls = assistant_message.tool_calls or []
            if force_final_answer and tool_calls:
                raise RuntimeError(
                    "Cloudflare siguió solicitando herramientas después "
                    "de recibir la instrucción de responder."
                )

            # CASO 1: Cloudflare devuelve llamadas estructuradas.
            if tool_calls:
                print(
                    f"[ClimaIA] Ronda {tool_rounds + 1} | "
                    f"Herramientas solicitadas: "
                    f"{[call.function.name for call in tool_calls]}"
                )
                messages.append(
                    cls._assistant_tool_message(assistant_message)
                )

                tool_rounds += 1

                repeated_call = False
                for tool_call in tool_calls:
                    state["tool_call_count"] += 1

                    if state["tool_call_count"] > cls.MAX_TOOL_CALLS:
                        raise RuntimeError(
                            "La investigación solicitó demasiadas "
                            "operaciones. Acotá la consulta."
                        )

                    name = tool_call.function.name
                    tool_call_id = tool_call.id

                    if not isinstance(name, str) or not name:
                        raise RuntimeError(
                            "La IA incluyó una herramienta inválida."
                        )

                    if not isinstance(tool_call_id, str) or not tool_call_id:
                        raise RuntimeError(
                            "La IA incluyó una llamada a herramienta inválida."
                        )

                    try:
                        arguments = json.loads(
                            tool_call.function.arguments or "{}"
                        )

                        if not isinstance(arguments, dict):
                            raise ValueError(
                                "Los argumentos de la herramienta "
                                "no son válidos."
                            )

                        tool_result, was_repeated = execute_tool(
                            name, arguments
                        )
                        repeated_call = repeated_call or was_repeated

                    except (json.JSONDecodeError, TypeError, ValueError) as error:
                        tool_result = {"error": str(error)}

                    except RuntimeError as error:
                        tool_result = {"error": str(error)}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": name,
                        "content": json.dumps(
                            tool_result,
                            ensure_ascii=False,
                            allow_nan=False
                        )
                    })

                if repeated_call:
                    ask_for_final_answer(
                        "Ya ejecutaste una o más de esas herramientas con "
                        "los mismos argumentos y sus resultados están "
                        "incluidos arriba. No vuelvas a llamar herramientas; "
                        "respondé ahora usando esos resultados."
                    )
                elif tool_rounds >= cls.MAX_TOOL_ROUNDS:
                    ask_for_final_answer(
                        "Se alcanzó el límite de operaciones. No solicites "
                        "más herramientas; respondé ahora con los resultados "
                        "ya disponibles y aclarales las limitaciones."
                    )

                continue

            # CASO 2: Cloudflare devuelve el llamado a la herramienta
            # como texto JSON en lugar de usar tool_calls.
            answer = assistant_message.content or ""

            if isinstance(answer, str) and not force_final_answer:
                text_call = cls._text_tool_call(answer)
            else:
                text_call = None

            if text_call is not None:
                print(
                    f"[ClimaIA] Ronda {tool_rounds + 1} | "
                    f"Herramienta textual: {text_call['name']} | "
                    f"Argumentos: {text_call['arguments']}"
                )
                if tool_rounds >= cls.MAX_TOOL_ROUNDS:
                    raise RuntimeError(
                        "La investigación superó el límite de operaciones."
                    )

                tool_rounds += 1
                state["tool_call_count"] += 1

                if state["tool_call_count"] > cls.MAX_TOOL_CALLS:
                    raise RuntimeError(
                        "La investigación solicitó demasiadas "
                        "operaciones. Acotá la consulta."
                    )

                name = text_call["name"]
                arguments = text_call["arguments"]
                tool_call_id = f"text_call_{tool_rounds}"

                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(
                                arguments,
                                ensure_ascii=False
                            )
                        }
                    }]
                })

                tool_result, was_repeated = execute_tool(name, arguments)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": name,
                    "content": json.dumps(
                        tool_result,
                        ensure_ascii=False,
                        allow_nan=False
                    )
                })

                if was_repeated:
                    ask_for_final_answer(
                        "Ya ejecutaste esta herramienta con los mismos "
                        "argumentos y su resultado está incluido arriba. "
                        "No vuelvas a llamar herramientas; respondé ahora "
                        "usando ese resultado."
                    )
                elif tool_rounds >= cls.MAX_TOOL_ROUNDS:
                    ask_for_final_answer(
                        "Se alcanzó el límite de operaciones. No solicites "
                        "más herramientas; respondé ahora con los resultados "
                        "ya disponibles y aclarales las limitaciones."
                    )

                continue

            if (
                force_final_answer
                and isinstance(answer, str)
                and cls._text_tool_call(answer) is not None
            ):
                raise RuntimeError(
                    "Cloudflare siguió solicitando herramientas después "
                    "de recibir la instrucción de responder."
                )

            # CASO 3: La IA devuelve una respuesta normal.
            if not isinstance(answer, str) or not answer.strip():
                raise RuntimeError(
                    f"{provider} respondió sin texto para la investigación."
                )

            if not state["results"]:
                if (
                    not historical_fallback_attempted
                    and (
                        cls._try_historical_comparison_fallback(
                            question,
                            state
                        )
                        or cls._try_historical_trend_fallback(
                            question,
                            state
                        )
                    )
                ):
                    historical_fallback_attempted = True
                    state["tool_call_count"] += len(state["results"])
                    evidence = [
                        cls._model_summary(result)
                        for result in state["results"]
                    ]
                    ask_for_final_answer(
                        "La investigación histórica ya se ejecutó con las "
                        "herramientas de datos de ClimaIA. Redactá la "
                        "respuesta usando exclusivamente esta evidencia; no "
                        "digas que faltan resultados ni agregues fuentes "
                        "externas:\n"
                        + json.dumps(
                            evidence,
                            ensure_ascii=False,
                            allow_nan=False
                        )
                    )
                    continue
                if state["tool_errors"]:
                    details = "; ".join(dict.fromkeys(state["tool_errors"]))
                    raise RuntimeError(
                        "No se pudieron obtener resultados climáticos. "
                        + details
                    )
                raise RuntimeError(
                    "La IA terminó sin ejecutar herramientas que generaran "
                    "resultados climáticos."
                )

            if cls._claims_missing_evidence(answer):
                answer = cls._format_evidence_answer(state["results"])

            return {
                "answer": answer.strip(),
                "results": state["results"],
                "locations_used": list(
                    state["locations_used"].values()
                ),
                "saved": state["saved"],
                "tool_call_count": state["tool_call_count"],
                "provider": provider,
                "model": model
            }
        
    @classmethod
    def _try_historical_comparison_fallback(cls, question, state):
        normalized = unicodedata.normalize("NFD", question.lower())
        normalized = "".join(
            character
            for character in normalized
            if unicodedata.category(character) != "Mn"
        )
        if "compar" not in normalized:
            return False

        year_range = re.search(
            r"\b((?:19|20)\d{2})\s*(?:a|hasta|y|-)\s*"
            r"((?:19|20)\d{2})\b",
            normalized
        )
        if not year_range:
            return False
        start_year, end_year = map(int, year_range.groups())
        today = date.today()
        if start_year > end_year or start_year > today.year:
            return False
        start_date = date(start_year, 1, 1)
        end_date = (
            today
            if end_year == today.year
            else date(end_year, 12, 31)
        )

        variables = []
        if re.search(r"\btemperatur\w*", normalized):
            variables.append("temperature_mean")
        if re.search(r"\b(?:precipit\w*|lluvia\w*)", normalized):
            variables.append("precipitation")
        if not variables:
            return False

        range_start = year_range.start()
        prefix = normalized[:range_start]
        connectors = list(re.finditer(r"\b(?:de|en)\s+", prefix))
        if not connectors:
            return False
        locations_text = re.sub(
            r"\s+(?:entre|between)\s*$",
            "",
            prefix[connectors[-1].end():].strip()
        )
        location_parts = [
            item.strip()
            for item in re.split(
                r"\s*,\s*|\s+(?:y|e)\s+",
                locations_text
            )
            if item.strip()
        ]
        if len(location_parts) < 2:
            return False

        explicit_country_code = country_code_for_name(location_parts[-1])
        explicit_country_name = None
        if explicit_country_code:
            explicit_country_name = location_parts.pop()
        if len(location_parts) < 2:
            return False

        try:
            candidates_by_location = []
            for name in location_parts:
                query = name
                if explicit_country_code:
                    query = f"{name}, {explicit_country_name}"
                candidates = LocationService.search_locations(
                    query,
                    limit=10
                )
                if not candidates:
                    state["tool_errors"].append(
                        f"search_locations: no se encontró {name}."
                    )
                    return False
                candidates_by_location.append(candidates)

            if explicit_country_code:
                shared_country_code = explicit_country_code
            else:
                common_country_codes = set(
                    item["country_code"]
                    for item in candidates_by_location[0]
                )
                for candidates in candidates_by_location[1:]:
                    common_country_codes.intersection_update(
                        item["country_code"]
                        for item in candidates
                    )
                if len(common_country_codes) != 1:
                    state["tool_errors"].append(
                        "search_locations: las localidades no identifican "
                        "un país común de forma inequívoca."
                    )
                    return False
                shared_country_code = common_country_codes.pop()

            locations = []
            for candidates in candidates_by_location:
                location = next(
                    (
                        item for item in candidates
                        if item["country_code"] == shared_country_code
                    ),
                    None
                )
                if location is None:
                    return False
                locations.append(location)

            fallback_state = {
                "results": [],
                "result_index": {},
                "locations_used": {}
            }
            arguments = {
                "geoname_ids": [
                    item["geoname_id"] for item in locations
                ],
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            }
            for variable in variables:
                cls._compare_locations(
                    {**arguments, "variable": variable},
                    fallback_state
                )
        except (RuntimeError, ValueError, KeyError) as error:
            state["tool_errors"].append(
                f"compare_locations: {error}"
            )
            return False

        state["results"].extend(fallback_state["results"])
        state["result_index"].update(fallback_state["result_index"])
        state["locations_used"].update(fallback_state["locations_used"])
        return bool(fallback_state["results"])

    @classmethod
    def _try_historical_trend_fallback(cls, question, state):
        normalized = unicodedata.normalize("NFD", question.lower())
        normalized = "".join(
            character
            for character in normalized
            if unicodedata.category(character) != "Mn"
        )
        if not any(term in normalized for term in (
            "histor", "evolucion", "tendenc"
        )):
            return False

        variables = []
        if re.search(r"\btemperatur\w*", normalized):
            variables.append("temperature_mean")
        if re.search(r"\b(?:precipit\w*|lluvia\w*)", normalized):
            variables.append("precipitation")
        if not variables:
            return False

        year_range = re.search(
            r"\b((?:19|20)\d{2})\s*(?:a|hasta|y|-)\s*"
            r"((?:19|20)\d{2})\b",
            normalized
        )
        if year_range:
            start_year, end_year = map(int, year_range.groups())
        else:
            years_ago = re.search(
                r"\bultimos\s+(\d{1,2})\s+anos\b",
                normalized
            )
            if not years_ago:
                return False
            year_count = int(years_ago.group(1))
            if year_count < 1:
                return False
            end_year = date.today().year - 1
            start_year = end_year - year_count + 1

        today = date.today()
        if start_year > end_year or start_year > today.year:
            return False
        end_date = (
            today
            if end_year == today.year
            else date(end_year, 12, 31)
        )
        start_date = date(start_year, 1, 1)

        commas = list(re.finditer(",", normalized))
        if len(commas) != 1:
            return False
        comma = commas[0].start()
        prefix = normalized[:comma]
        connectors = list(re.finditer(r"\b(?:de|en)\s+", prefix))
        if not connectors:
            return False
        city = prefix[connectors[-1].end():].strip()
        country = re.split(
            r"\s+(?:durante|entre|para|con|usando|en)\b",
            normalized[comma + 1:],
            maxsplit=1
        )[0].strip()
        if not city or not country:
            return False

        try:
            locations = LocationService.search_locations(
                f"{city}, {country}",
                limit=1
            )
            if not locations:
                state["tool_errors"].append(
                    f"search_locations: no se encontró {city}, {country}."
                )
                return False

            location = locations[0]
            fallback_state = {
                "results": [],
                "result_index": {},
                "locations_used": {}
            }
            for variable in variables:
                cls._analyze_climate_trends(
                    {
                        "geoname_id": location["geoname_id"],
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "variable": variable
                    },
                    fallback_state
                )
        except (RuntimeError, ValueError, KeyError) as error:
            state["tool_errors"].append(
                f"analyze_climate_trends: {error}"
            )
            return False

        state["results"].extend(fallback_state["results"])
        state["result_index"].update(fallback_state["result_index"])
        state["locations_used"].update(fallback_state["locations_used"])
        return bool(fallback_state["results"])

    @staticmethod
    def _claims_missing_evidence(answer):
        normalized = unicodedata.normalize("NFD", answer.lower())
        normalized = "".join(
            character
            for character in normalized
            if unicodedata.category(character) != "Mn"
        )
        return any(phrase in normalized for phrase in (
            "no tengo resultados",
            "no hay resultados",
            "no tengo acceso",
            "no puedo acceder a",
            "no he podido acceder",
            "sin acceso",
            "sin datos disponibles",
            "no cuento con datos"
        ))

    @staticmethod
    def _format_evidence_answer(results):
        sections = ["## Resultados basados en los datos consultados"]
        for result in results:
            title = result.get("title") or "Resultado climático"
            sections.append(f"### {title}")
            period = result.get("period")
            if isinstance(period, dict):
                start = period.get("start")
                end = period.get("end")
                if start and end:
                    sections.append(f"Período: {start} a {end}.")

            trend = result.get("trend")
            if isinstance(trend, dict):
                sections.append(
                    "Tendencia lineal descriptiva: "
                    f"{trend.get('slope_per_decade')} "
                    f"{trend.get('unit')} por década "
                    f"(R²={trend.get('r_squared')}); "
                    f"{trend.get('method', 'método no especificado')}."
                )
            elif result.get("summary"):
                sections.append(result["summary"])

            statistics = result.get("statistics")
            if isinstance(statistics, dict) and statistics.get(
                "sample_count"
            ) is not None:
                sections.append(
                    f"Registros válidos: {statistics['sample_count']}."
                )

            source = result.get("source")
            if source:
                sections.append(f"Fuente: {source}.")
            if result.get("warning"):
                sections.append(f"Advertencia: {result['warning']}")

            table = result.get("table")
            if (
                result.get("type") == "location_comparison"
                and isinstance(table, dict)
                and table.get("columns")
                and table.get("rows")
            ):
                columns = table["columns"]
                rows = table["rows"]
                sections.append(
                    "| " + " | ".join(str(item) for item in columns) + " |"
                )
                sections.append(
                    "| " + " | ".join("---" for _ in columns) + " |"
                )
                for row in rows:
                    sections.append(
                        "| "
                        + " | ".join(
                            str(item) if item is not None else "-"
                            for item in row
                        )
                        + " |"
                    )

        sections.append(
            "Limitación: las pendientes describen los valores anuales "
            "observados; no demuestran causalidad ni son una predicción."
        )
        return "\n\n".join(sections)

    @staticmethod
    def _text_tool_call(content):
        """
        Detecta llamadas a herramientas que el modelo devuelve
        como JSON dentro del texto, en lugar de tool_calls.
        """

        if not isinstance(content, str):
            return None

        decoder = json.JSONDecoder()

        available_tools = {
            item["function"]["name"]
            for item in ResearchAgentService.TOOLS
        }

        # Buscar también la herramienta de guardado.
        available_tools.add("save_research")

        for index, character in enumerate(content):
            if character != "{":
                continue

            try:
                data, _ = decoder.raw_decode(content[index:])
            except json.JSONDecodeError:
                continue

            if not isinstance(data, dict):
                continue

            name = data.get("name")
            arguments = data.get("parameters")

            if not isinstance(name, str):
                continue

            if name not in available_tools:
                continue

            if not isinstance(arguments, dict):
                continue

            # No permitir guardar si el usuario no lo solicitó.
            if name == "save_research":
                continue

            arguments = dict(arguments)

            # Convertir números que algunos modelos devuelven como texto.
            for key in ("limit", "geoname_id"):
                value = arguments.get(key)

                if isinstance(value, str) and value.isdigit():
                    arguments[key] = int(value)

            # Convertir los identificadores de localidades.
            if isinstance(arguments.get("geoname_ids"), list):
                arguments["geoname_ids"] = [
                    int(value)
                    if isinstance(value, str) and value.isdigit()
                    else value
                    for value in arguments["geoname_ids"]
                ]

            return {
                "name": name,
                "arguments": arguments
            }

        return None

    @staticmethod
    def _assistant_tool_message(message):
        assistant_message = {
            "role": "assistant",
            "content": (
                message.content
                if isinstance(message.content, str)
                else ""
            ),
            "tool_calls": []
        }

        for call in message.tool_calls or []:
            assistant_message["tool_calls"].append({
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments
                }
            })

        return assistant_message
    
    @classmethod
    def _dispatch_tool(cls, name, arguments, state):
        handlers = {
            "search_locations": cls._search_locations,
            "get_historical_records": cls._get_historical_records,
            "get_location_climate_profile": cls._get_location_climate_profile,
            "compare_locations": cls._compare_locations,
            "compare_periods": cls._compare_periods,
            "find_similar_climates": cls._find_similar_climates,
            "calculate_climate_statistics": cls._calculate_climate_statistics,
            "analyze_climate_trends": cls._analyze_climate_trends,
            "detect_climate_patterns": cls._detect_climate_patterns,
            "generate_research_chart": cls._generate_research_chart,
            "generate_comparison_table": cls._generate_comparison_table,
            "save_research": cls._save_research
        }
        handler = handlers.get(name)
        if handler is None:
            raise ValueError("La herramienta solicitada no está disponible.")
        return handler(arguments, state)

    @staticmethod
    def _user_requested_save(question):
        normalized = unicodedata.normalize("NFD", question.lower())
        normalized = "".join(
            character
            for character in normalized
            if unicodedata.category(character) != "Mn"
        )
        if re.search(r"\bno\s+(?:la\s+)?(?:guardes|guardemos|guardar)\b", normalized):
            return False
        return bool(
            re.search(
                r"\b(guardar|guarda|guardame|guardemos|conservar|archivar)\b",
                normalized
            )
        )

    @staticmethod
    def _positive_integer(value, label, maximum=None):
        if type(value) is not int or value < 1:
            raise ValueError(f"{label} debe ser un entero positivo.")
        if maximum is not None and value > maximum:
            raise ValueError(f"{label} supera el límite permitido.")
        return value

    @classmethod
    def _validate_period(cls, start_value, end_value):
        try:
            start = date.fromisoformat(str(start_value))
            end = date.fromisoformat(str(end_value))
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Las fechas deben tener el formato YYYY-MM-DD."
            ) from error

        if start < date(1940, 1, 1):
            raise ValueError(
                "El archivo histórico está disponible desde 1940."
            )
        if start > end:
            raise ValueError(
                "La fecha inicial no puede ser posterior a la fecha final."
            )
        if end > date.today():
            raise ValueError("La fecha final no puede estar en el futuro.")
        if (end - start).days > cls.MAX_PERIOD_YEARS * 366:
            raise ValueError(
                "El período supera el máximo de 50 años por consulta."
            )
        return start, end

    @classmethod
    def _variable(cls, key):
        variable = cls.VARIABLES.get(key)
        if variable is None:
            raise ValueError("La variable climática no está disponible.")
        return variable

    @staticmethod
    def _get_location(geoname_id):
        geoname_id = ResearchAgentService._positive_integer(
            geoname_id,
            "El identificador de localidad"
        )
        location = Location.query.filter_by(
            geoname_id=geoname_id
        ).first()
        if location is None:
            raise ValueError(
                "La localidad no existe en el catálogo de ClimaIA."
            )
        return location

    @staticmethod
    def _location_data(location):
        return LocationService._serialize_location(location)

    @staticmethod
    def _display_location(location):
        display_name = location.get("display_name")
        if display_name:
            return display_name
        name = location.get("name") or "Localidad"
        country = location.get("country_name") or location.get("country")
        return f"{name}, {country}" if country else name

    @classmethod
    def _search_locations(cls, arguments, state):
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Ingresá un nombre de localidad para buscar.")
        limit = arguments.get("limit", 5)
        if isinstance(limit, str) and limit.strip().isdigit():
            limit = int(limit.strip())
        warning = None
        if type(limit) is not int or not 1 <= limit <= 10:
            limit = 5
            warning = (
                "La IA envió un límite de búsqueda inválido; "
                "se usaron los 5 resultados predeterminados."
            )
        result = {
            "locations": LocationService.search_locations(
                query.strip(),
                limit=limit
            )
        }
        if warning:
            result["warning"] = warning
        return result

    @classmethod
    def _get_daily_records(
        cls,
        location,
        start,
        end,
        required_variables=None
    ):
        query = (
            WeatherRecord.query
            .filter(
                WeatherRecord.location_id == location.id,
                WeatherRecord.record_date >= start,
                WeatherRecord.record_date <= end
            )
            .order_by(WeatherRecord.record_date.asc())
        )
        stored_records = query.all()
        stored_normalized = [
            {
                "date": record.record_date.isoformat(),
                "temperature_mean": record.temperature_mean,
                "temperature_max": record.temperature_max,
                "temperature_min": record.temperature_min,
                "precipitation": record.precipitation_sum,
                "wind_speed_max": record.wind_speed_max,
                "sunshine_duration": record.sunshine_duration
            }
            for record in stored_records
        ]
        expected_days = (end - start).days + 1
        variables = required_variables or ["temperature_mean"]
        stored_is_sufficient = bool(stored_normalized) and all(
            sum(
                record.get(variable) is not None
                for record in stored_normalized
            ) >= max(1, int(expected_days * 0.8))
            for variable in variables
        )
        if stored_is_sufficient:
            return {
                "records": stored_normalized,
                "source": "Registros meteorológicos almacenados en ClimaIA",
                "warning": None,
                "units": {}
            }

        try:
            historical = WeatherService.get_historical_series(
                latitude=float(location.latitude),
                longitude=float(location.longitude),
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                timezone=location.timezone or "auto"
            )
            records = historical.get("records", [])
            if not records:
                raise ValueError(
                    "El archivo histórico no devolvió registros."
                )
            return {
                "records": records,
                "source": "Open-Meteo Historical Weather API · ERA5",
                "warning": None,
                "units": historical.get("units", {})
            }
        except (RuntimeError, ValueError) as error:
            if stored_normalized:
                return {
                    "records": stored_normalized,
                    "source": "Registros meteorológicos almacenados en ClimaIA",
                    "warning": (
                        "El conjunto local está incompleto; se utilizó la "
                        "cobertura existente porque el archivo externo falló: "
                        + str(error)
                    ),
                    "units": {}
                }
            raise RuntimeError(
                "No hay registros locales suficientes y el archivo histórico "
                f"no está disponible: {error}"
            ) from error

    @classmethod
    def _get_cached_daily_records(
        cls,
        state,
        location,
        start,
        end,
        required_variables
    ):
        cache = state.setdefault("_daily_records_cache", {})
        cache_key = (location.id, start, end)
        cached = cache.get(cache_key)
        expected_days = (end - start).days + 1
        if cached and all(
            sum(
                record.get(
                    cls.VARIABLES[variable]["external_field"]
                ) is not None
                for record in cached["records"]
            ) >= max(1, int(expected_days * 0.8))
            for variable in required_variables
        ):
            return cached

        loaded = cls._get_daily_records(
            location,
            start,
            end,
            required_variables
        )
        cache[cache_key] = loaded
        return loaded

    @staticmethod
    def _series_value(record, variable_key):
        return record.get(
            ResearchAgentService.VARIABLES[variable_key]["external_field"]
        )

    @staticmethod
    def _round(value, digits=2):
        return round(float(value), digits)

    @classmethod
    def _aggregate_records(
        cls,
        records,
        variable_key,
        aggregation
    ):
        if aggregation not in ("annual", "monthly", "daily"):
            raise ValueError("La escala temporal solicitada no es válida.")
        groups = {}
        for record in records:
            value = cls._series_value(record, variable_key)
            record_date = record.get("date")
            if value is None or not record_date:
                continue
            try:
                parsed_date = date.fromisoformat(record_date)
            except (TypeError, ValueError):
                continue

            if aggregation == "annual":
                key = str(parsed_date.year)
            elif aggregation == "monthly":
                key = f"{parsed_date.year:04d}-{parsed_date.month:02d}"
            else:
                key = parsed_date.isoformat()
            groups.setdefault(key, []).append(float(value))

        series = []
        for key in sorted(groups):
            values = groups[key]
            if cls.VARIABLES[variable_key]["aggregation"] == "sum":
                aggregate = sum(values)
            else:
                aggregate = sum(values) / len(values)
            series.append({
                "period": key,
                "value": cls._round(aggregate),
                "sample_count": len(values)
            })
        if not series:
            raise ValueError(
                "No hay registros válidos para la variable y el período."
            )
        return series

    @classmethod
    def _statistics(cls, records, variable_key):
        values = [
            float(value)
            for value in (
                cls._series_value(record, variable_key)
                for record in records
            )
            if value is not None
        ]
        if not values:
            raise ValueError(
                "No hay datos válidos para calcular estadísticas."
            )
        statistics = {
            "sample_count": len(values),
            "mean": cls._round(sum(values) / len(values)),
            "minimum": cls._round(min(values)),
            "maximum": cls._round(max(values))
        }
        if variable_key == "precipitation":
            statistics["accumulated_total"] = cls._round(sum(values))
        return statistics

    @staticmethod
    def _period_label(value, aggregation):
        if aggregation == "monthly":
            year, month = value.split("-")
            month_name = (
                "ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic"
            )[int(month) - 1]
            return f"{month_name} {year}"
        return value

    @classmethod
    def _base_result(
        cls,
        state,
        result_type,
        title,
        summary,
        source,
        period,
        locations,
        chart=None,
        charts=None,
        table=None,
        **extra
    ):
        result_id = f"R{len(state['results']) + 1}"
        tracked = []
        for location in locations:
            if not location:
                continue
            item = {
                "geoname_id": location.get("geoname_id"),
                "name": location.get("name"),
                "country_name": location.get("country_name")
                or location.get("country")
            }
            if item["geoname_id"] is not None:
                state["locations_used"][str(item["geoname_id"])] = item
            tracked.append(item)

        result = {
            "result_id": result_id,
            "type": result_type,
            "title": title,
            "summary": summary,
            "source": source,
            "period": period,
            "locations": tracked,
            "chart": chart,
            "charts": charts or [],
            "table": table,
            **extra
        }
        state["results"].append(result)
        state["result_index"][result_id] = result
        return result

    @classmethod
    def _model_summary(cls, result):
        fields = (
            "result_id",
            "type",
            "title",
            "summary",
            "source",
            "period",
            "locations",
            "statistics",
            "trend",
            "patterns",
            "correlation",
            "coverage",
            "warning"
        )
        return {
            key: result[key]
            for key in fields
            if key in result and result[key] is not None
        }

    @classmethod
    def _get_historical_result(
        cls,
        state,
        geoname_id,
        start_date,
        end_date,
        variable_key,
        aggregation
    ):
        location = cls._get_location(geoname_id)
        start, end = cls._validate_period(start_date, end_date)
        variable = cls._variable(variable_key)
        if aggregation == "daily" and (end - start).days + 1 > cls.MAX_DAILY_DAYS:
            raise ValueError(
                "La escala diaria está limitada a 90 días por consulta."
            )
        loaded = cls._get_cached_daily_records(
            state,
            location,
            start,
            end,
            [variable_key]
        )
        series = cls._aggregate_records(
            loaded["records"],
            variable_key,
            aggregation
        )
        labels = [
            cls._period_label(item["period"], aggregation)
            for item in series
        ]
        values = [item["value"] for item in series]
        stats = cls._statistics(loaded["records"], variable_key)
        location_data = cls._location_data(location)
        warnings = [
            loaded["warning"]
        ] if loaded["warning"] else []
        if len(loaded["records"]) < (end - start).days * 0.8:
            warnings.append(
                "El período contiene menos registros que días solicitados."
            )

        chart = {
            "type": "line",
            "title": f"{variable['label']} · {location_data['display_name']}",
            "labels": labels,
            "datasets": [{
                "label": variable["label"],
                "unit": variable["unit"],
                "data": values
            }]
        }
        table = {
            "columns": ["Período", variable["label"], "Registros"],
            "rows": [
                [labels[index], values[index], series[index]["sample_count"]]
                for index in range(len(series))
            ]
        }
        return cls._base_result(
            state,
            "historical_series",
            f"{variable['label']} · {location_data['display_name']}",
            (
                f"Serie {aggregation} de {variable['label'].lower()} para "
                f"{location_data['display_name']} entre {start.isoformat()} "
                f"y {end.isoformat()}. Se agregaron {stats['sample_count']} "
                "registros diarios válidos."
            ),
            loaded["source"],
            {"start": start.isoformat(), "end": end.isoformat()},
            [location_data],
            chart=chart,
            table=table,
            variable=variable_key,
            unit=variable["unit"],
            aggregation=aggregation,
            series=series,
            statistics=stats,
            coverage={
                "records": stats["sample_count"],
                "expected_days": (end - start).days + 1
            },
            warning=" ".join(warnings) if warnings else None
        )

    @classmethod
    def _get_historical_records(cls, arguments, state):
        aggregation = arguments.get("aggregation", "annual")
        result = cls._get_historical_result(
            state,
            arguments.get("geoname_id"),
            arguments.get("start_date"),
            arguments.get("end_date"),
            arguments.get("variable"),
            aggregation
        )
        return cls._model_summary(result)

    @classmethod
    def _calculate_climate_statistics(cls, arguments, state):
        result = cls._get_historical_result(
            state,
            arguments.get("geoname_id"),
            arguments.get("start_date"),
            arguments.get("end_date"),
            arguments.get("variable"),
            "annual"
        )
        result["type"] = "statistics"
        result["title"] = "Estadísticas · " + result["title"]
        result["summary"] += (
            " Las estadísticas se calcularon sobre los registros diarios "
            "disponibles; la serie se muestra agregada por año."
        )
        return cls._model_summary(result)

    @classmethod
    def _get_location_climate_profile(cls, arguments, state):
        location = cls._get_location(arguments.get("geoname_id"))
        start_value = arguments.get("start_date", "1991-01-01")
        end_value = arguments.get("end_date", "2020-12-31")
        start, end = cls._validate_period(start_value, end_value)

        if start == SimilarityService.REFERENCE_START and end == SimilarityService.REFERENCE_END:
            stored = SimilarityService._get_or_create_stored_profile(location)
            profile = SimilarityService._stored_profile_to_dict(stored)
            profile_source = (
                f"{stored.dataset_code} · perfil almacenado en ClimaIA"
            )
            monthly_profile = profile.get("monthly_profile", [])
            period = profile.get("period", {})
            statistics = stored.summary_statistics
        else:
            profile = WeatherService.get_climate_profile(
                latitude=float(location.latitude),
                longitude=float(location.longitude),
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                timezone=location.timezone or "auto"
            )
            profile_source = "Open-Meteo Historical Weather API · ERA5"
            monthly_profile = profile.get("monthly_profile", [])
            period = profile.get("period", {})
            statistics = profile.get("general_statistics", {})

        location_data = cls._location_data(location)
        monthly = sorted(
            monthly_profile,
            key=lambda item: item.get("month", 0)
        )
        temperature = [
            item.get("temperature_mean")
            for item in monthly
        ]
        precipitation = [
            item.get("precipitation_mean_daily")
            for item in monthly
        ]
        month_labels = [
            item.get("name") or str(item.get("month"))
            for item in monthly
        ]
        charts = [
            {
                "type": "line",
                "title": "Temperatura media mensual",
                "labels": month_labels,
                "datasets": [{
                    "label": "Temperatura media",
                    "unit": "°C",
                    "data": temperature
                }]
            },
            {
                "type": "bar",
                "title": "Precipitación media diaria por mes",
                "labels": month_labels,
                "datasets": [{
                    "label": "Precipitación media diaria",
                    "unit": "mm/día",
                    "data": precipitation
                }]
            }
        ]
        table = {
            "columns": [
                "Mes",
                "Temperatura media (°C)",
                "Precipitación media diaria (mm)"
            ],
            "rows": [
                [
                    month_labels[index],
                    temperature[index],
                    precipitation[index]
                ]
                for index in range(len(monthly))
            ]
        }
        result = cls._base_result(
            state,
            "climate_profile",
            f"Perfil climático · {location_data['display_name']}",
            (
                f"Perfil mensual de {location_data['display_name']} para "
                f"{period.get('start', start.isoformat())}–"
                f"{period.get('end', end.isoformat())}."
            ),
            profile_source,
            period,
            [location_data],
            charts=charts,
            table=table,
            monthly_profile=monthly,
            statistics=statistics
        )
        return cls._model_summary(result)

    @classmethod
    def _compare_locations(cls, arguments, state):
        geoname_ids = arguments.get("geoname_ids")
        if not isinstance(geoname_ids, list) or not 2 <= len(geoname_ids) <= cls.MAX_LOCATIONS:
            raise ValueError("Compará entre dos y cinco localidades.")
        if len(set(geoname_ids)) != len(geoname_ids):
            raise ValueError("No repitas localidades en la comparación.")
        start, end = cls._validate_period(
            arguments.get("start_date"),
            arguments.get("end_date")
        )
        variable_key = arguments.get("variable")
        variable = cls._variable(variable_key)

        locations = []
        series_by_location = []
        summaries = []
        sources = []
        for geoname_id in geoname_ids:
            location = cls._get_location(geoname_id)
            loaded = cls._get_cached_daily_records(
                state,
                location,
                start,
                end,
                [variable_key]
            )
            annual = cls._aggregate_records(
                loaded["records"],
                variable_key,
                "annual"
            )
            location_data = cls._location_data(location)
            values = [item["value"] for item in annual]
            labels = [item["period"] for item in annual]
            series_by_location.append({
                "name": location_data["display_name"],
                "labels": labels,
                "data": values
            })
            summaries.append({
                "location": location_data["display_name"],
                "mean_of_annual_values": cls._round(
                    sum(values) / len(values)
                ),
                "minimum_annual_value": min(values),
                "maximum_annual_value": max(values),
                "years": len(values),
                "source": loaded["source"]
            })
            locations.append(location_data)
            sources.append(loaded["source"])

        all_years = sorted({
            label
            for item in series_by_location
            for label in item["labels"]
        })
        datasets = []
        for item in series_by_location:
            data_by_year = dict(zip(item["labels"], item["data"]))
            datasets.append({
                "label": item["name"],
                "unit": variable["unit"],
                "data": [data_by_year.get(year) for year in all_years]
            })
        table = {
            "columns": [
                "Localidad",
                f"Promedio anual de {variable['label'].lower()} ({variable['unit']})",
                "Mínimo anual",
                "Máximo anual",
                "Años disponibles",
                "Fuente"
            ],
            "rows": [
                [
                    row["location"],
                    row["mean_of_annual_values"],
                    row["minimum_annual_value"],
                    row["maximum_annual_value"],
                    row["years"],
                    row["source"]
                ]
                for row in summaries
            ]
        }
        result = cls._base_result(
            state,
            "location_comparison",
            f"Comparación de {variable['label'].lower()}",
            (
                f"Se compararon {len(locations)} localidades entre "
                f"{start.isoformat()} y {end.isoformat()}. Los valores de "
                "precipitación son acumulados anuales; los demás son "
                "promedios anuales de registros diarios."
            ),
            "Fuentes indicadas por localidad",
            {"start": start.isoformat(), "end": end.isoformat()},
            locations,
            chart={
                "type": "line",
                "title": f"{variable['label']} · comparación anual",
                "labels": all_years,
                "datasets": datasets
            },
            table=table,
            variable=variable_key,
            unit=variable["unit"],
            aggregation="annual",
            statistics=summaries,
            sources=sorted(set(sources))
        )
        return cls._model_summary(result)

    @classmethod
    def _compare_periods(cls, arguments, state):
        location = cls._get_location(arguments.get("geoname_id"))
        variable_key = arguments.get("variable")
        variable = cls._variable(variable_key)
        periods = [
            cls._validate_period(
                arguments.get("first_start"),
                arguments.get("first_end")
            ),
            cls._validate_period(
                arguments.get("second_start"),
                arguments.get("second_end")
            )
        ]
        location_data = cls._location_data(location)
        summaries = []
        sources = []
        for start, end in periods:
            loaded = cls._get_cached_daily_records(
                state,
                location,
                start,
                end,
                [variable_key]
            )
            annual = cls._aggregate_records(
                loaded["records"],
                variable_key,
                "annual"
            )
            values = [item["value"] for item in annual]
            summaries.append({
                "start": start.isoformat(),
                "end": end.isoformat(),
                "annual_value_mean": cls._round(
                    sum(values) / len(values)
                ),
                "minimum_annual_value": min(values),
                "maximum_annual_value": max(values),
                "years": len(values)
            })
            sources.append(loaded["source"])

        difference = cls._round(
            summaries[1]["annual_value_mean"]
            - summaries[0]["annual_value_mean"]
        )
        first_value = summaries[0]["annual_value_mean"]
        percent_change = None
        if variable_key == "precipitation" and first_value > 0:
            percent_change = cls._round(difference / first_value * 100)
        table = {
            "columns": [
                "Período",
                f"Promedio anual ({variable['unit']})",
                "Mínimo anual",
                "Máximo anual",
                "Años disponibles"
            ],
            "rows": [
                [
                    f"{row['start']} – {row['end']}",
                    row["annual_value_mean"],
                    row["minimum_annual_value"],
                    row["maximum_annual_value"],
                    row["years"]
                ]
                for row in summaries
            ]
        }
        result = cls._base_result(
            state,
            "period_comparison",
            f"Comparación de períodos · {location_data['display_name']}",
            (
                f"La diferencia del segundo período respecto del primero es "
                f"{difference} {variable['unit']} en el promedio de valores "
                "anuales."
            ),
            " · ".join(sorted(set(sources))),
            {
                "first": {
                    "start": periods[0][0].isoformat(),
                    "end": periods[0][1].isoformat()
                },
                "second": {
                    "start": periods[1][0].isoformat(),
                    "end": periods[1][1].isoformat()
                }
            },
            [location_data],
            chart={
                "type": "bar",
                "title": f"{variable['label']} · comparación de períodos",
                "labels": ["Primer período", "Segundo período"],
                "datasets": [{
                    "label": variable["label"],
                    "unit": variable["unit"],
                    "data": [
                        summaries[0]["annual_value_mean"],
                        summaries[1]["annual_value_mean"]
                    ]
                }]
            },
            table=table,
            variable=variable_key,
            unit=variable["unit"],
            statistics={
                "first_period": summaries[0],
                "second_period": summaries[1],
                "absolute_difference": difference,
                "percent_change": percent_change
            }
        )
        return cls._model_summary(result)

    @classmethod
    def _find_similar_climates(cls, arguments, state):
        geoname_id = arguments.get("geoname_id")
        cls._get_location(geoname_id)
        limit = cls._positive_integer(
            arguments.get("limit", 5),
            "El límite",
            maximum=10
        )
        similarity = SimilarityService.find_similar_locations(
            geoname_id=geoname_id,
            limit=limit
        )
        target = similarity["target"]
        matches = similarity.get("results", [])
        if not matches:
            raise ValueError(
                similarity.get("message")
                or "No hay perfiles climáticos comparables almacenados."
            )
        chart = {
            "type": "bar",
            "title": "Distancia climática normalizada",
            "labels": [
                cls._display_location(item["location"])
                for item in matches
            ],
            "datasets": [{
                "label": "Distancia (menor indica mayor similitud)",
                "unit": "índice relativo",
                "data": [
                    item["distance_index"] for item in matches
                ]
            }]
        }
        table = {
            "columns": [
                "Localidad",
                "Distancia normalizada",
                "RMSE temperatura (°C)",
                "RMSE precipitación diaria (mm)"
            ],
            "rows": [
                [
                    cls._display_location(item["location"]),
                    item["distance_index"],
                    item["temperature_rmse"],
                    item["precipitation_rmse"]
                ]
                for item in matches
            ]
        }
        location_data = {
            "geoname_id": target.get("geoname_id"),
            "name": target.get("name"),
            "country_name": target.get("country")
        }
        result = cls._base_result(
            state,
            "similar_locations",
            f"Localidades similares a {target.get('name')}",
            (
                f"Se compararon perfiles mensuales del período "
                f"{similarity['period']['start']}–"
                f"{similarity['period']['end']} mediante distancia "
                "climática normalizada."
            ),
            similarity.get("method"),
            similarity.get("period"),
            [location_data],
            chart=chart,
            table=table,
            matches=matches,
            target=target,
            statistics={
                "count": len(matches),
                "method": similarity.get("method")
            }
        )
        return cls._model_summary(result)

    @classmethod
    def _analyze_climate_trends(cls, arguments, state):
        result = cls._get_historical_result(
            state,
            arguments.get("geoname_id"),
            arguments.get("start_date"),
            arguments.get("end_date"),
            arguments.get("variable"),
            "annual"
        )
        series = result["series"]
        years = [int(item["period"]) for item in series]
        values = [float(item["value"]) for item in series]
        if len(values) < 3:
            raise ValueError(
                "Se necesitan al menos tres años con datos para calcular "
                "una tendencia descriptiva."
            )
        slope, intercept, r_squared = cls._linear_regression(years, values)
        trend_values = [
            cls._round(intercept + slope * year)
            for year in years
        ]
        result["type"] = "trend"
        result["title"] = "Tendencia · " + result["title"]
        result["trend"] = {
            "slope_per_year": cls._round(slope, 4),
            "slope_per_decade": cls._round(slope * 10, 3),
            "unit": result["unit"],
            "r_squared": cls._round(r_squared, 4),
            "method": "Regresión lineal descriptiva sobre valores anuales"
        }
        result["summary"] = (
            f"La pendiente descriptiva es {result['trend']['slope_per_decade']} "
            f"{result['unit']} por década; R²={result['trend']['r_squared']}. "
            "No representa causalidad ni una predicción."
        )
        result["chart"]["datasets"].append({
            "label": "Tendencia lineal descriptiva",
            "unit": result["unit"],
            "data": trend_values
        })
        result["table"]["columns"].append("Tendencia descriptiva")
        for index, row in enumerate(result["table"]["rows"]):
            row.append(trend_values[index])
        return cls._model_summary(result)

    @staticmethod
    def _linear_regression(xs, ys):
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        denominator = sum((x - x_mean) ** 2 for x in xs)
        if denominator == 0:
            raise ValueError("No se puede calcular la tendencia.")
        slope = sum(
            (x - x_mean) * (y - y_mean)
            for x, y in zip(xs, ys)
        ) / denominator
        intercept = y_mean - slope * x_mean
        total = sum((y - y_mean) ** 2 for y in ys)
        residual = sum(
            (y - (intercept + slope * x)) ** 2
            for x, y in zip(xs, ys)
        )
        r_squared = 1 - residual / total if total else 0.0
        return slope, intercept, r_squared

    @classmethod
    def _detect_climate_patterns(cls, arguments, state):
        location = cls._get_location(arguments.get("geoname_id"))
        start, end = cls._validate_period(
            arguments.get("start_date"),
            arguments.get("end_date")
        )
        loaded = cls._get_cached_daily_records(
            state,
            location,
            start,
            end,
            ["temperature_mean", "precipitation"]
        )
        annual_temperature = cls._aggregate_records(
            loaded["records"],
            "temperature_mean",
            "annual"
        )
        annual_precipitation = cls._aggregate_records(
            loaded["records"],
            "precipitation",
            "annual"
        )
        temp_by_year = {
            int(item["period"]): item["value"]
            for item in annual_temperature
        }
        precip_by_year = {
            int(item["period"]): item["value"]
            for item in annual_precipitation
        }
        paired_years = sorted(set(temp_by_year) & set(precip_by_year))
        if len(paired_years) < 3:
            raise ValueError(
                "Se necesitan al menos tres años con temperatura y "
                "precipitación para buscar patrones."
            )
        highest_temperature_years = sorted(
            paired_years,
            key=lambda year: temp_by_year[year],
            reverse=True
        )[:3]
        lowest_precipitation_years = sorted(
            paired_years,
            key=lambda year: precip_by_year[year]
        )[:3]
        temperatures = [temp_by_year[year] for year in paired_years]
        precipitation = [precip_by_year[year] for year in paired_years]
        correlation = cls._pearson(temperatures, precipitation)
        patterns = [
            {
                "name": "Años con mayor temperatura media",
                "years": [
                    {
                        "year": year,
                        "temperature_mean": temp_by_year[year]
                    }
                    for year in highest_temperature_years
                ]
            },
            {
                "name": "Años con menor precipitación acumulada",
                "years": [
                    {
                        "year": year,
                        "precipitation_total": precip_by_year[year]
                    }
                    for year in lowest_precipitation_years
                ]
            }
        ]
        correlation_info = {
            "coefficient": cls._round(correlation, 3)
            if correlation is not None
            else None,
            "paired_years": len(paired_years),
            "interpretation": (
                "Asociación estadística; no demuestra causalidad."
            )
        }
        location_data = cls._location_data(location)
        rows = [
            [
                year,
                temp_by_year[year],
                precip_by_year[year]
            ]
            for year in paired_years
        ]
        result = cls._base_result(
            state,
            "patterns",
            f"Patrones climáticos · {location_data['display_name']}",
            (
                f"Se analizaron {len(paired_years)} años con ambas variables. "
                "Los extremos describen los registros disponibles."
            ),
            loaded["source"],
            {"start": start.isoformat(), "end": end.isoformat()},
            [location_data],
            charts=[
                {
                    "type": "line",
                    "title": "Temperatura media anual",
                    "labels": [str(year) for year in paired_years],
                    "datasets": [{
                        "label": "Temperatura media",
                        "unit": "°C",
                        "data": temperatures
                    }]
                },
                {
                    "type": "line",
                    "title": "Precipitación acumulada anual",
                    "labels": [str(year) for year in paired_years],
                    "datasets": [{
                        "label": "Precipitación",
                        "unit": "mm",
                        "data": precipitation
                    }]
                }
            ],
            table={
                "columns": [
                    "Año",
                    "Temperatura media (°C)",
                    "Precipitación acumulada (mm)"
                ],
                "rows": rows
            },
            patterns=patterns,
            correlation=correlation_info,
            warning=loaded["warning"]
        )
        return cls._model_summary(result)

    @staticmethod
    def _pearson(first, second):
        if len(first) != len(second) or len(first) < 3:
            return None
        first_mean = sum(first) / len(first)
        second_mean = sum(second) / len(second)
        numerator = sum(
            (left - first_mean) * (right - second_mean)
            for left, right in zip(first, second)
        )
        denominator = sqrt(
            sum((left - first_mean) ** 2 for left in first)
            * sum((right - second_mean) ** 2 for right in second)
        )
        return numerator / denominator if denominator else None

    @classmethod
    def _generate_research_chart(cls, arguments, state):
        result = state["result_index"].get(arguments.get("result_id"))
        if result is None:
            raise ValueError(
                "El resultado no pertenece a esta investigación."
            )
        chart_type = arguments.get("chart_type")
        if chart_type not in ("line", "bar"):
            raise ValueError("El tipo de gráfico no está permitido.")
        charts = result.get("charts") or (
            [result["chart"]] if result.get("chart") else []
        )
        if not charts:
            raise ValueError(
                "Este resultado no contiene series aptas para graficar."
            )
        prepared = [
            {**chart, "type": chart_type}
            for chart in charts
        ]
        return {
            "result_id": result["result_id"],
            "charts": prepared,
            "values_from_backend": True
        }

    @classmethod
    def _generate_comparison_table(cls, arguments, state):
        result = state["result_index"].get(arguments.get("result_id"))
        if result is None or not result.get("table"):
            raise ValueError(
                "No hay una tabla real disponible para ese resultado."
            )
        return {
            "result_id": result["result_id"],
            "table": result["table"],
            "values_from_backend": True
        }

    @classmethod
    def _save_research(cls, arguments, state):
        if not state["allow_save"]:
            raise ValueError(
                "Solo se guarda cuando el usuario lo solicita explícitamente."
            )
        investigation = Investigation.query.filter_by(
            id=state["investigation_id"],
            user_id=state["user_id"]
        ).first()
        if investigation is None:
            raise ValueError(
                "No se encontró la investigación de este usuario."
            )
        title = arguments.get("title")
        if not isinstance(title, str) or not title.strip():
            title = state["question"][:180]
        description = arguments.get("description")
        investigation.title = title.strip()[:180]
        if isinstance(description, str):
            investigation.description = description.strip()[:2000]
        investigation.status = "saved"
        db.session.commit()
        state["saved"] = True
        return {
            "saved": True,
            "title": investigation.title
        }
