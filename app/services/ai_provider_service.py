
import copy
import json
import re
from dataclasses import dataclass, field

import requests

from flask import current_app


@dataclass
class ChatFunction:
    name: str
    arguments: str


@dataclass
class ChatToolCall:
    id: str
    function: ChatFunction


@dataclass
class ChatMessage:
    role: str
    content: str | None
    tool_calls: list[ChatToolCall] = field(default_factory=list)


@dataclass
class ChatChoice:
    message: ChatMessage
    index: int = 0
    finish_reason: str | None = None


@dataclass
class ChatCompletion:
    choices: list[ChatChoice]
    id: str | None = None
    model: str | None = None


class AIProviderError(RuntimeError):
    def __init__(self, provider, message, status=None):
        self.provider = provider
        self.status = status
        super().__init__(f"{provider}: {message}")


class AIProviderService:
    GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
    CLOUDFLARE_CHAT_URL = (
        "https://api.cloudflare.com/client/v4/accounts/"
        "{account_id}/ai/v1/chat/completions"
    )

    @classmethod
    def is_configured(cls):
        return bool(
            current_app.config.get("GROQ_API_KEY")
            and current_app.config.get("GROQ_MODEL")
        )

    @classmethod
    def is_cloudflare_configured(cls):
        return bool(
            current_app.config.get("CLOUDFLARE_API_TOKEN")
            and current_app.config.get("CLOUDFLARE_ACCOUNT_ID")
            and current_app.config.get("CLOUDFLARE_AI_MODEL")
        )

    @classmethod
    def complete_chat(
        cls,
        payload,
        timeout=45,
        require_text=True
    ):
        return cls._complete(
            cls._groq_provider(),
            payload,
            timeout,
            require_text
        )

    @classmethod
    def complete_cloudflare_chat(
        cls,
        payload,
        timeout=45,
        require_text=True
    ):
        return cls._complete(
            cls._cloudflare_provider(),
            payload,
            timeout,
            require_text
        )

    @classmethod
    def _complete(cls, provider, payload, timeout, require_text):
        try:
            return cls._request(
                provider,
                payload,
                timeout,
                require_text
            )
        except AIProviderError as error:
            raise RuntimeError(
                cls._provider_failure_message(error)
            ) from error

    @classmethod
    def _groq_provider(cls):
        groq_key = current_app.config.get("GROQ_API_KEY")
        groq_model = current_app.config.get("GROQ_MODEL")
        if not groq_key or not groq_model:
            raise RuntimeError(
                "Configurá GROQ_API_KEY y GROQ_MODEL para utilizar la IA."
            )
        return {
            "name": "Groq",
            "url": cls.GROQ_URL,
            "key": groq_key,
            "model": groq_model
        }

    @classmethod
    def _cloudflare_provider(cls):
        token = current_app.config.get("CLOUDFLARE_API_TOKEN")
        account_id = current_app.config.get("CLOUDFLARE_ACCOUNT_ID")
        model = current_app.config.get("CLOUDFLARE_AI_MODEL")
        if not token or not account_id or not model:
            raise RuntimeError(
                "Configurá CLOUDFLARE_API_TOKEN, "
                "CLOUDFLARE_ACCOUNT_ID y CLOUDFLARE_AI_MODEL "
                "para investigar."
            )
        if not re.fullmatch(r"[a-fA-F0-9]{32}", account_id):
            raise RuntimeError(
                "CLOUDFLARE_ACCOUNT_ID debe ser un identificador válido."
            )
        return {
            "name": "Cloudflare Workers AI",
            "url": cls.CLOUDFLARE_CHAT_URL.format(
                account_id=account_id
            ),
            "key": token,
            "model": model
        }

    @staticmethod
    def _provider_failure_message(error):
        if error.provider == "Groq":
            if error.status == 429:
                return "Groq alcanzó temporalmente su límite."
            if error.status is None or error.status >= 500:
                return "Groq no respondió a tiempo o está temporalmente indisponible."
            return f"Groq no pudo completar la solicitud (HTTP {error.status})."

        if error.provider == "Cloudflare Workers AI":
            if error.status in (401, 403):
                return (
                    "Cloudflare rechazó el token o no tiene permisos "
                    "para Workers AI."
                )
            if error.status == 429:
                return "Cloudflare Workers AI alcanzó su límite temporal."
            if error.status is None or error.status >= 500:
                return (
                    "Cloudflare Workers AI no respondió o está "
                    "temporalmente indisponible."
                )
            return (
                "Cloudflare Workers AI no pudo completar la solicitud "
                f"(HTTP {error.status}). Detalle: {str(error)}"
            )

        return "El proveedor de IA no pudo completar la solicitud."

    @classmethod
    def _request(cls, provider, payload, timeout, require_text):
        request_payload = copy.deepcopy(payload)
        request_payload["model"] = provider["model"]
        headers = {
            "Authorization": f"Bearer {provider['key']}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(
                provider["url"],
                headers=headers,
                json=request_payload,
                timeout=timeout
            )
        except requests.Timeout as error:
            raise AIProviderError(
                provider["name"],
                "la solicitud excedió el tiempo de espera."
            ) from error
        except requests.RequestException as error:
            raise AIProviderError(
                provider["name"],
                "no se pudo establecer conexión."
            ) from error

        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            status = (
                error.response.status_code
                if error.response is not None
                else None
            )
            message = cls._error_message(response)
            raise AIProviderError(
                provider["name"],
                f"respondió con HTTP {status or 'desconocido'}: {message}",
                status=status
            ) from error

        try:
            result = response.json()
        except ValueError as error:
            raise AIProviderError(
                provider["name"],
                "devolvió una respuesta con formato inesperado."
            ) from error

        choices = result.get("choices") if isinstance(result, dict) else None
        if not isinstance(choices, list) or not choices:
            raise AIProviderError(
                provider["name"],
                "devolvió una respuesta sin opciones."
            )

        normalized_choices = []
        for index, choice in enumerate(choices):
            message = (
                choice.get("message")
                if isinstance(choice, dict)
                else None
            )
            if not isinstance(message, dict):
                raise AIProviderError(
                    provider["name"],
                    "devolvió una respuesta con formato inesperado."
                )

            content = message.get("content")
            if content is not None and not isinstance(content, str):
                raise AIProviderError(
                    provider["name"],
                    "devolvió contenido con un formato inesperado."
                )

            raw_tool_calls = message.get("tool_calls") or []
            if not isinstance(raw_tool_calls, list):
                raise AIProviderError(
                    provider["name"],
                    "devolvió llamadas a herramientas con formato inesperado."
                )

            tool_calls = []
            for raw_tool_call in raw_tool_calls:
                function = (
                    raw_tool_call.get("function")
                    if isinstance(raw_tool_call, dict)
                    else None
                )
                if not isinstance(function, dict):
                    raise AIProviderError(
                        provider["name"],
                        "devolvió una llamada a herramienta inválida."
                    )

                name = function.get("name")
                arguments = function.get("arguments", "{}")
                if isinstance(arguments, dict):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                tool_id = raw_tool_call.get("id")
                if (
                    not isinstance(name, str)
                    or not name
                    or not isinstance(arguments, str)
                    or not isinstance(tool_id, str)
                    or not tool_id
                ):
                    raise AIProviderError(
                        provider["name"],
                        "devolvió una llamada a herramienta incompleta."
                    )
                tool_calls.append(ChatToolCall(
                    id=tool_id,
                    function=ChatFunction(
                        name=name,
                        arguments=arguments
                    )
                ))

            if index == 0:
                if require_text:
                    valid_result = isinstance(content, str) and content.strip()
                else:
                    valid_result = (
                        (isinstance(content, str) and content.strip())
                        or tool_calls
                    )
                if not valid_result:
                    raise AIProviderError(
                        provider["name"],
                        "respondió sin contenido utilizable."
                    )

            normalized_choices.append(ChatChoice(
                message=ChatMessage(
                    role=message.get("role") or "assistant",
                    content=content,
                    tool_calls=tool_calls
                ),
                index=choice.get("index", index),
                finish_reason=choice.get("finish_reason")
            ))

        return ChatCompletion(
            choices=normalized_choices,
            id=result.get("id"),
            model=provider["model"]
        ), provider["name"], provider["model"]


    @staticmethod
    def _error_message(response):
        try:
            error_data = response.json()
        except (ValueError, requests.RequestException):
            text = getattr(response, "text", "")
            return text.strip()[:500] if text else (
                "el proveedor rechazó la solicitud."
            )

        if isinstance(error_data, dict):
            # Formato compatible con OpenAI
            api_error = error_data.get("error")

            if isinstance(api_error, dict):
                message = api_error.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()[:500]

            if isinstance(api_error, str) and api_error.strip():
                return api_error.strip()[:500]

            # Formato habitual de errores de Cloudflare
            errors = error_data.get("errors")

            if isinstance(errors, list) and errors:
                messages = []

                for item in errors:
                    if isinstance(item, dict):
                        code = item.get("code")
                        message = item.get("message")

                        if isinstance(message, str) and message.strip():
                            if code is not None:
                                messages.append(
                                    f"Código {code}: {message.strip()}"
                                )
                            else:
                                messages.append(message.strip())

                if messages:
                    return " | ".join(messages)[:500]

            message = error_data.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()[:500]

        return "el proveedor rechazó la solicitud."
