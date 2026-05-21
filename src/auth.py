"""Whitelist auth decorator for handlers."""
from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

REFUSAL_AF = "Jammer, jy het nie toegang tot hierdie bot nie."


def _allowed_ids() -> set[int]:
    raw = os.environ.get("ALLOWED_TELEGRAM_USER_IDS", "").strip()
    if not raw:
        return set()
    ids: set[int] = set()
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            ids.add(int(piece))
        except ValueError:
            log.warning("Ignoring non-integer entry in ALLOWED_TELEGRAM_USER_IDS: %r", piece)
    return ids


def is_allowed(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return user_id in _allowed_ids()


Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def whitelisted(handler: Handler) -> Handler:
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        uid = user.id if user else None
        if not is_allowed(uid):
            log.warning(
                "Unauthorised access attempt: user_id=%s username=%s",
                uid,
                getattr(user, "username", None),
            )
            if update.effective_message:
                await update.effective_message.reply_text(REFUSAL_AF)
            return
        await handler(update, context)

    return wrapper
