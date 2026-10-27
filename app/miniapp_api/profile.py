"""Mini App endpoints of the entrance test: read the profile, answer, go back, send a recording."""

import logging
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.bot.roles import RoleRegistry
from app.bot.runtime import BotRuntime
from app.config import Settings
from app.miniapp_api.auth import TelegramUser
from app.profile import service as outcomes
from app.profile.asr import MAX_AUDIO_BYTES, clean_mime
from app.profile.service import InvalidAnswerError

log = logging.getLogger("app.miniapp")
Authenticate = Callable[[str, Request], TelegramUser | JSONResponse]


class AnswerBody(BaseModel):
    field: str = Field(max_length=32)
    kind: str = Field(max_length=16)
    code: str | None = Field(default=None, max_length=16)
    text: str | None = Field(default=None, max_length=2000)


def _no_store(body: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def register_profile_routes(
    app: FastAPI,
    *,
    authenticate: Authenticate,
    get_runtime: Callable[[], BotRuntime],
    settings: Settings,
) -> None:
    async def context(tenant_id: str, request: Request):
        """(person row id, ProfileService) or the error response."""
        user = authenticate(tenant_id, request)
        if isinstance(user, JSONResponse):
            return user
        runtime = get_runtime()
        profile = runtime.profile(tenant_id)
        if profile is None:
            return _no_store({"error": "unavailable"}, 503)
        row = await runtime.repo.upsert_user(
            tenant_id,
            user.id,
            role=RoleRegistry(settings.owner_tg_id).role_of(user.id),
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            lang=user.language_code,
        )
        return row.id, profile, user

    @app.get("/api/miniapp/{tenant_id}/profile")
    async def read_profile(tenant_id: str, request: Request) -> JSONResponse:
        found = await context(tenant_id, request)
        if isinstance(found, JSONResponse):
            return found
        user_id, profile, _ = found
        return _no_store(await profile.view(tenant_id, user_id))

    @app.post("/api/miniapp/{tenant_id}/profile/answer")
    async def answer(tenant_id: str, request: Request) -> JSONResponse:
        found = await context(tenant_id, request)  # the person is checked before the body is read
        if isinstance(found, JSONResponse):
            return found
        user_id, profile, _ = found
        try:
            body = AnswerBody.model_validate(await request.json())
        except (ValueError, ValidationError):
            return _no_store({"error": "bad_request"}, 422)
        try:
            view = await profile.answer(
                tenant_id, user_id, body.field, body.kind, body.code, body.text
            )
        except InvalidAnswerError as exc:
            # "not_current": an old screen was answered; the client reloads the profile
            return _no_store({"error": exc.reason}, 409 if exc.reason == "not_current" else 422)
        return _no_store(view)

    @app.post("/api/miniapp/{tenant_id}/profile/back")
    async def back(tenant_id: str, request: Request) -> JSONResponse:
        found = await context(tenant_id, request)
        if isinstance(found, JSONResponse):
            return found
        user_id, profile, _ = found
        return _no_store(await profile.back(tenant_id, user_id))

    @app.post("/api/miniapp/{tenant_id}/profile/voice")
    async def voice(tenant_id: str, request: Request) -> JSONResponse:
        found = await context(tenant_id, request)
        if isinstance(found, JSONResponse):
            return found
        user_id, profile, user = found
        mime = clean_mime(request.headers.get("content-type"))
        if mime is None:
            return _no_store({"error": "unsupported_type"}, 415)
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
            return _no_store({"error": "too_big"}, 413)
        if not get_runtime().voice_limiter.allow(("voice", tenant_id, user.id)):
            return _no_store({"error": "rate_limited"}, 429)
        audio = bytearray()
        async for chunk in request.stream():
            audio.extend(chunk)
            if len(audio) > MAX_AUDIO_BYTES:
                return _no_store({"error": "too_big"}, 413)  # a lying header cannot get past this
        if not audio:
            return _no_store({"outcome": outcomes.EMPTY, "profile": None, "new_fields": 0})
        result = await profile.hear(tenant_id, user_id, bytes(audio), mime)
        return _no_store(
            {"outcome": result.outcome, "profile": result.view, "new_fields": result.new_fields}
        )
