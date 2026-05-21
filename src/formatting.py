"""Filename + frontmatter builders. Pure functions, no I/O."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SOURCE_VOICE = "telegram-voice"
SOURCE_PHOTO = "telegram-photo"
SOURCE_TEXT = "telegram-text"
SOURCE_DOCUMENT = "telegram-document"

_TZ = ZoneInfo("Africa/Johannesburg")


def now_local() -> datetime:
    return datetime.now(_TZ)


def slugify(text: str, max_words: int = 6) -> str:
    """First N words → lowercase, hyphenated, ASCII-only.

    Strips accents, drops anything that isn't [a-z0-9]. Returns "untitled"
    for empty input so a filename is always producible.
    """
    if not text:
        return "untitled"
    normalised = unicodedata.normalize("NFKD", text)
    ascii_text = normalised.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    words = re.findall(r"[a-z0-9]+", ascii_text)
    if not words:
        return "untitled"
    return "-".join(words[:max_words])


def build_filename(source: str, content: str, when: datetime | None = None) -> str:
    """`YYYY-MM-DD_HHMM_{source}_{slug}.md`."""
    when = when or now_local()
    stamp = when.strftime("%Y-%m-%d_%H%M")
    short_source = source.removeprefix("telegram-")
    return f"{stamp}_{short_source}_{slugify(content)}.md"


def _yaml_escape(value: str) -> str:
    """Minimal YAML scalar escaping. Quote if value contains chars that would
    confuse a YAML parser; otherwise return bare."""
    needs_quote = any(c in value for c in ":#\n\"'") or value.strip() != value or not value
    if not needs_quote:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def build_frontmatter(
    *,
    source: str,
    kb_name: str,
    telegram_user: str,
    telegram_user_id: int,
    when: datetime | None = None,
    duration_sec: int | None = None,
    original_filename: str | None = None,
    forwarded_from: str | None = None,
) -> str:
    when = when or now_local()
    lines = ["---", f"date: {when.isoformat(timespec='seconds')}", f"source: {source}"]
    lines.append(f"telegram_user: {_yaml_escape(telegram_user)}")
    lines.append(f"telegram_user_id: {telegram_user_id}")
    lines.append(f"kb: {_yaml_escape(kb_name)}")
    if duration_sec is not None:
        lines.append(f"duration_sec: {duration_sec}")
    if original_filename is not None:
        lines.append(f"original_filename: {_yaml_escape(original_filename)}")
    if forwarded_from is not None:
        lines.append(f"forwarded_from: {_yaml_escape(forwarded_from)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def build_markdown(
    *,
    body: str,
    source: str,
    kb_name: str,
    telegram_user: str,
    telegram_user_id: int,
    when: datetime | None = None,
    duration_sec: int | None = None,
    original_filename: str | None = None,
    forwarded_from: str | None = None,
) -> str:
    fm = build_frontmatter(
        source=source,
        kb_name=kb_name,
        telegram_user=telegram_user,
        telegram_user_id=telegram_user_id,
        when=when,
        duration_sec=duration_sec,
        original_filename=original_filename,
        forwarded_from=forwarded_from,
    )
    return fm + "\n" + body.strip() + "\n"
