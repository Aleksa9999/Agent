"""Posts the public profile card into the person's topic of the shared group."""

import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.bot.service import GROUP_KIND, OnboardingService
from app.profile.privacy import violations

log = logging.getLogger("app.bot")
NOT_MODIFIED = "message is not modified"


class GroupPublisher:
    def __init__(self, svc: OnboardingService, patterns: Path):
        self.svc = svc
        self.patterns = patterns

    async def publish(
        self,
        tenant: str,
        user_id: int,
        name: str,
        lines: list[tuple[str, str]],
        previous: int | None,
    ) -> int | None:
        topic = await self.svc.repo.get_topic(tenant, user_id, GROUP_KIND)
        if topic is None or not lines:
            return None  # the person is not in the group yet, or nothing public is left
        body = "\n".join(self.svc.t("pass_public_line", label=a, text=b) for a, b in lines)
        found = violations(body, self.patterns)
        if found:  # the last gate: whatever got here, private data does not leave
            log.error("public card was held back by the privacy gate: %s", ",".join(found))
            return None
        text = self.svc.t("pass_public_header", name=name) + "\n" + body
        bot = self.svc.bot
        try:
            if previous is not None:
                try:
                    await bot.edit_message_text(
                        chat_id=topic.chat_id, message_id=previous, text=text
                    )
                    return previous
                except TelegramBadRequest as exc:
                    if NOT_MODIFIED in (exc.message or ""):
                        return previous
                    # the old message is gone: post a new one below
            sent = await bot.send_message(
                chat_id=topic.chat_id, message_thread_id=topic.thread_id, text=text
            )
            return sent.message_id
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            log.error("public card was not posted: %s", type(exc).__name__)
            return None
