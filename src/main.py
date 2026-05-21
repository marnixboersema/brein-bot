"""Bot entry point — long-polling loop."""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from . import handlers, state


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        level=level,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _require_env(*names: str) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        print(f"Missing required env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)


async def _post_init(app: Application) -> None:
    await state.init_db()
    logging.info("State DB ready at %s", state.DB_PATH)


def build_app() -> Application:
    _require_env(
        "TELEGRAM_BOT_TOKEN",
        "OPENAI_API_KEY",
        "OPENWEBUI_BASE_URL",
        "OPENWEBUI_API_KEY",
        "ALLOWED_TELEGRAM_USER_IDS",
    )
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CommandHandler("status", handlers.cmd_status))
    app.add_handler(CommandHandler("kb", handlers.cmd_kb))

    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handlers.on_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handlers.on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handlers.on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text))

    app.add_handler(CallbackQueryHandler(handlers.on_callback))

    return app


def main() -> None:
    _configure_logging()
    app = build_app()
    logging.info("Brein-bot starting (long polling)")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
