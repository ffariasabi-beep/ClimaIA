from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from app.services.ai_provider_service import (
    AIProviderError,
    ChatChoice,
    ChatCompletion,
    ChatFunction,
    ChatMessage,
    ChatToolCall
)
from app.services.ai_provider_service import AIProviderService
from app.services.location_service import LocationService
from app.services.research_agent_service import ResearchAgentService


def test_research_agent_uses_the_normalized_provider_response(
    monkeypatch
):
    app = Flask(__name__)
    app.config.update(
        CLOUDFLARE_API_TOKEN="test-cloudflare-token",
        CLOUDFLARE_ACCOUNT_ID="27a213e220bc2df09c1d4d9fc906a7f9",
        CLOUDFLARE_AI_MODEL=(
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        )
    )
    tool_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[ChatToolCall(
                id="call_1",
                function=ChatFunction(
                    name="calculate_climate_statistics",
                    arguments="{}"
                )
            )]
        )
    )])
    answer_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content="Resultado basado en las herramientas."
        )
    )])
    complete_chat = Mock(side_effect=[
        (
            tool_response,
            "Cloudflare Workers AI",
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        ),
        (
            answer_response,
            "Cloudflare Workers AI",
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        )
    ])
    def dispatch_tool(name, arguments, state):
        state["results"].append({
            "result_id": "R1",
            "summary": "Resultado climático de prueba.",
            "source": "Python"
        })
        return {"source": "Python"}

    dispatch = Mock(side_effect=dispatch_tool)
    monkeypatch.setattr(
        AIProviderService,
        "complete_cloudflare_chat",
        complete_chat
    )
    monkeypatch.setattr(
        ResearchAgentService,
        "_dispatch_tool",
        dispatch
    )

    with app.app_context():
        result = ResearchAgentService.run(
            question="Analizá el perfil climático.",
            conversation_history=[],
            investigation_id=1,
            user_id=1
        )

    assert result["answer"] == "Resultado basado en las herramientas."
    assert result["provider"] == "Cloudflare Workers AI"
    assert result["model"] == "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    dispatch.assert_called_once()
    assert dispatch.call_args.args[:2] == (
        "calculate_climate_statistics",
        {}
    )
    assert dispatch.call_args.args[2]["allow_save"] is False
    second_request = complete_chat.call_args_list[1]
    assert second_request.args[0]["messages"][-2]["role"] == "assistant"
    assert second_request.args[0]["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "name": "calculate_climate_statistics",
        "content": "{\"source\": \"Python\"}"
    }


def test_text_tool_call_uses_standard_tool_result_messages(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        CLOUDFLARE_API_TOKEN="test-cloudflare-token",
        CLOUDFLARE_ACCOUNT_ID="27a213e220bc2df09c1d4d9fc906a7f9",
        CLOUDFLARE_AI_MODEL="@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )
    tool_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content=(
                '{"name":"search_locations",'
                '"parameters":{"query":"Córdoba"}}'
            )
        )
    )])
    answer_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content="Encontré la localidad solicitada."
        )
    )])
    complete_chat = Mock(side_effect=[
        (
            tool_response,
            "Cloudflare Workers AI",
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        ),
        (
            answer_response,
            "Cloudflare Workers AI",
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        )
    ])
    def dispatch_tool(name, arguments, state):
        state["results"].append({
            "result_id": "R1",
            "summary": "Localidad de prueba encontrada."
        })
        return {"locations": [{"name": "Córdoba"}]}

    dispatch = Mock(side_effect=dispatch_tool)
    monkeypatch.setattr(
        AIProviderService,
        "complete_cloudflare_chat",
        complete_chat
    )
    monkeypatch.setattr(
        ResearchAgentService,
        "_dispatch_tool",
        dispatch
    )

    with app.app_context():
        result = ResearchAgentService.run(
            question="Buscá Córdoba.",
            conversation_history=[],
            investigation_id=1,
            user_id=1
        )

    assert result["answer"] == "Encontré la localidad solicitada."
    assert dispatch.call_args.args[:2] == (
        "search_locations",
        {"query": "Córdoba"}
    )
    messages = complete_chat.call_args_list[1].args[0]["messages"]
    assert messages[-2] == {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "text_call_1",
            "type": "function",
            "function": {
                "name": "search_locations",
                "arguments": "{\"query\": \"Córdoba\"}"
            }
        }]
    }
    assert messages[-1] == {
        "role": "tool",
        "tool_call_id": "text_call_1",
        "name": "search_locations",
        "content": "{\"locations\": [{\"name\": \"Córdoba\"}]}"
    }


