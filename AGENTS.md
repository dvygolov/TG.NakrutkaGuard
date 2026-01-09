# Repository Guidelines

## Project Structure & Module Organization
- `bot/` contains the Python source code for the Telegram bot.
- `bot/handlers/` holds chat command and event handlers (setup, members, captcha, moderation).
- `bot/utils/` provides shared helpers (detector, scoring, captcha generation, logging).
- `bot/database.py` wraps SQLite access via `aiosqlite`.
- `data/` stores the SQLite database (default `data/bot.db`).
- `logs/` stores per-chat log files.
- Root scripts: `build.sh`, `start.sh`, `stop.sh`, `install-service.sh`, `update.sh`.

## Build, Test, and Development Commands
- `./build.sh` creates `.venv` and installs `requirements.txt`.
- `.venv/bin/python -m bot.main` runs the bot in the foreground.
- `./start.sh` runs the bot via `nohup` and writes `nakrutkaguard.log`.
- `./stop.sh` stops running bot processes (`pgrep -f "bot.main"`).
- `./install-service.sh` installs and starts a systemd service (Linux).
- `./update.sh` fast-forwards git, rebuilds deps, restarts systemd service.

## Coding Style & Naming Conventions
- Python 3.9+; use 4-space indentation and `async`/`await`.
- Prefer `snake_case` for functions/variables and `PascalCase` for classes.
- Keep handler logic in `bot/handlers/` and shared logic in `bot/utils/`.
- No formatting/linting tool is enforced in this repo; keep changes minimal and readable.

## Testing Guidelines
- There is no test framework configured.
- Ad-hoc checks live in root scripts: `test_username_analysis.py` and `test_weird_name.py`.
- Run them directly:
  - `.venv/bin/python test_username_analysis.py`
  - `.venv/bin/python test_weird_name.py`

## Commit & Pull Request Guidelines
- Recent commits use short, imperative messages (e.g., "Add ...", "Replace ...").
- Keep commit subjects concise and describe the change clearly.
- PRs should include a brief summary, affected modules/paths, and any setup or config changes (e.g., `.env`, DB schema).

## Security & Configuration Tips
- Configure secrets in `.env` (see `.env.example`).
- Required: `BOT_TOKEN`, `ADMIN_IDS`.
- Never commit real tokens or production DB files.
