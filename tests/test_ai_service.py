from unittest.mock import Mock, patch

import pytest
import requests
from flask import Flask

from app.services.ai_provider_service import AIProviderService
from app.services.ai_service import AIService


@pytest.fixture
def ai_app():
    app = Flask(__name__)
    app.config.update(
        GROQ_API_KEY="test-groq-key",
        GROQ_MODEL="qwen/qwen3.8-27b"
    )
    return app


def test_generate_report_uses_groq_chat_completions_api(ai_app):
    response = Mock()
    response.json.return_value = {
        "choices": [{
            "message": {
                "content": "Lectura climática"
            }
        }]
    }

    with ai_app.app_context(), patch(
        "app.services.ai_provider_service.requests.post",
        return_value=response
    ) as post:
        result = AIService._generate_report("Instrucciones", "Datos")

    assert result == "Lectura climática"
    assert post.call_count == 1
    args, kwargs = post.call_args
    assert args[0] == (
        "https://api.groq.com/openai/v1/chat/completions"
    )
    assert kwargs["headers"]["Authorization"] == "Bearer test-groq-key"
    assert kwargs["json"] == {
        "model": "qwen/qwen3.8-27b",
        "max_completion_tokens": 1500,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "Instrucciones"},
            {"role": "user", "content": "Datos"}
        ]
    }


def test_cloudflare_chat_uses_account_scoped_workers_ai_api(ai_app):
    ai_app.config.update(
        CLOUDFLARE_API_TOKEN="test-cloudflare-token",
        CLOUDFLARE_ACCOUNT_ID="27a213e220bc2df09c1d4d9fc906a7f9",
        CLOUDFLARE_AI_MODEL=(
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        )
    )
    response = Mock()
    response.json.return_value = {
        "choices": [{
            "message": {"content": "Respuesta de Cloudflare."}
        }]
    }

    with ai_app.app_context(), patch(
        "app.services.ai_provider_service.requests.post",
        return_value=response
    ) as post:
        completion, provider, model = (
            AIProviderService.complete_cloudflare_chat({
                "messages": [{"role": "user", "content": "Hola"}]
            })
        )

    assert provider == "Cloudflare Workers AI"
    assert model == "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    assert completion.choices[0].message.content == (
        "Respuesta de Cloudflare."
    )
    assert post.call_args.args[0] == (
        "https://api.cloudflare.com/client/v4/accounts/"
        "27a213e220bc2df09c1d4d9fc906a7f9/ai/v1/chat/completions"
    )
    assert post.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer test-cloudflare-token"
    )
    assert post.call_args.kwargs["json"]["model"] == (
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )


def test_observatory_insight_only_interprets_selected_location(ai_app):
    response = Mock()
    response.json.return_value = {
        "choices": [{
            "message": {
                "content": "Contraste regional observado."
            }
        }]
    }

    with ai_app.app_context(), patch(
        "app.services.ai_provider_service.requests.post",
        return_value=response
    ) as post:
        report = AIService.generate_observatory_insight(
            {
                "city": "Yekaterinburg",
                "region": "Sverdlovsk Oblast",
                "country": "Rusia",
                "temperature": 1.1,
                "precipitation_today": 30.1
            },
            {
                "fuente": "ERA5",
                "referencia": {"start_year": 1991, "end_year": 2020},
                "tendencias_por_decada": {"temperature_per_decade": 0.3}
            }
        )

    payload = post.call_args.kwargs["json"]
    assert report == "Contraste regional observado."
    assert payload["max_completion_tokens"] == 650
    assert "observación climática local" in payload["messages"][0]["content"]
    assert "todo el país" in payload["messages"][0]["content"]
    assert "Yekaterinburg" in payload["messages"][1]["content"]
    assert "30.1" in payload["messages"][1]["content"]
    assert "interpretá de todos modos las condiciones actuales" in (
        payload["messages"][0]["content"]
    )
    assert "no confundas ese problema con la disponibilidad de Groq" in (
        payload["messages"][0]["content"]
    )
    assert "Córdoba" not in payload["messages"][1]["content"]
    assert "NASA" not in payload["messages"][1]["content"]


def test_generate_report_requires_a_configured_provider(ai_app):
    ai_app.config["GROQ_API_KEY"] = ""

    with ai_app.app_context(), pytest.raises(
        RuntimeError,
        match="GROQ_API_KEY y GROQ_MODEL"
    ):
        AIService._generate_report("Instrucciones", "Datos")


def test_generate_report_surfaces_groq_http_errors(ai_app):
    response = Mock()
    response.status_code = 401
    response.json.return_value = {
        "error": {
            "message": "invalid API key"
        }
    }
    response.raise_for_status.side_effect = requests.HTTPError(
        response=response
    )

    with ai_app.app_context(), patch(
        "app.services.ai_provider_service.requests.post",
        return_value=response
    ), pytest.raises(
        RuntimeError,
        match="Groq no pudo completar la solicitud \\(HTTP 401\\)"
    ):
        AIService._generate_report("Instrucciones", "Datos")