def test_repeated_tool_call_is_not_executed_again_and_forces_final_answer(
    monkeypatch
):
    app = Flask(__name__)
    app.config.update(
        CLOUDFLARE_API_TOKEN="test-cloudflare-token",
        CLOUDFLARE_ACCOUNT_ID="27a213e220bc2df09c1d4d9fc906a7f9",
        CLOUDFLARE_AI_MODEL="@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )
    arguments = '{"query":"Córdoba, Argentina"}'
    repeated_search = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[ChatToolCall(
                id="call_1",
                function=ChatFunction(
                    name="search_locations",
                    arguments=arguments
                )
            )]
        )
    )])
    repeated_search_again = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[ChatToolCall(
                id="call_2",
                function=ChatFunction(
                    name="search_locations",
                    arguments=arguments
                )
            )]
        )
    )])
    final_answer = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content="Córdoba está en el catálogo consultado."
        )
    )])
    complete_chat = Mock(side_effect=[
        (
            repeated_search,
            "Cloudflare Workers AI",
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        ),
        (
            repeated_search_again,
            "Cloudflare Workers AI",
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        ),
        (
            final_answer,
            "Cloudflare Workers AI",
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        )
    ])
    def dispatch_tool(name, call_arguments, state):
        state["results"].append({
            "result_id": "R1",
            "summary": "Localidad de prueba encontrada."
        })
        return {
            "locations": [{
                "name": "Córdoba",
                "country_name": "Argentina"
            }]
        }

    dispatch = Mock(side_effect=dispatch_tool)
    monkeypatch.setattr(
        AIProviderService,
        "complete_cloudflare_chat",
        complete_chat
    )
    monkeypatch.setattr(
        ResearchAgentService,
        "_dispatch_tool",
        dispatch
    )

    with app.app_context():
        result = ResearchAgentService.run(
            question="Buscá Córdoba.",
            conversation_history=[],
            investigation_id=1,
            user_id=1
        )

    assert result["answer"] == "Córdoba está en el catálogo consultado."
    dispatch.assert_called_once()
    assert dispatch.call_args.args[:2] == (
        "search_locations",
        {"query": "Córdoba, Argentina"}
    )
    final_request = complete_chat.call_args_list[2].args[0]
    assert "tools" not in final_request
    assert "No vuelvas a llamar herramientas" in (
        final_request["messages"][-1]["content"]
    )


