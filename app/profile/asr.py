"""Speech recognition port and the Model Studio adapter (Qwen-ASR, OpenAI-compatible protocol).

The request shape follows the Model Studio reference: chat/completions with an `input_audio`
content part carrying a data URL. It is covered by recorded payloads only; the first real call
happens when a key and a model id are configured (gate 1).
"""

import base64
import logging
from typing import Protocol

import httpx

log = logging.getLogger("app.profile")

ALLOWED_MIME = frozenset(
    {
        "audio/ogg",
        "audio/opus",
        "audio/webm",
        "audio/mp4",
        "audio/x-m4a",
        "audio/m4a",
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/aac",
        "audio/flac",
    }
)
MAX_AUDIO_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 60.0


class AsrError(Exception):
    """A failed recognition. The message never contains keys or audio."""


class AsrPort(Protocol):
    async def transcribe(self, audio: bytes, mime: str) -> str: ...


def clean_mime(value: str | None) -> str | None:
    """`audio/webm;codecs=opus` -> `audio/webm`; None when the type is not an allowed audio type."""
    base = (value or "").split(";")[0].strip().lower()
    return base if base in ALLOWED_MIME else None


class QwenAsrClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.AsyncClient | None = None,
    ):
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._key = api_key
        self._model = model
        self._client = client

    async def transcribe(self, audio: bytes, mime: str) -> str:
        data_url = f"data:{mime};base64,{base64.b64encode(audio).decode()}"
        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "input_audio", "input_audio": {"data": data_url}}],
                }
            ],
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            if self._client is not None:
                response = await self._client.post(self._url, json=body, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                    response = await client.post(self._url, json=body, headers=headers)
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            log.warning("recognition failed: %s", type(exc).__name__)
            raise AsrError(type(exc).__name__) from None
        return text.strip() if isinstance(text, str) else ""
