"""A voice message in the private chat fills the same profile as the Mini App recording."""

import logging

from aiogram.types import Audio, Voice
from aiogram.types import User as TgUser

from app.bot.service import OnboardingService
from app.profile import service as outcomes
from app.profile.asr import MAX_AUDIO_BYTES, clean_mime
from app.profile.service import ProfileService
from app.ratelimit import RateLimiter

log = logging.getLogger("app.bot")
DEFAULT_VOICE_MIME = "audio/ogg"  # Telegram voice messages are Ogg/Opus


class VoiceIntake:
    def __init__(self, *, svc: OnboardingService, profile: ProfileService, limiter: RateLimiter):
        self.svc = svc
        self.profile = profile
        self.limiter = limiter

    async def handle(
        self, user: TgUser, chat_id: int, thread_id: int | None, media: Voice | Audio
    ) -> None:
        bot, t = self.svc.bot, self.svc.t

        async def say(key: str, **values: object) -> None:
            await bot.send_message(
                chat_id=chat_id, message_thread_id=thread_id, text=t(key, **values)
            )

        if not self.profile.voice_available:
            await say("pf_voice_unavailable")
            return
        if media.file_size is not None and media.file_size > MAX_AUDIO_BYTES:
            await say("pf_voice_too_big")
            return
        if not self.limiter.allow(("voice", self.svc.tenant_id, user.id)):
            await say("pf_voice_limit")
            return
        mime = clean_mime(media.mime_type) or DEFAULT_VOICE_MIME
        row = await self.svc.upsert_user(user)
        await say("pf_voice_busy")
        file = await bot.get_file(media.file_id)
        buffer = await bot.download_file(file.file_path) if file.file_path else None
        audio = buffer.read() if buffer is not None else b""
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            await say("pf_voice_too_big" if audio else "pf_voice_empty")
            return
        result = await self.profile.hear(self.svc.tenant_id, row.id, audio, mime)
        failures = {
            outcomes.NO_ASR: "pf_voice_unavailable",
            outcomes.ASR_ERROR: "pf_voice_error",
            outcomes.EMPTY: "pf_voice_empty",
            outcomes.NOTHING: "pf_voice_nothing",
        }
        if result.outcome in failures or result.view is None:
            await say(failures.get(result.outcome, "pf_voice_error"))
            return
        progress = result.view["progress"]
        left = progress["total"] - progress["answered"]
        if left == 0:
            await say("pf_voice_complete", done=progress["answered"], total=progress["total"])
            return
        await say("pf_voice_filled", done=progress["answered"], total=progress["total"], left=left)
        await self.svc.offer_miniapp(chat_id, thread_id)