def test_tool_round_limit_requests_a_final_answer(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        CLOUDFLARE_API_TOKEN="test-cloudflare-token",
        CLOUDFLARE_ACCOUNT_ID="27a213e220bc2df09c1d4d9fc906a7f9",
        CLOUDFLARE_AI_MODEL="@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )
    tool_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[ChatToolCall(
                id="call_1",
                function=ChatFunction(
                    name="search_locations",
                    arguments='{"query":"Córdoba"}'
                )
            )]
        )
    )])
    answer_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content="La localidad está en los resultados disponibles."
        )
    )])
    complete_chat = Mock(side_effect=[
        (
            tool_response,
            "Cloudflare Workers AI",
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        ),
        (
            answer_response,
            "Cloudflare Workers AI",
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        )
    ])
    def dispatch_tool(name, arguments, state):
        state["results"].append({
            "result_id": "R1",
            "summary": "Localidad de prueba encontrada."
        })
        return {"locations": [{"name": "Córdoba"}]}

    dispatch = Mock(side_effect=dispatch_tool)
    monkeypatch.setattr(ResearchAgentService, "MAX_TOOL_ROUNDS", 1)
    monkeypatch.setattr(
        AIProviderService,
        "complete_cloudflare_chat",
        complete_chat
    )
    monkeypatch.setattr(
        ResearchAgentService,
        "_dispatch_tool",
        dispatch
    )

    with app.app_context():
        result = ResearchAgentService.run(
            question="Buscá Córdoba.",
            conversation_history=[],
            investigation_id=1,
            user_id=1
        )

    assert result["answer"] == (
        "La localidad está en los resultados disponibles."
    )
    assert "tools" not in complete_chat.call_args_list[1].args[0]
    assert "Se alcanzó el límite de operaciones" in (
        complete_chat.call_args_list[1].args[0]["messages"][-1]["content"]
    )


def test_historical_trend_fallback_uses_data_when_model_claims_none(
    monkeypatch
):
    app = Flask(__name__)
    app.config.update(
        CLOUDFLARE_API_TOKEN="test-cloudflare-token",
        CLOUDFLARE_ACCOUNT_ID="27a213e220bc2df09c1d4d9fc906a7f9",
        CLOUDFLARE_AI_MODEL="@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )
    location = {
        "geoname_id": 3860259,
        "name": "Córdoba",
        "country_name": "Argentina"
    }
    search = Mock(return_value=[location])
    monkeypatch.setattr(LocationService, "search_locations", search)
    trend_calls = []

    def analyze_trend(arguments, state):
        trend_calls.append(arguments)
        variable = arguments["variable"]
        unit = "°C" if variable == "temperature_mean" else "mm"
        result = {
            "result_id": f"R{len(state['results']) + 1}",
            "type": "trend",
            "title": variable,
            "summary": "Tendencia calculada con valores anuales.",
            "source": "Open-Meteo Historical Weather API · ERA5",
            "period": {
                "start": arguments["start_date"],
                "end": arguments["end_date"]
            },
            "trend": {
                "slope_per_decade": 0.12,
                "unit": unit,
                "r_squared": 0.42
            }
        }
        state["results"].append(result)
        state["result_index"][result["result_id"]] = result
        return result

    analyze = Mock(side_effect=analyze_trend)
    monkeypatch.setattr(
        ResearchAgentService,
        "_analyze_climate_trends",
        analyze
    )
    answer_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content="No tengo resultados previos para trabajar con ellos."
        )
    )])
    complete_chat = Mock(return_value=(
        answer_response,
        "Cloudflare Workers AI",
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    ))
    monkeypatch.setattr(
        AIProviderService,
        "complete_cloudflare_chat",
        complete_chat
    )

    with app.app_context():
        result = ResearchAgentService.run(
            question=(
                "Analizá la evolución histórica de la temperatura media "
                "y la precipitación de Córdoba, Argentina durante los "
                "últimos 30 años. Mostrá tendencias descriptivas y "
                "limitaciones."
            ),
            conversation_history=[],
            investigation_id=1,
            user_id=1
        )

    assert search.call_args.args[0] == "cordoba, argentina"
    assert [call["variable"] for call in trend_calls] == [
        "temperature_mean",
        "precipitation"
    ]
    assert trend_calls[0]["start_date"] == (
        f"{date.today().year - 30}-01-01"
    )
    assert trend_calls[0]["end_date"] == (
        f"{date.today().year - 1}-12-31"
    )
    assert "0.12 °C por década" in result["answer"]
    assert "Open-Meteo Historical Weather API · ERA5" in result["answer"]
    assert "No tengo resultados" not in result["answer"]
    final_request = complete_chat.call_args.args[0]
    assert "tools" not in final_request
    assert "Open-Meteo Historical Weather API" in (
        final_request["messages"][-1]["content"]
    )


