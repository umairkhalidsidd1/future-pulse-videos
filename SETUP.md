# Setup guide

Follow these steps in order. Everything is free. You can stop after any step: the
machine works with what is set up, and skips platforms that are not set up yet.

**How it works, in one paragraph:** GitHub runs this project 6 times a day.
The first run of the day finds trending tech stories. Then it writes 5 short
scripts and 1 long script with the free Gemini AI. Each run makes **one** video:
a voice track, stock clips, captions and music. It then posts that video. Order:
Short, Short, Long, Short, Short, Short. Progress is saved in `data/` in the repo.

A "secret" (used below) is a password GitHub keeps hidden. Your code can read it,
but nobody who looks at the public repo can see it.

---

## Step 1: Put the project on GitHub (public repo)

Public repos get unlimited free GitHub Actions minutes. Your keys stay hidden in Secrets.

```bash
cd ~/Desktop/Videos && git add -A && git commit -m "Daily video machine" && gh repo create --public --source . --push
```

## Step 2: Free AI and stock-video keys (about 10 minutes)

| Secret name | Where to get it |
|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com → **Get API key** |
| `GROQ_API_KEY` (backup AI) | https://console.groq.com → **API Keys** |
| `PIXABAY_API_KEY` | https://pixabay.com/api/docs (sign up or log in, and the key appears on that page) |
| `PEXELS_API_KEY` (optional) | https://www.pexels.com/api. New keys were paused in Oct 2026, so skip this if it's still paused |

Save each one in GitHub. The command asks you to paste the value:

```bash
gh secret set GEMINI_API_KEY
```

Do the same for the others. To test on your Mac too, also put them in a file called `.env`
in this folder, one per line, like `GEMINI_API_KEY=abc123`. `.env` is never uploaded.

## Step 3: YouTube (about 20 minutes)

1. Make the channel. Then verify your phone at https://www.youtube.com/verify.
   Without this, custom thumbnails and videos over 15 minutes are blocked.
2. Open https://console.cloud.google.com and create a new project.
3. **APIs & Services → Library**: enable **YouTube Data API v3**.
4. **OAuth consent screen**: choose External and fill in the app name and your email.
   Then press **Publish app** so the status says **In production**.
   - Why: in "Testing" mode, the login stops working after 7 days.
   - Google will say the app is "unverified". That is fine, because only you use it.
5. **Credentials → Create credentials → OAuth client ID → Desktop app**. Download the JSON file.
   Save it in this folder as `client_secret.json`. It is never uploaded.
6. Run this on your Mac. A browser opens. Pick the channel's Google account and allow access.
   If you see "Google hasn't verified this app", click **Advanced → Go to app**.
   ```bash
   .venv/bin/python scripts/youtube_auth.py
   ```
7. Save the 3 printed values as secrets: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
8. **If your uploads come out Private:** new API projects can be locked to private until
   Google checks them. Fill in the free audit form: https://support.google.com/youtube/contact/yt_api_form
   (It usually takes 2–4 weeks. Videos still upload in the meantime.)

## Step 4: Instagram Reels (about 30 minutes)

1. In the Instagram app: **Settings → Account type → switch to Professional** (Creator or Business).
2. Create a Facebook Page and link your Instagram account to it.
   In the Page's settings, look for **Linked accounts → Instagram**.
3. https://developers.facebook.com → **Create app** → type **Business**.
   Add the **Instagram** product and choose **API setup with Facebook Login**.
4. Open https://business.facebook.com/settings → **Users → System users → Add**, with the Admin role. Then:
   - **Assign assets**: your app (full control), your Facebook Page and your Instagram account.
   - **Generate new token**: pick your app, set expiry to **Never**, and tick
     `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management`.
   - Save the token as the secret `IG_ACCESS_TOKEN`.
5. Find your Instagram user ID. Paste your token in place of `TOKEN`:
   ```bash
   curl "https://graph.facebook.com/v26.0/me/accounts?fields=name,instagram_business_account&access_token=TOKEN"
   ```
   The number inside `instagram_business_account` is your `IG_USER_ID`. Save it as a secret.

Limit: Instagram allows about 50–100 API posts a day. We post 5.

## Step 5: TikTok (about 30 minutes, plus waiting for TikTok)

**Important:** until TikTok approves ("audits") your app, two limits apply:
- API posts can only be **private** (only you can see them).
- Your TikTok account must also be set to **Private**.

You have 2 choices until the audit passes:
- **A (default):** keep `mode: "direct"` in `config.yaml`. Posts go up private. Once the audit
  passes, they go up public automatically, with no change needed.
- **B:** set `mode: "inbox"`. Each video arrives in your TikTok inbox as a draft.
  You tap **Post** in the app. This is public, but not fully automatic.

Steps:
1. https://developers.tiktok.com → **Manage apps → Connect an app**.
2. Add the products **Login Kit** and **Content Posting API**, and switch on **Direct Post**.
   Scopes: `user.info.basic`, `video.upload`, `video.publish`.
3. Redirect URI: use a page on your own website (your Hostinger site), for example
   `https://yourdomain.com/tiktok`. The page doesn't have to exist.
4. Put these 3 lines in `.env`: `TIKTOK_CLIENT_KEY=...`, `TIKTOK_CLIENT_SECRET=...` and
   `TIKTOK_REDIRECT_URI=https://yourdomain.com/tiktok`. Then run:
   ```bash
   .venv/bin/python scripts/tiktok_auth.py
   ```
5. Save `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` and `TIKTOK_REFRESH_TOKEN` as secrets.
6. TikTok sometimes replaces the refresh token. To let the bot save the new one by itself, make a
   GitHub token at https://github.com/settings/personal-access-tokens:
   - Fine-grained, only this repo, permission **Secrets: Read and write**.
   - Save it as the secret `GH_PAT`.
7. Apply for the audit in the TikTok developer portal (Content Posting API → **Apply**).

## Step 6: Background music (5 minutes, optional)

Music licences let you use tracks in videos, but not share the files themselves. So the tracks
go in a separate **private** repo, never this public one.

1. YouTube Studio → **Audio Library** → filter **Attribution not required** → download 5–10 upbeat tracks.
2. Make a private repo with the same name as this one plus `-music` (example: `future-pulse-videos-music`),
   and put the tracks in it.
3. Your `GH_PAT` token (Step 5.6) also needs **Contents: Read** on that music repo.

With no music, videos still work (voice and whooshes only).

## Step 7: Test, then switch on

In GitHub, open the repo → **Actions → Daily videos → Run workflow**:
1. `check`: tests every key. Each line says OK or FAIL.
2. `test`: makes 2 sample videos without posting. Download them from the run page (**Artifacts**).
3. `auto`: makes and posts the first real video of today.

After that it runs by itself 6 times a day. To pause: **Actions → Daily videos → ⋯ → Disable workflow**.

## Things to know

- **Cost:** everything here is free. Gemini's free limit is about 100 requests a day; we use about 15.
- **Pinned comment:** YouTube's API can post the question comment, but it can't pin it. Pin it in the app.
- **Check your videos for the first 1–2 weeks.** Fully automatic posting means a bad script can go live.
  Each run's videos stay downloadable for 7 days under **Actions → the run → Artifacts**.
- **Schedule stops after 60 days with no repo activity.** The bot commits its progress every run, so this won't happen while it runs.
- **Give it 30–60 days** of daily posting before judging the results.
