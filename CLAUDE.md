# Project notes for Claude

Automated faceless video channel (tech & future niche, English). Python 3.12 in `.venv` (made with uv).
GitHub Actions (`.github/workflows/daily.yml`) runs `python -m pipeline auto` 6×/day. Each run does ONE job
from `config.yaml → channel.job_order`. State lives in `data/plans/<date>.json` and is committed by the bot.

- Decisions (from the user): original scripts only (no reuploads), fully automatic posting (no Telegram approval),
  1 long + 5 Shorts per day, public repo, official APIs only (no browser automation, no instagrapi).
- `pipeline/sample_plan.json` + `python -m pipeline test` = offline render test with no keys.
- Kokoro needs Python ≤3.12. faster-whisper gets raw samples (newer PyAV breaks its file reader).
- Reddit blocks bots (403), so it is off in config.
- The repo is public: never commit downloaded article text (`facts` is removed before the plan is saved),
  `.env`, `client_secret.json` or tokens.
- No Metro or simulators in this project, so the multi-project port and device rules don't apply. Rendering
  uses half the CPU cores.
- Video engine: Remotion project in `remotion/` (React templates: footage, headline/stat/compare/list/quote/
  outro/chapter cards, captions, progress bar). Python writes `props.json` (shot list) and calls
  `npx remotion render`; FFmpeg mixes the sound. On failure it falls back to the FFmpeg+ASS engine.
  On this Mac, Remotion's default headless browser never starts: renders use `--chrome-mode=chrome-for-testing`.
- Voice: Gemini TTS (~10 requests/day free), Kokoro backup. Captions: wav2vec2 forced alignment (align.py).
- Google retires old Gemini model names for new keys (2.5-flash is gone): keep model lists in config.yaml current.