def test_historical_comparison_fallback_resolves_shared_country(
    monkeypatch
):
    app = Flask(__name__)
    app.config.update(
        CLOUDFLARE_API_TOKEN="test-cloudflare-token",
        CLOUDFLARE_ACCOUNT_ID="27a213e220bc2df09c1d4d9fc906a7f9",
        CLOUDFLARE_AI_MODEL="@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )
    catalog = {
        "cordoba": [
            {"geoname_id": 1, "name": "Córdoba", "country_code": "AR"},
            {"geoname_id": 11, "name": "Córdoba", "country_code": "ES"}
        ],
        "buenos aires": [
            {"geoname_id": 2, "name": "Buenos Aires", "country_code": "AR"},
            {
                "geoname_id": 22,
                "name": "Buenos Aires",
                "country_code": "IT"
            }
        ],
        "rosario": [
            {"geoname_id": 3, "name": "Rosario", "country_code": "AR"},
            {"geoname_id": 33, "name": "Rosario", "country_code": "PH"}
        ]
    }

    def search_location(query, limit):
        assert type(limit) is int
        city = query.split(",")[0].strip()
        return catalog[city]

    monkeypatch.setattr(
        LocationService,
        "search_locations",
        Mock(side_effect=search_location)
    )
    comparison_calls = []

    def compare_locations(arguments, state):
        comparison_calls.append(arguments)
        variable = arguments["variable"]
        rows = [
            ["Córdoba, Argentina", 18.1, 17.4, 18.8, 30, "ERA5"],
            ["Buenos Aires, Argentina", 17.6, 16.9, 18.2, 30, "ERA5"],
            ["Rosario, Argentina", 17.9, 17.1, 18.5, 30, "ERA5"]
        ]
        result = {
            "result_id": f"R{len(state['results']) + 1}",
            "type": "location_comparison",
            "title": f"Comparación de {variable}",
            "summary": "Comparación anual basada en datos meteorológicos.",
            "source": "Open-Meteo Historical Weather API · ERA5",
            "period": {
                "start": arguments["start_date"],
                "end": arguments["end_date"]
            },
            "table": {
                "columns": [
                    "Localidad", "Promedio", "Mínimo", "Máximo",
                    "Años", "Fuente"
                ],
                "rows": rows
            }
        }
        state["results"].append(result)
        state["result_index"][result["result_id"]] = result
        return result

    monkeypatch.setattr(
        ResearchAgentService,
        "_compare_locations",
        Mock(side_effect=compare_locations)
    )
    answer_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content="No tengo resultados previos para comparar."
        )
    )])
    complete_chat = Mock(return_value=(
        answer_response,
        "Cloudflare Workers AI",
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    ))
    monkeypatch.setattr(
        AIProviderService,
        "complete_cloudflare_chat",
        complete_chat
    )

    with app.app_context():
        result = ResearchAgentService.run(
            question=(
                "Compará la temperatura media y la precipitación "
                "acumulada de Córdoba, Buenos Aires y Rosario entre "
                "1991 y 2020."
            ),
            conversation_history=[],
            investigation_id=1,
            user_id=1
        )

    assert [call["variable"] for call in comparison_calls] == [
        "temperature_mean",
        "precipitation"
    ]
    assert comparison_calls[0]["geoname_ids"] == [1, 2, 3]
    assert comparison_calls[0]["start_date"] == "1991-01-01"
    assert comparison_calls[0]["end_date"] == "2020-12-31"
    assert "18.1" in result["answer"]
    assert "Open-Meteo Historical Weather API · ERA5" in result["answer"]
    assert "No tengo resultados" not in result["answer"]
    assert len(result["results"]) == 2


