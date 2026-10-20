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
- **Look:** keep the full Remotion engine for every video (no plain engine). Long videos 25 fps, Shorts 30 fps.
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

## Where things stand (2026-10-20 evening)
- **Modal works but its free limit is tiny for this account:** after ~$1.03 of tests Modal said "Workspace has
  exceeded its spend limit" (no card on file, so nothing can be charged). Measured on 8 cores: the 8.6-min
  history video drew in 624 s once and 3182 s another time; mix 316 s; ~$0.44 per long video. Full 6+9/day
  would be ~$30-90/month there. modal_app.py stays (job/plan/work/tick/switch/dashboard) for later.
- **Owner wants free only.** Next: Oracle Always Free (2 ARM cores, 12 GB since the 2026 cut; est. 3-6 long +
  6-9 Shorts/day). Owner must sign up (card check) and create the VM; then set it up like modal_app.py's image.
  Hostinger KVM 4 (~$10-15/mo, ~double on renewal) is the paid backup.
- Review files on the Mac: out/review/history-0/ (long.mp4 = cloud render BEFORE the picture fixes; short_4 =
  with Wikipedia paintings; short_5 = before). The re-made long video with paintings is NOT made yet.
- Fixed today: FFmpeg mix freeze (2-pass + timeouts), cloud FFmpeg 5.1 stereo format, Wikimedia previews (UA +
  standard sizes: Wikipedia photos were never approved before), era-aware picture check, cloud core count.

## Next steps
1. DONE: Modal account, `modal token new`, `modal_app.py` (job / plan / tick timer / switch / dashboard),
   `scripts/modal_secrets.py`. Measure time + cost of the first cloud job, then decide 25 fps / lighter blur.
2. `modal deploy modal_app.py` switches on the 20-min timer (makes videos, holds them for review). Only
   after the owner's go. Optional: ntfy.sh phone notifications.
3. Speed/cost: blurred backgrounds via FFmpeg instead of CSS blur; long videos at 25 fps.
4. Plan + render one full day's batch on Modal → owner review.
5. Then: owner picks 4 channel names, creates channels; `scripts/youtube_auth.py` per channel →
   YT_REFRESH_TOKEN_<SPACE|HISTORY|BUSINESS|GEOGRAPHY>; switch on posting.
6. Later: learning loop (YouTube Analytics; scope already added), Instagram/TikTok (accounts needed;
   TikTok/Facebook don't pay creators in Pakistan), Archive.org footage for history.
