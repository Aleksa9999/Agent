"""Roles come from the server-side registry (OWNER_TG_ID), never from names or message text."""

from typing import Literal

Role = Literal["owner", "member"]


class RoleRegistry:
    def __init__(self, owner_tg_id: int | None):
        self._owner = owner_tg_id

    def role_of(self, tg_id: int) -> Role:
        return "owner" if self._owner is not None and tg_id == self._owner else "member"