def test_daily_records_are_reused_for_multiple_variables(monkeypatch):
    loaded = {
        "records": [{
            "date": "2000-01-01",
            "temperature_mean": 20.0,
            "precipitation": 3.0
        }],
        "source": "Open-Meteo",
        "warning": None,
        "units": {}
    }
    request_records = Mock(return_value=loaded)
    monkeypatch.setattr(
        ResearchAgentService,
        "_get_daily_records",
        request_records
    )
    state = {}
    location = SimpleNamespace(id=1)
    start = end = date(2000, 1, 1)

    temperature = ResearchAgentService._get_cached_daily_records(
        state,
        location,
        start,
        end,
        ["temperature_mean"]
    )
    precipitation = ResearchAgentService._get_cached_daily_records(
        state,
        location,
        start,
        end,
        ["precipitation"]
    )

    assert temperature is loaded
    assert precipitation is loaded
    request_records.assert_called_once_with(
        location,
        start,
        end,
        ["temperature_mean"]
    )


def test_location_search_defaults_invalid_model_limit(monkeypatch):
    search = Mock(return_value=[{"name": "Córdoba"}])
    monkeypatch.setattr(LocationService, "search_locations", search)

    result = ResearchAgentService._search_locations(
        {"query": "Córdoba, Argentina", "limit": 0},
        {}
    )

    assert result["locations"] == [{"name": "Córdoba"}]
    assert "límite de búsqueda inválido" in result["warning"]
    search.assert_called_once_with("Córdoba, Argentina", limit=5)


def test_comparison_data_errors_stop_before_ai_tool_loop(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        CLOUDFLARE_API_TOKEN="test-cloudflare-token",
        CLOUDFLARE_ACCOUNT_ID="27a213e220bc2df09c1d4d9fc906a7f9",
        CLOUDFLARE_AI_MODEL="@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )
    locations = {
        "cordoba": [{"geoname_id": 1, "country_code": "AR"}],
        "buenos aires": [{"geoname_id": 2, "country_code": "AR"}],
        "rosario": [{"geoname_id": 3, "country_code": "AR"}]
    }

    def search_location(query, limit):
        return locations[query.split(",")[0].strip()]

    monkeypatch.setattr(
        LocationService,
        "search_locations",
        Mock(side_effect=search_location)
    )
    monkeypatch.setattr(
        ResearchAgentService,
        "_compare_locations",
        Mock(side_effect=RuntimeError("Open-Meteo HTTP 429"))
    )
    complete_chat = Mock()
    monkeypatch.setattr(
        AIProviderService,
        "complete_cloudflare_chat",
        complete_chat
    )

    with app.app_context(), pytest.raises(
        RuntimeError,
        match="compare_locations: Open-Meteo HTTP 429"
    ):
        ResearchAgentService.run(
            question=(
                "Compará la temperatura media y la precipitación "
                "acumulada de Córdoba, Buenos Aires y Rosario entre "
                "1991 y 2020."
            ),
            conversation_history=[],
            investigation_id=1,
            user_id=1
        )

    complete_chat.assert_not_called()


def test_agent_does_not_complete_a_research_without_data(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        CLOUDFLARE_API_TOKEN="test-cloudflare-token",
        CLOUDFLARE_ACCOUNT_ID="27a213e220bc2df09c1d4d9fc906a7f9",
        CLOUDFLARE_AI_MODEL="@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )
    answer_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content="No tengo resultados previos para responder."
        )
    )])
    complete_chat = Mock(return_value=(
        answer_response,
        "Cloudflare Workers AI",
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    ))
    monkeypatch.setattr(
        AIProviderService,
        "complete_cloudflare_chat",
        complete_chat
    )

    with app.app_context(), pytest.raises(
        RuntimeError,
        match="sin ejecutar herramientas que generaran resultados"
    ):
        ResearchAgentService.run(
            question="Analizá la situación climática.",
            conversation_history=[],
            investigation_id=1,
            user_id=1
        )


