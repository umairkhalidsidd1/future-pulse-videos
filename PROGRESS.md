# Progress — video factory (updated 2026-10-20)

Read this + CLAUDE.md (project notes and "Lessons learned") first in a new session.

## Decisions (by the owner)
- **4 niches / 4 channels:** space & science, history documentaries, business & company stories,
  geography & geopolitics. Channel names and accounts: decided AFTER the system is finished.
  (Old "Reality Shockwaves" tech channel is dropped; its YouTube login still works for tests.)
- **Volume:** 6 long videos + 9 Shorts per day (space 2+3, history 2+3, business 1+2, geography 1+1).
  Shorts are cut from the best chapters of the long videos. Long videos must be 8+ minutes (mid-roll ads).
- **Budget: free only.** Voice: Gemini TTS for space ("Charon") and history ("Gacrux"), Kokoro for business
  ("am_michael") and geography ("bf_emma"). A Gemini channel WAITS when its voice quota is used up (never swaps).
- **Free AI text:** Gemini (many models, each its own quota) + Groq (key in .env, gpt-oss-120b) as backup.
- **Hosting:** the Mac is too slow (the 8.6-min history video took 25+ min just to draw). Owner chose
  **Modal** (free $30/month credits; est. ~$15-20 use; ~1-2 h/day). Backups: Contabo ~€7.50, OVH ~$12.
- **Review first:** one full day's batch must be reviewed by the owner before posting is switched on.
- Delete rendered videos from disk 2 days after all of that day's uploads succeeded (YouTube keeps them).
- Owner wants: simple English, plain reports, a dashboard/notifications showing when work runs,
  continuous research and learning from mistakes (add to CLAUDE.md "Lessons learned").

## What is built (code in pipeline/, remotion/)
- `factory.py` — multi-channel daily flow: plan (topics → research → chapter scripts → fact-check),
  long video, Shorts from chapters (reuse voice + exact timings), scheduled YouTube upload (publishAt),
  cleanup, VoiceWait handling. Commands: `python -m pipeline factory | factory-plan | factory-batch |
  factory-job <id> | dashboard`.
- `topics.py` — trend + evergreen topics (Wikipedia most-read, on-this-day, niche RSS, AI ideas),
  duplicate guard (365 days), Wikipedia research.
- `writer.py` — long videos written IN PARTS (outline → each chapter → intro/outro), 7-9 stand-alone chapters,
  proof cards (headline, stat, compare, list, quote, slam, map, timeline, chart), card source checks,
  batched fact-check.
- `tts.py` (Gemini/Kokoro per channel, full-recording check), `align.py` (wav2vec2 exact word timing),
  `stock.py` (Pixabay video+photos, Wikipedia/Commons PD/CC0/CC BY photos, NASA; AI picture check 0-10;
  polite rate limit), `render.py` + `remotion_render.py` (Remotion engine, FFmpeg sound mix with mood music,
  word-timed music volume, SFX, grain/vignette, exact −14 LUFS), `status.py` + `dashboard.py`
  (out/dashboard.html, Mac notifications, PAUSE switch at data/PAUSE, usage counters).
- `scripts/mac_timer.py` — launchd timer (written, NOT installed; superseded by Modal plan).
- Remotion templates in `remotion/src` incl. `templates/Infographics.tsx` (map with Natural Earth PD data,
  timeline, chart).

## Running right now
- Test render of `long:history-0` (Battle of Navarino, 8.6 min, 1,276 words) on the Mac. Log:
  `out/history_long.log`; done marker `out/history_long.done`. After it: render its 2 Shorts
  (`short:history-0:5`, `short:history-0:4`) and review.

## Next steps
1. Owner creates a Modal account (modal.com/signup was opened in Chrome). Then: `pip install modal`,
   `modal token new` (owner approves in browser).
2. Build `modal_app.py`: image (Python 3.12, FFmpeg, Node 22, Chrome deps, requirements, remotion npm),
   a Modal Volume for data/, out/, models/, cache/ and assets/music; secrets (ask owner before uploading
   keys); a 15-min cron that runs one job (max 1 container); dashboard as a private web endpoint
   (token in URL); optional ntfy.sh phone notifications.
3. Speed/cost: blurred backgrounds via FFmpeg instead of CSS blur; long videos at 25 fps.
4. Plan + render one full day's batch on Modal → owner review.
5. Then: owner picks 4 channel names, creates channels; `scripts/youtube_auth.py` per channel →
   YT_REFRESH_TOKEN_<SPACE|HISTORY|BUSINESS|GEOGRAPHY>; switch on posting.
6. Later: learning loop (YouTube Analytics; scope already added), Instagram/TikTok (accounts needed;
   TikTok/Facebook don't pay creators in Pakistan), Archive.org footage for history.
