# Future Pulse: daily faceless video machine

Every day this makes **1 long YouTube video** ("Top 5 tech stories today") and **5 vertical Shorts**.
It posts the Shorts to YouTube Shorts, Instagram Reels and TikTok. It is free and runs on GitHub Actions.
It writes its own scripts, so there is no reuploading of other people's videos.

**Start here: [SETUP.md](SETUP.md)**

| Step | Tool (free) |
|---|---|
| Trending stories | Hacker News, Google Trends, Google News, tech RSS feeds |
| Scripts, hooks, fact-check | Gemini (Groq as backup) |
| Voice | Kokoro TTS (Apache-2.0) |
| Footage | Pexels, Pixabay |
| Word-by-word captions | faster-whisper + ASS subtitles |
| Editing | FFmpeg |
| Upload | Official YouTube, Instagram Graph and TikTok Content Posting APIs |

## Commands (on your Mac)

```bash
.venv/bin/python -m pipeline test
```
Makes 2 sample videos in `out/test/`. It needs no keys and posts nothing.

```bash
.venv/bin/python scripts/check_setup.py
```
Checks every key.

```bash
.venv/bin/python -m pipeline render short:0
```
Writes today's real scripts and renders Short 0 without posting.

```bash
.venv/bin/python -m pipeline auto
```
Does the next job of today, including posting.

All settings (niche, voice, schedule order, caption colors, privacy) are in `config.yaml`.