def test_research_agent_uses_groq_when_cloudflare_is_unconfigured(
    monkeypatch
):
    app = Flask(__name__)
    app.config.update(
        GROQ_API_KEY="test-groq-key",
        GROQ_MODEL="qwen/qwen3.8-27b"
    )
    tool_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[ChatToolCall(
                id="groq_call_1",
                function=ChatFunction(
                    name="search_locations",
                    arguments='{"query":"Córdoba"}'
                )
            )]
        )
    )])
    answer_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content="Respuesta de investigación de Groq."
        )
    )])
    groq = Mock(side_effect=[
        (
            tool_response,
            "Groq",
            "qwen/qwen3.8-27b"
        ),
        (
            answer_response,
            "Groq",
            "qwen/qwen3.8-27b"
        )
    ])
    cloudflare = Mock()
    monkeypatch.setattr(AIProviderService, "complete_chat", groq)
    monkeypatch.setattr(
        AIProviderService,
        "complete_cloudflare_chat",
        cloudflare
    )

    def dispatch_tool(name, arguments, state):
        state["results"].append({
            "result_id": "R1",
            "summary": "Resultado climático de prueba."
        })
        return {"locations": [{"name": "Córdoba"}]}

    monkeypatch.setattr(
        ResearchAgentService,
        "_dispatch_tool",
        Mock(side_effect=dispatch_tool)
    )

    with app.app_context():
        result = ResearchAgentService.run(
            question="Analizá el perfil climático.",
            conversation_history=[],
            investigation_id=1,
            user_id=1
        )

    assert result["answer"] == "Respuesta de investigación de Groq."
    assert result["provider"] == "Groq"
    assert result["model"] == "qwen/qwen3.8-27b"
    assert groq.call_count == 2
    cloudflare.assert_not_called()


def test_cloudflare_429_falls_back_to_groq_for_the_research(
    monkeypatch
):
    app = Flask(__name__)
    app.config.update(
        CLOUDFLARE_API_TOKEN="test-cloudflare-token",
        CLOUDFLARE_ACCOUNT_ID="27a213e220bc2df09c1d4d9fc906a7f9",
        CLOUDFLARE_AI_MODEL="@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        GROQ_API_KEY="test-groq-key",
        GROQ_MODEL="qwen/qwen3.8-27b"
    )

    def cloudflare_quota_error(*args, **kwargs):
        raise RuntimeError(
            "Cloudflare Workers AI alcanzó su límite temporal."
        ) from AIProviderError(
            "Cloudflare Workers AI",
            "se agotó la cuota diaria.",
            status=429
        )

    cloudflare = Mock(side_effect=cloudflare_quota_error)
    tool_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[ChatToolCall(
                id="groq_call_1",
                function=ChatFunction(
                    name="search_locations",
                    arguments='{"query":"Córdoba"}'
                )
            )]
        )
    )])
    answer_response = ChatCompletion(choices=[ChatChoice(
        message=ChatMessage(
            role="assistant",
            content="La investigación se completó con Groq."
        )
    )])
    groq = Mock(side_effect=[
        (
            tool_response,
            "Groq",
            "qwen/qwen3.8-27b"
        ),
        (
            answer_response,
            "Groq",
            "qwen/qwen3.8-27b"
        )
    ])
    monkeypatch.setattr(
        AIProviderService,
        "complete_cloudflare_chat",
        cloudflare
    )
    monkeypatch.setattr(AIProviderService, "complete_chat", groq)

    def dispatch_tool(name, arguments, state):
        state["results"].append({
            "result_id": "R1",
            "summary": "Resultado climático de prueba."
        })
        return {"locations": [{"name": "Córdoba"}]}

    monkeypatch.setattr(
        ResearchAgentService,
        "_dispatch_tool",
        Mock(side_effect=dispatch_tool)
    )

    with app.app_context():
        result = ResearchAgentService.run(
            question="Analizá el perfil climático.",
            conversation_history=[],
            investigation_id=1,
            user_id=1
        )

    assert result["answer"] == "La investigación se completó con Groq."
    assert result["provider"] == "Groq"
    assert result["model"] == "qwen/qwen3.8-27b"
    assert cloudflare.call_count == 1
    assert groq.call_count == 2
