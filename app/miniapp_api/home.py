"""Mini App endpoints of "My Googlagent": the home view and the first result."""

import logging
import re
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.bot.roles import RoleRegistry
from app.bot.runtime import BotRuntime
from app.config import Settings
from app.miniapp_api.auth import TelegramUser
from app.profile.asr import MAX_AUDIO_BYTES, AsrError, clean_mime
from app.track.service import FirstResultError

log = logging.getLogger("app.miniapp")
Authenticate = Callable[[str, Request], TelegramUser | JSONResponse]
STATUS = {"not_ready": 409, "need_text": 422, "unavailable": 503, "failed": 502}
TEXT_LIMIT = 6000
SLUG = re.compile(r"[a-z0-9-]{1,64}")


def _no_store(body: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def register_home_routes(
    app: FastAPI,
    *,
    authenticate: Authenticate,
    get_runtime: Callable[[], BotRuntime],
    settings: Settings,
) -> None:
    async def context(tenant_id: str, request: Request):
        user = authenticate(tenant_id, request)
        if isinstance(user, JSONResponse):
            return user
        runtime = get_runtime()
        home = runtime.home(tenant_id)
        first = runtime.first_result(tenant_id)
        if home is None or first is None:
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
        return row.id, home, first, runtime, user

    async def produce(tenant_id, user_id, home, first, runtime, user, routines):
        if not runtime.first_result_limiter.allow(("first", tenant_id, user.id)):
            return _no_store({"error": "rate_limited"}, 429)
        try:
            result = await first.run(tenant_id, user_id, routines)
        except FirstResultError as exc:
            return _no_store({"error": exc.reason}, STATUS.get(exc.reason, 500))
        return _no_store({"result": result, "home": await home.view(tenant_id, user_id)})

    @app.post("/api/miniapp/{tenant_id}/skills/{slug}/start")
    async def start_skill(tenant_id: str, slug: str, request: Request) -> JSONResponse:
        """Open a skill in the chat: the estimate and the choice of the road arrive there."""
        user = authenticate(tenant_id, request)
        if isinstance(user, JSONResponse):
            return user
        flow = get_runtime().flow(tenant_id)
        if flow is None or not SLUG.fullmatch(slug):
            return _no_store({"error": "unavailable" if flow is None else "unknown_skill"}, 404)
        outcome = await flow.start(user.id, slug)
        status = {"ok": 200, "no_chat": 409, "unknown_skill": 404}[outcome]
        return _no_store(
            {"started": outcome == "ok", "error": None if outcome == "ok" else outcome}, status
        )

    @app.get("/api/miniapp/{tenant_id}/home")
    async def read_home(tenant_id: str, request: Request) -> JSONResponse:
        found = await context(tenant_id, request)
        if isinstance(found, JSONResponse):
            return found
        user_id, home, *_ = found
        return _no_store(await home.view(tenant_id, user_id))

    @app.post("/api/miniapp/{tenant_id}/first-result")
    async def first_result(tenant_id: str, request: Request) -> JSONResponse:
        found = await context(tenant_id, request)
        if isinstance(found, JSONResponse):
            return found
        user_id, home, first, runtime, user = found
        try:
            body = await request.json()
            text = body.get("text") if isinstance(body, dict) else None
        except ValueError:
            text = None
        text = text[:TEXT_LIMIT] if isinstance(text, str) else None
        return await produce(tenant_id, user_id, home, first, runtime, user, text)

    @app.post("/api/miniapp/{tenant_id}/first-result/voice")
    async def first_result_voice(tenant_id: str, request: Request) -> JSONResponse:
        """The routines told by voice: recognised, then handled like typed text."""
        found = await context(tenant_id, request)
        if isinstance(found, JSONResponse):
            return found
        user_id, home, first, runtime, user = found
        mime = clean_mime(request.headers.get("content-type"))
        if mime is None:
            return _no_store({"error": "unsupported_type"}, 415)
        asr = runtime.profile(tenant_id).asr if runtime.profile(tenant_id) else None
        if asr is None:
            return _no_store({"error": "no_asr"}, 503)
        audio = bytearray()
        async for chunk in request.stream():
            audio.extend(chunk)
            if len(audio) > MAX_AUDIO_BYTES:
                return _no_store({"error": "too_big"}, 413)
        if not runtime.voice_limiter.allow(("voice", tenant_id, user.id)):
            return _no_store({"error": "rate_limited"}, 429)
        try:
            story = await asr.transcribe(bytes(audio), mime) if audio else ""
        except AsrError:
            return _no_store({"error": "asr_error"}, 502)
        return await produce(tenant_id, user_id, home, first, runtime, user, story)
