# brein-bot

Telegram bot that captures voice / photo / text / PDF into Open WebUI knowledge bases at `https://brein.marnixboersema.co.za`.

- **Voice** → OpenAI `gpt-4o-transcribe` (Afrikaans) → preview → save
- **Photo** → OpenAI `gpt-4o` vision OCR → preview → save
- **Text** → straight to KB (no preview)
- **Document / PDF** → passed through to Open WebUI as-is

Runs as a Docker container alongside the existing Open WebUI stack. Long polling — no inbound webhook.

---

## 1 — Create the Telegram bot

In Telegram, talk to [@BotFather](https://t.me/BotFather):

```
/newbot
→ name: Brein
→ username: brein_boersema_bot  (must end in `bot`)
```

Save the `TELEGRAM_BOT_TOKEN` it gives you.

While you're there, set the commands menu so Marnix and Clarinda get autocomplete:

```
/setcommands
→ pick the bot
→ paste:
start - Welkom en huidige KB
kb - Kies kennisbasis
status - KB + laaste 3 stoor-aksies
help - Lys van opdragte
```

## 2 — Get the Open WebUI API key

Sign in to `https://brein.marnixboersema.co.za` as the admin user → **Settings → Account → API keys → Create new key**. Copy it.

## 3 — Find your Telegram user IDs

Forward any message from yourself / Clarinda to [@userinfobot](https://t.me/userinfobot) — it replies with the numeric user ID. Add each ID, comma-separated, to `ALLOWED_TELEGRAM_USER_IDS`.

## 4 — Configure env vars

On the VPS:

```bash
cd /opt
git clone <this-repo> brein-bot
cd brein-bot
cp .env.example .env
nano .env
```

Fill in every value:

| var | what |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | from BotFather |
| `ALLOWED_TELEGRAM_USER_IDS` | comma-separated numeric IDs |
| `OPENAI_API_KEY` | sk-… key with access to `gpt-4o` + `gpt-4o-transcribe` |
| `OPENWEBUI_BASE_URL` | leave as `http://open-webui:8080` for the internal hop |
| `OPENWEBUI_API_KEY` | from Open WebUI Settings → Account |
| `LOG_LEVEL` | `INFO` (or `DEBUG` while testing) |
| `TZ` | `Africa/Johannesburg` |

## 5 — Start it

The bot's compose file joins Open WebUI's existing network. On the brein VPS, Open WebUI lives at `/opt/brein` so its Compose project name is `brein` and its default network is `brein_default` — which is what `docker-compose.yml` here references. Verify with:

```bash
docker network ls | grep brein
```

If the network name differs on your host, edit the `networks:` block in `docker-compose.yml`.

Then:

```bash
docker compose up -d --build
docker compose logs -f brein-bot
```

You should see `Brein-bot starting (long polling)`. Open Telegram, message your bot, send `/start`.

## 6 — First-time use

1. `/kb` — pick a knowledge base. (Create it first in Open WebUI if the list is empty.)
2. Send a voice note in Afrikaans → preview appears → `💾 Stoor`.
3. `/status` — confirm it was saved.

---

## File format

Every captured item lands in Open WebUI as a Markdown file:

```
2026-05-21_1432_voice_hallo-wereld-toets.md
```

with frontmatter:

```yaml
---
date: 2026-05-21T14:32:00+02:00
source: telegram-voice
telegram_user: Marnix
telegram_user_id: 123456789
kb: Homeschool
duration_sec: 47
---
```

Documents (PDFs etc.) keep their original filename and are uploaded raw — Open WebUI's own pipeline does the extraction.

---

## Day-2 ops

State lives in the `brein-bot-data` Docker volume (`/data/state.db` inside the container). Back it up the same way as Open WebUI's volume.

Logs: `docker compose logs -f brein-bot`.

Update Open WebUI's API key: edit `.env`, `docker compose up -d`.

---

## Troubleshooting

**`/kb` returns "Geen kennisbasisse gevind nie"** — the API key is wrong, or no KBs exist. Check Open WebUI Settings → Account → API keys. Test from the VPS host:

```bash
docker exec brein-bot sh -c 'curl -s -H "Authorization: Bearer $OPENWEBUI_API_KEY" $OPENWEBUI_BASE_URL/api/v1/knowledge/'
```

**Transcription empty / "Kon nie die stem transkribeer nie"** — Telegram voice notes are `.ogg` (Opus). The OpenAI endpoint accepts that, so an empty transcript usually means the audio is silent or corrupt. Test with a louder, clearer message. Files > 25 MB are rejected with a polite message.

**Bot says "Stoor het misluk"** — Open WebUI processing timed out or returned an error. Check `docker compose logs -f brein-bot` for the underlying status code. Most common: Open WebUI restarting; retry after a minute.

**Bot doesn't reply at all** — check the long-polling connection is up:

```bash
docker compose logs brein-bot | tail -50
```

If you see `Conflict: terminated by other getUpdates request`, another bot instance is running with the same token — stop it.

**Bot refuses you with "Jammer, jy het nie toegang ..."** — your numeric user ID isn't in `ALLOWED_TELEGRAM_USER_IDS`. Forward a message to @userinfobot to get yours; update `.env`; `docker compose up -d`.

---

## Run tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
pytest tests/ -v
```
