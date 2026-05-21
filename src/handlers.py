"""Telegram message + callback handlers."""
from __future__ import annotations

import difflib
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from .auth import whitelisted
from . import formatting, ocr, state, transcribe
from .openwebui import OpenWebUIClient, OpenWebUIError

log = logging.getLogger(__name__)

PREVIEW_PREFIX = "p:"  # p:<id>:<action>


@dataclass
class PendingPreview:
    source: str
    body: str
    duration_sec: int | None = None
    original_filename: str | None = None
    forwarded_from: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def _preview_keyboard(preview_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💾 Stoor", callback_data=f"{PREVIEW_PREFIX}{preview_id}:save"),
                InlineKeyboardButton("✏️ Wysig", callback_data=f"{PREVIEW_PREFIX}{preview_id}:edit"),
                InlineKeyboardButton("🗑️ Vee uit", callback_data=f"{PREVIEW_PREFIX}{preview_id}:discard"),
            ]
        ]
    )


def _pending(context: ContextTypes.DEFAULT_TYPE) -> dict[str, PendingPreview]:
    return context.user_data.setdefault("pending", {})


def _format_preview(kb_name: str, body: str) -> str:
    body_trimmed = body if len(body) <= 3500 else body[:3500] + "\n…(afgekap vir voorskou)"
    return f"💾 Stoor na: *{kb_name}*\n\n{body_trimmed}"


async def _require_kb(update: Update) -> state.UserSettings | None:
    user = update.effective_user
    settings = await state.get_settings(user.id) if user else None
    if not settings or not settings.default_kb_id:
        if update.effective_message:
            await update.effective_message.reply_text(
                "Kies eers 'n kennisbasis met /kb voordat jy iets stoor."
            )
        return None
    return settings


# ───────────────────────── commands ─────────────────────────

@whitelisted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = await state.get_settings(update.effective_user.id)
    kb = settings.default_kb_name if settings and settings.default_kb_name else "geen — gebruik /kb om te kies"
    await update.effective_message.reply_text(
        f"Hallo! Stuur stem, foto, teks of 'n PDF en ek stoor dit in jou Brein.\n\n"
        f"Huidige kennisbasis: *{kb}*",
        parse_mode="Markdown",
    )


@whitelisted
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Opdragte:\n"
        "/start — welkom + huidige KB\n"
        "/kb — lys KB's, kies een\n"
        "/kb <naam> — stel KB direk per naam\n"
        "/status — huidige KB + laaste 3 stoor-aksies\n"
        "/help — hierdie lys\n\n"
        "Stuur stem, foto, teks of dokument om iets te stoor."
    )


@whitelisted
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    settings = await state.get_settings(user_id)
    kb = settings.default_kb_name if settings and settings.default_kb_name else "geen"
    recents = await state.recent_uploads(user_id, limit=3)
    if recents:
        lines = [f"• [{r.source_type}] {r.filename} → {r.kb_name}" for r in recents]
        recent_block = "\n".join(lines)
    else:
        recent_block = "(nog niks gestoor nie)"
    await update.effective_message.reply_text(
        f"Huidige KB: *{kb}*\n\nLaaste 3 stoor-aksies:\n{recent_block}",
        parse_mode="Markdown",
    )