def test_generate_report_uses_only_groq_even_if_openrouter_is_configured(
    ai_app
):
    ai_app.config.update(
        OPENROUTER_API_KEY="test-openrouter-key",
        OPENROUTER_MODEL="openrouter/free"
    )
    response = Mock()
    response.json.return_value = {
        "choices": [{
            "message": {"content": "Respuesta de Groq."}
        }]
    }

    with ai_app.app_context(), patch(
        "app.services.ai_provider_service.requests.post",
        return_value=response
    ) as post:
        report = AIService._generate_report(
            "Instrucciones",
            "Datos",
            max_completion_tokens=120
        )

    assert report == "Respuesta de Groq."
    assert post.call_count == 1
    assert post.call_args.args[0] == (
        "https://api.groq.com/openai/v1/chat/completions"
    )
    assert post.call_args.kwargs["json"]["max_completion_tokens"] == 120


def test_openrouter_configuration_is_not_used_without_groq(ai_app):
    ai_app.config.update(
        GROQ_API_KEY="",
        OPENROUTER_API_KEY="test-openrouter-key",
        OPENROUTER_MODEL="openrouter/free"
    )
    with ai_app.app_context(), patch(
        "app.services.ai_provider_service.requests.post"
    ) as post:
        with pytest.raises(
            RuntimeError,
            match="GROQ_API_KEY y GROQ_MODEL"
        ):
            AIService._generate_report("Instrucciones", "Datos")
    post.assert_not_called()


def test_generate_report_does_not_fallback_after_groq_failure(ai_app):
    ai_app.config.update(
        OPENROUTER_API_KEY="test-openrouter-key",
        OPENROUTER_MODEL="openrouter/free"
    )
    groq_response = Mock()
    groq_response.status_code = 429
    groq_response.json.return_value = {
        "error": {"message": "rate limited"}
    }
    groq_response.raise_for_status.side_effect = requests.HTTPError(
        response=groq_response
    )
    with ai_app.app_context(), patch(
        "app.services.ai_provider_service.requests.post",
        return_value=groq_response
    ) as post, pytest.raises(
        RuntimeError,
        match="Groq alcanzó temporalmente su límite"
    ):
        AIService._generate_report("Instrucciones", "Datos")
    assert post.call_count == 1
    assert post.call_args.args[0] == (
        "https://api.groq.com/openai/v1/chat/completions"
    )


def test_groq_tool_calls_use_the_normalized_response_interface(ai_app):
    response = Mock()
    response.json.return_value = {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search_locations",
                        "arguments": "{\"query\":\"Córdoba\"}"
                    }
                }]
            }
        }]
    }

    with ai_app.app_context(), patch(
        "app.services.ai_provider_service.requests.post",
        return_value=response
    ) as post:
        completion, provider, model = AIProviderService.complete_chat(
            {"messages": []},
            require_text=False
        )

    tool_call = completion.choices[0].message.tool_calls[0]
    assert provider == "Groq"
    assert model == "qwen/qwen3.8-27b"
    assert post.call_count == 1
    assert post.call_args.args[0] == (
        "https://api.groq.com/openai/v1/chat/completions"
    )
    assert completion.choices[0].message.content is None
    assert tool_call.id == "call_1"
    assert tool_call.function.name == "search_locations"
    assert tool_call.function.arguments == "{\"query\":\"Córdoba\"}"


def test_territory_answer_combines_climate_context_images_and_chat(ai_app):
    response = Mock()
    response.json.return_value = {
        "choices": [{
            "message": {
                "content": "Respuesta integrada."
            }
        }]
    }
    history = [
        {"role": "user", "content": "¿Qué período elegí?"},
        {"role": "assistant", "content": "2019 y 2020."}
    ]
    image = {
        "date": "2020-06-15",
        "media_type": "image/jpeg",
        "data": "dGVzdA=="
    }

    with ai_app.app_context(), patch(
        "app.services.ai_provider_service.requests.post",
        return_value=response
    ) as post:
        answer = AIService.generate_territory_research_answer(
            question="¿Qué puedo investigar aquí?",
            selection={"type": "point", "name": "Córdoba"},
            climate_profile={"reference": {"start_year": 1991}},
            satellite_images=[image],
            conversation_history=history
        )

    assert answer == "Respuesta integrada."
    payload = post.call_args.kwargs["json"]
    assert payload["messages"][1:3] == history
    assert "asistente de investigación territorial" in (
        payload["messages"][0]["content"]
    )
    assert payload["max_completion_tokens"] == 900
    current_message = payload["messages"][3]["content"]
    assert current_message[0]["type"] == "text"
    assert "perfil climático" in current_message[0]["text"].lower()
    assert current_message[-1] == {
        "type": "image_url",
        "image_url": {
            "url": "data:image/jpeg;base64,dGVzdA=="
        }
    }
