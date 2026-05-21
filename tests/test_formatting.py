from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.formatting import (
    SOURCE_DOCUMENT,
    SOURCE_PHOTO,
    SOURCE_TEXT,
    SOURCE_VOICE,
    build_filename,
    build_frontmatter,
    build_markdown,
    slugify,
)

TZ = ZoneInfo("Africa/Johannesburg")
FIXED = datetime(2026, 5, 21, 14, 32, 7, tzinfo=TZ)


class TestSlugify:
    def test_lowercases_and_hyphenates(self):
        assert slugify("Hello World Foo") == "hello-world-foo"

    def test_takes_first_six_words(self):
        text = "een twee drie vier vyf ses sewe agt"
        assert slugify(text) == "een-twee-drie-vier-vyf-ses"

    def test_strips_accents_to_ascii(self):
        assert slugify("Môre só") == "more-so"

    def test_drops_punctuation(self):
        assert slugify("Hello, world! How's it?") == "hello-world-how-s-it"

    def test_empty_returns_untitled(self):
        assert slugify("") == "untitled"

    def test_only_punctuation_returns_untitled(self):
        assert slugify("!!! ??? ...") == "untitled"

    def test_unicode_outside_ascii_falls_back(self):
        assert slugify("日本語のみ") == "untitled"

    def test_numbers_preserved(self):
        assert slugify("Versie 2 punt 1") == "versie-2-punt-1"


class TestBuildFilename:
    def test_voice_source_short_form(self):
        name = build_filename(SOURCE_VOICE, "Hallo wereld toets", when=FIXED)
        assert name == "2026-05-21_1432_voice_hallo-wereld-toets.md"

    def test_photo_source(self):
        name = build_filename(SOURCE_PHOTO, "Ontvangsbewys van pick n pay", when=FIXED)
        assert name == "2026-05-21_1432_photo_ontvangsbewys-van-pick-n-pay.md"

    def test_document_source(self):
        name = build_filename(SOURCE_DOCUMENT, "Some pdf", when=FIXED)
        assert name == "2026-05-21_1432_document_some-pdf.md"

    def test_text_source(self):
        name = build_filename(SOURCE_TEXT, "snel nota oor iets", when=FIXED)
        assert name == "2026-05-21_1432_text_snel-nota-oor-iets.md"


class TestBuildFrontmatter:
    def test_minimal_voice(self):
        fm = build_frontmatter(
            source=SOURCE_VOICE,
            kb_name="Homeschool",
            telegram_user="Marnix",
            telegram_user_id=42,
            when=FIXED,
            duration_sec=47,
        )
        assert fm.startswith("---\n")
        assert fm.endswith("---\n")
        assert "date: 2026-05-21T14:32:07+02:00" in fm
        assert "source: telegram-voice" in fm
        assert "telegram_user: Marnix" in fm
        assert "telegram_user_id: 42" in fm
        assert "kb: Homeschool" in fm
        assert "duration_sec: 47" in fm

    def test_quotes_values_with_colons(self):
        fm = build_frontmatter(
            source=SOURCE_TEXT,
            kb_name="KB: with colon",
            telegram_user="Marnix",
            telegram_user_id=1,
            when=FIXED,
        )
        assert 'kb: "KB: with colon"' in fm

    def test_document_includes_original_filename(self):
        fm = build_frontmatter(
            source=SOURCE_DOCUMENT,
            kb_name="Homeschool",
            telegram_user="Marnix",
            telegram_user_id=1,
            when=FIXED,
            original_filename="aantekeninge.pdf",
        )
        assert "original_filename: aantekeninge.pdf" in fm

    def test_forwarded_from_included(self):
        fm = build_frontmatter(
            source=SOURCE_TEXT,
            kb_name="Homeschool",
            telegram_user="Marnix",
            telegram_user_id=1,
            when=FIXED,
            forwarded_from="Some Channel",
        )
        assert "forwarded_from: Some Channel" in fm

    def test_omits_optional_fields_when_absent(self):
        fm = build_frontmatter(
            source=SOURCE_TEXT,
            kb_name="Homeschool",
            telegram_user="Marnix",
            telegram_user_id=1,
            when=FIXED,
        )
        assert "duration_sec" not in fm
        assert "original_filename" not in fm
        assert "forwarded_from" not in fm


class TestBuildMarkdown:
    def test_frontmatter_then_blank_line_then_body(self):
        md = build_markdown(
            body="Dit is die nota.",
            source=SOURCE_TEXT,
            kb_name="Homeschool",
            telegram_user="Marnix",
            telegram_user_id=1,
            when=FIXED,
        )
        assert md.startswith("---\n")
        assert "\n---\n\nDit is die nota.\n" in md

    def test_body_is_stripped(self):
        md = build_markdown(
            body="   \n\nfoo\n\n   ",
            source=SOURCE_TEXT,
            kb_name="Homeschool",
            telegram_user="Marnix",
            telegram_user_id=1,
            when=FIXED,
        )
        assert md.endswith("foo\n")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