@whitelisted
async def cmd_kb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    async with OpenWebUIClient() as client:
        try:
            kbs = await client.list_knowledge_bases()
        except OpenWebUIError as exc:
            log.exception("Failed to list KBs")
            await update.effective_message.reply_text(f"Kan nie KB-lys kry nie: {exc}")
            return

    if not kbs:
        await update.effective_message.reply_text(
            "Geen kennisbasisse gevind nie. Skep eers een in Open WebUI."
        )
        return

    if args:
        query = " ".join(args).strip().lower()
        names = [kb.name for kb in kbs]
        # exact substring first, then difflib fuzzy
        exact = [kb for kb in kbs if query in kb.name.lower()]
        if len(exact) == 1:
            chosen = exact[0]
        elif len(exact) > 1:
            await update.effective_message.reply_text(
                "Meer as een KB pas: " + ", ".join(kb.name for kb in exact)
            )
            return
        else:
            close = difflib.get_close_matches(query, [n.lower() for n in names], n=1, cutoff=0.5)
            if not close:
                await update.effective_message.reply_text(f"Geen KB pas by '{query}' nie.")
                return
            chosen = next(kb for kb in kbs if kb.name.lower() == close[0])
        await state.set_default_kb(update.effective_user.id, chosen.id, chosen.name)
        await update.effective_message.reply_text(f"✅ KB gestel: *{chosen.name}*", parse_mode="Markdown")
        return

    buttons = [
        [InlineKeyboardButton(kb.name, callback_data=f"kb:{kb.id}")] for kb in kbs
    ]
    await update.effective_message.reply_text(
        "Kies 'n kennisbasis:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ───────────────────────── content handlers ─────────────────────────

async def _stage_preview(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    source: str,
    body: str,
    duration_sec: int | None = None,
    original_filename: str | None = None,
    forwarded_from: str | None = None,
) -> None:
    """Reply with preview + keyboard, store pending state."""
    settings = await _require_kb(update)
    if not settings:
        return
    if not body.strip():
        await update.effective_message.reply_text(
            "Geen teks gevind nie. Wil jy steeds stoor? Stuur die teks self, of /help."
        )
        return
    preview_id = uuid.uuid4().hex[:10]
    pending = PendingPreview(
        source=source,
        body=body,
        duration_sec=duration_sec,
        original_filename=original_filename,
        forwarded_from=forwarded_from,
    )
    _pending(context)[preview_id] = pending
    await update.effective_message.reply_text(
        _format_preview(settings.default_kb_name or "?", body),
        reply_markup=_preview_keyboard(preview_id),
        parse_mode="Markdown",
    )


@whitelisted
async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    voice = msg.voice or msg.audio
    if not voice:
        return
    await msg.chat.send_action("typing")
    duration = getattr(voice, "duration", None)
    with tempfile.TemporaryDirectory() as tmp:
        ogg_path = Path(tmp) / "voice.ogg"
        tg_file = await voice.get_file()
        await tg_file.download_to_drive(custom_path=str(ogg_path))
        try:
            transcript = await transcribe.transcribe_voice(ogg_path)
        except transcribe.AudioTooLarge:
            await msg.reply_text("Stem is te groot (oor 25 MB). Stuur 'n korter opname.")
            return
        except Exception:
            log.exception("Transcription failed")
            await msg.reply_text("Kon nie die stem transkribeer nie. Probeer weer.")
            return
    await _stage_preview(
        update,
        context,
        source=formatting.SOURCE_VOICE,
        body=transcript,
        duration_sec=duration,
    )


@whitelisted
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg.photo:
        return
    await msg.chat.send_action("typing")
    largest = msg.photo[-1]
    with tempfile.TemporaryDirectory() as tmp:
        jpg_path = Path(tmp) / "photo.jpg"
        tg_file = await largest.get_file()
        await tg_file.download_to_drive(custom_path=str(jpg_path))
        try:
            text = await ocr.ocr_image(jpg_path)
        except Exception:
            log.exception("OCR failed")
            await msg.reply_text("Kon nie die foto verwerk nie. Probeer weer.")
            return
    if not text.strip():
        # Per spec: still ask to save
        await _stage_preview(
            update,
            context,
            source=formatting.SOURCE_PHOTO,
            body="(geen teks in beeld gevind)",
        )
        return
    await _stage_preview(update, context, source=formatting.SOURCE_PHOTO, body=text)


@whitelisted
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg.text:
        return

    # Wysig edit-reply flow
    awaiting = context.user_data.get("awaiting_edit")
    if awaiting:
        preview_id = awaiting
        context.user_data.pop("awaiting_edit", None)
        pending = _pending(context).get(preview_id)
        if pending:
            pending.body = msg.text
            settings = await _require_kb(update)
            if not settings:
                return
            await msg.reply_text(
                _format_preview(settings.default_kb_name or "?", pending.body),
                reply_markup=_preview_keyboard(preview_id),
                parse_mode="Markdown",
            )
            return
        # fall through to treat as fresh text if pending was lost

    forwarded_from = _forwarded_label(update)
    settings = await _require_kb(update)
    if not settings:
        return

    user = update.effective_user
    md = formatting.build_markdown(
        body=msg.text,
        source=formatting.SOURCE_TEXT,
        kb_name=settings.default_kb_name or "?",
        telegram_user=user.first_name or user.username or str(user.id),
        telegram_user_id=user.id,
        forwarded_from=forwarded_from,
    )
    filename = formatting.build_filename(formatting.SOURCE_TEXT, msg.text)
    ok = await _do_upload(
        update=update,
        kb_id=settings.default_kb_id,
        kb_name=settings.default_kb_name or "?",
        filename=filename,
        content=md.encode("utf-8"),
        source_type="text",
    )
    if ok:
        await msg.reply_text(f"✅ Gestoor in {settings.default_kb_name}")


@whitelisted
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    doc = msg.document
    if not doc:
        return
    settings = await _require_kb(update)
    if not settings:
        return
    await msg.chat.send_action("upload_document")
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / (doc.file_name or "document.bin")
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(custom_path=str(local))
        content = local.read_bytes()
    filename = doc.file_name or local.name
    content_type = doc.mime_type or "application/octet-stream"
    ok = await _do_upload(
        update=update,
        kb_id=settings.default_kb_id,
        kb_name=settings.default_kb_name or "?",
        filename=filename,
        content=content,
        source_type="document",
        content_type=content_type,
    )
    if ok:
        await msg.reply_text(f"✅ Gestoor in {settings.default_kb_name}")


def _forwarded_label(update: Update) -> str | None:
    msg = update.effective_message
    if not msg:
        return None
    if msg.forward_origin is None:
        # python-telegram-bot v21 uses forward_origin; fall back to older attrs just in case
        sender = getattr(msg, "forward_from", None) or getattr(msg, "forward_sender_name", None) or getattr(msg, "forward_from_chat", None)
        if not sender:
            return None
        if hasattr(sender, "full_name"):
            return sender.full_name
        if hasattr(sender, "title"):
            return sender.title
        return str(sender)
    origin = msg.forward_origin
    for attr in ("sender_user", "sender_chat", "chat"):
        node = getattr(origin, attr, None)
        if node is not None:
            for label_attr in ("full_name", "title", "username"):
                v = getattr(node, label_attr, None)
                if v:
                    return v
    return getattr(origin, "sender_user_name", None) or "forwarded"


# ───────────────────────── callbacks ─────────────────────────

@whitelisted
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    data = query.data

    if data.startswith("kb:"):
        kb_id = data.split(":", 1)[1]
        async with OpenWebUIClient() as client:
            try:
                kbs = await client.list_knowledge_bases()
            except OpenWebUIError as exc:
                await query.edit_message_text(f"Kan nie KB-lys kry nie: {exc}")
                return
        chosen = next((kb for kb in kbs if kb.id == kb_id), None)
        if not chosen:
            await query.edit_message_text("KB nie meer beskikbaar nie.")
            return
        await state.set_default_kb(update.effective_user.id, chosen.id, chosen.name)
        await query.edit_message_text(f"✅ KB gestel: {chosen.name}")
        return

    if data.startswith(PREVIEW_PREFIX):
        rest = data[len(PREVIEW_PREFIX):]
        try:
            preview_id, action = rest.rsplit(":", 1)
        except ValueError:
            return
        pending = _pending(context).get(preview_id)
        if not pending:
            await query.edit_message_text("Voorskou verval. Stuur weer.")
            return

        if action == "discard":
            _pending(context).pop(preview_id, None)
            try:
                await query.message.delete()
            except Exception:
                await query.edit_message_text("🗑️ Verwyder.")
            return

        if action == "edit":
            context.user_data["awaiting_edit"] = preview_id
            await query.edit_message_text(
                "✏️ Stuur die regstelling as 'n teksboodskap. Ek vervang die voorskou met jou weergawe."
            )
            return

        if action == "save":
            settings = await state.get_settings(update.effective_user.id)
            if not settings or not settings.default_kb_id:
                await query.edit_message_text("Geen KB gekies nie. Gebruik /kb.")
                return
            user = update.effective_user
            md = formatting.build_markdown(
                body=pending.body,
                source=pending.source,
                kb_name=settings.default_kb_name or "?",
                telegram_user=user.first_name or user.username or str(user.id),
                telegram_user_id=user.id,
                duration_sec=pending.duration_sec,
                original_filename=pending.original_filename,
                forwarded_from=pending.forwarded_from,
            )
            filename = formatting.build_filename(pending.source, pending.body)
            source_type = pending.source.removeprefix("telegram-")
            try:
                async with OpenWebUIClient() as client:
                    await client.upload_and_attach(
                        kb_id=settings.default_kb_id,
                        filename=filename,
                        content=md.encode("utf-8"),
                    )
                await state.record_upload(
                    user_id=user.id,
                    kb_id=settings.default_kb_id,
                    kb_name=settings.default_kb_name or "?",
                    filename=filename,
                    source_type=source_type,
                )
                _pending(context).pop(preview_id, None)
                await query.edit_message_text(f"✅ Gestoor in {settings.default_kb_name}")
            except OpenWebUIError as exc:
                log.exception("Save failed")
                await query.edit_message_text(f"⚠️ Stoor het misluk: {exc}")
            return


# ───────────────────────── shared upload helper ─────────────────────────

async def _do_upload(
    *,
    update: Update,
    kb_id: str,
    kb_name: str,
    filename: str,
    content: bytes,
    source_type: str,
    content_type: str = "text/markdown",
) -> bool:
    try:
        async with OpenWebUIClient() as client:
            await client.upload_and_attach(
                kb_id=kb_id,
                filename=filename,
                content=content,
                content_type=content_type,
            )
    except OpenWebUIError as exc:
        log.exception("Upload failed")
        await update.effective_message.reply_text(f"⚠️ Stoor het misluk: {exc}")
        return False
    await state.record_upload(
        user_id=update.effective_user.id,
        kb_id=kb_id,
        kb_name=kb_name,
        filename=filename,
        source_type=source_type,
    )
    return True
