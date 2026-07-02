# Meow_Bot Agent Guide

## Project Scope

- This is a Discord bot built with Python 3.13 and discord.py 2.x.
- Production runs in Docker on Linux. Windows is a local development environment only.
- Keep dependency/runtime upgrades separate from unrelated architecture refactors. Explain and discuss worthwhile hardening before including it in an upgrade task.
- Do not commit changes unless the user explicitly asks for a commit.

## Runtime Notes

- Install dependencies with `python -m pip install -r requirements.txt`.
- Run locally with `python main.py` and an untracked `.env` based on `.env.template`.
- Do not add `WindowsSelectorEventLoopPolicy`. An older Windows Service workaround was abandoned, and the music downloader relies on asyncio subprocess support.
- Never print or commit `DISCORD_BOT_TOKEN` or the contents of `.env`.

## Architecture

- `main.py` creates the bot, loads cogs, registers error handlers, and starts the process.
- `cogs/` contains Discord command modules. Each loadable cog must expose `async def setup(bot)`.
- `module/music_player/` contains reusable player, queue, downloader, FFmpeg, UI, and error-handling code.
- The music player uses asyncio locks. Avoid nested acquisition of the same lock and keep slow network or subprocess work outside critical sections.
- Preserve the direct `commands.Bot` style in `main.py` unless lifecycle restructuring is explicitly in scope. If startup work must move out of `on_ready`, discuss the behavioral reason and tradeoffs first.

## Change Guidelines

- Preserve Chinese command names and user-facing language unless wording changes are requested.
- Prefer public discord.py APIs such as `display_avatar`; use REST fetches only when cache lookup can legitimately miss.
- Avoid direct mutation of private queue state. Use the queue's public methods.
- Keep Docker and local-development behavior aligned where practical, while treating Linux containers as the deployment target.

## Verification

- Run `python -m compileall main.py cogs module` after Python edits.
- Run `python -m pip check` after dependency changes.
- Import the main modules or run focused checks for the changed area when a full bot login is unavailable.
- A live Discord startup requires a valid token and should not be attempted unless explicitly requested.
