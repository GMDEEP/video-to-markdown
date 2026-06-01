# Platform Notes

## YouTube

**Auth required:** Only on datacenter/cloud IPs, or for age-restricted/sign-in-required content.

**Captions:** Excellent. Auto-captions available for most English content. Prefer manual captions (`en`) over auto (`en-orig`) when both are present — auto-captions sometimes insert stray `>>` markers.

**Cookie setup (when needed):**
1. Install the "cookies.txt" extension for Firefox
2. Log into youtube.com in Firefox
3. Click the extension → "Export" → save the file
4. Pass: `--cookies /path/to/cookies.txt`
5. Must export from the same IP you're downloading from
6. Cookies expire — re-export every ~2 weeks

**Note:** Chrome cookies are encrypted (app-bound since Chrome 127) and cannot be reliably extracted. Use Firefox.

---

## Instagram

**Auth required:** Yes — public Reels increasingly require a logged-in session.

**Captions:** Rarely available via yt-dlp. Whisper transcription recommended (`--whisper`).

**Cookie setup:**
1. Install "cookies.txt" for Firefox
2. Log into instagram.com in Firefox
3. Export cookies (`sessionid` and `ds_user_id` are the critical ones)
4. Pass: `--cookies /path/to/cookies.txt`

**Known behavior:** Even with valid cookies, some Reels return "empty media response" (yt-dlp issue #13551). This is intermittent — retry after a few minutes or try a different account's cookies.

**Throwaway account recommended.** Instagram can temporarily lock accounts used for cookie-based scraping.

---

## Facebook

**Auth required:** Yes — cookies required. Additionally, Facebook's Tahoe API uses TLS fingerprinting that causes "Cannot parse data" errors unless browser impersonation is also active.

**The fix:** `--impersonate Chrome-99` — this is handled automatically by video_analyzer.py when Facebook is detected. Requires `curl_cffi` (installed via `pip install "yt-dlp[default,curl-cffi]"`).

**Captions:** Rarely reliable via yt-dlp. Use `--whisper`.

**Cookie setup:**
1. Install "cookies.txt" for Firefox
2. Log into facebook.com in Firefox (must be the same browser/IP you export from)
3. Export cookies
4. Pass: `--cookies /path/to/cookies.txt`
5. Cookies must be fresh — export within ~30 min of use, from the same IP

**Throwaway account strongly recommended.** Facebook locks accounts on cookie-based scraping more aggressively than Instagram.

---

## General Cookie Tips

- **Firefox only** — Chrome's app-bound encryption (Chrome 127+) makes extraction unreliable
- **Same IP** — export from the same network you're running the script on
- **Fresh** — export immediately before use; sessions expire
- **Private instance** — use a dedicated browser profile or throwaway account
- Never commit cookies.txt to git

---

## Unsupported Platforms

yt-dlp supports 1,800+ sites. If a platform isn't YouTube/Facebook/Instagram, the script still attempts a generic yt-dlp download. Success varies. Check yt-dlp's [supported sites list](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).
