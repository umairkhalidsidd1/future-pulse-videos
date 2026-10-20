# Project notes for Claude

Automated faceless video factory: 4 channels (space, history, business, geography), English. Python 3.12 in `.venv` (made with uv).
Runs on Modal (`modal_app.py`: image, volume "video-factory", secret "video-factory-keys", 20-min timer that does
ONE job). State lives in `data/plans/<date>.json` on the volume. The old GitHub workflow is disabled.

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

## Lessons learned (read before changing things; add a line every time something goes wrong)
- Long scripts: Gemini writes only ~700 words per answer, even when told it's too short. Write long videos
  in parts (outline -> chapters -> intro/outro), never in one request.
- Hidden retries waste quota and time: every rejected AI answer must be logged with its reason, the reason sent
  back on the next try, and tries capped (llm.ask_json max_tries).
- Save after every finished step (scripts, plans). Saving only at the end once lost 3 finished scripts.
- Free Gemini quotas reset at midnight US Pacific (noon in Pakistan). Heavy testing days use them up; test with
  one job, not whole batches. Add the free Groq key as a backup before going live.
- Gemini model names get retired for new keys (gemini-2.5-flash vanished). List models via the API when a
  model 404s and update config.yaml.
- Gemini TTS can read its instructions out loud or skip sentences: keep the "#### TRANSCRIPT" layout, a SHORT
  style line, <=240 words per request, and the full-recording check (tts._check_full).
- Remotion's default headless browser never starts on this Mac: use --chrome-mode=chrome-for-testing (done in
  remotion_render.py). Edits to remotion/src are safe while a render runs only after its bundling finished.
- Before removing/renaming a config key, grep the whole pipeline for it (removing channel.niche broke imports).
- Plan "day" is New York time: late at night in Pakistan it's still the previous day in the plan.
- FFmpeg: never "-ss" on a photo input (gives no frame). One-pass loudnorm lands 1-2 dB off: measure + correct.
- Stock footage: Pixabay returns cartoons/unrelated clips; brand names get misread (Apple -> fruit). Keep
  video_type=film, tag filter, the AI picture check with 0-10 scores and the brand rule.
- Wide clips in tall Shorts: never hard-crop (looks over-zoomed); use the blurred-background layout.
- Captions: the bouncing active word eats the gap; keep >=48 px word gap in Shorts.
- commons.wikimedia.org doesn't resolve on this network: use en.wikipedia.org's API for Commons files.
- NASA images: "~large" doesn't always exist; try "~medium" and "~orig".
- GitHub CI: `npm ci` fails on small lock differences (use npm install); `git pull --rebase` needs --autostash.
- GitHub's free runners may not be used as a render farm (terms): the factory runs on the Mac (launchd).
- Gemini "lite" models write ~90 words per chapter whatever you ask; best models have tiny free quotas (~20/day).
  Design for it: many short chapters (7-9 x ~110 words), accept >=70 words. Google also returns 503 "high
  demand" at busy hours: wait ~20 s and retry, then try the next model.
- Long videos must be 8+ minutes: only then does YouTube allow mid-video ads.
- Pixabay returns 429 when downloads go too fast (a long video needs ~150 files): stock._polite keeps it to ~1
  request per 0.8 s and retries after 20 s.
- FFmpeg froze (0% CPU, no error, 75 min) at the end of an 8.6-min video when ONE graph mixed the picture and
  3 sound inputs with -t. Now: sound mixed first to a wav, then picture + wav; every FFmpeg/Remotion run has a
  timeout so a freeze can't block the factory. If a process sits at 0% CPU, `sample <pid>` shows what it waits on.
- Remotion "delayRender ... Setting the current frame ... not cleared" = the machine was too busy (Mac load 7-29
  from other projects), not a bad clip (the clip on screen was a normal 10 s file). It retries with half the tabs.
- In the cloud, os.cpu_count() and the load average are the whole host's, not ours: use config.workers()
  (FACTORY_CPUS) and skip the busy-Mac check there.
- Posting off (FACTORY_UPLOAD=0 / no POSTING_ON switch) marks jobs "held for review", else they re-ran every tick.
- `modal run`/`deploy` copies the project while it builds: editing ANY copied file during that time stops the
  build ("was modified during build process"). Notes (*.md) are no longer copied; don't edit code mid-build.
- Modal: a program sees only the cores REQUESTED (cpu=(1,8) showed 1 core), and Python's counts there are wrong
  (24 on an 8-core machine). modal_app._cores() counts like Remotion (min of nproc and Node availableParallelism).
- Modal fires schedules even during `modal run` tests, and re-runs a call whose container you stop. The timer
  exists only with `FACTORY_DEPLOY=1 modal deploy`; never run planning and a job at the same time (same plan file).
- The cloud's FFmpeg is Debian's 5.1 (Mac has 8): audio graphs must force one format
  (aformat ... channel_layouts=stereo) or 5.1 fails "Cannot select channel layout". Test FFmpeg changes on the
  cloud with a 10-second clip before a full run.
- Modal speed (8 cores): the 8.6-min history video drew 15,547 frames in 624 s (Mac: 25+ min, then failed).
- Wikimedia answers 403 to requests without a User-Agent, and 400 to non-standard thumbnail sizes (320, 1600 px
  fail; 250/330/500/960/1280/1920 work). The picture check fetched previews without one, so NO Wikipedia photo
  was ever approved (history videos were all Pixabay). Every Wikimedia request sends WIKI_UA; stock._wm_thumb.
- The picture check must know the story's subject and era (Stock(topic=...)): told only the narration line, it
  approved a modern cruise ship for an 1827 "squadron" and modern soldiers for 1820s "Russian armies".
- Busy Mac: Remotion with 7 tabs failed ("Visited http://localhost:3000/index.html but got no response");
  the automatic retry with half the tabs worked. Long videos are 25 fps (owner's choice), Shorts 30 fps.
