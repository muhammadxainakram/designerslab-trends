# DesignersLab Trend Finder

Live: **https://designerslab-trends.vercel.app**

A dashboard that shows **real** trending search data for [designerslab.io](https://designerslab.io).
Nothing on it is estimated, scored or generated. Every number comes straight from the source.

## Data sources

| Source | What you see |
|---|---|
| **Google Trends: Trending now** ([trends.google.com/trending](https://trends.google.com/trending)) | The same table Google shows, for 12 countries: **searches** since the trend started, **% increase**, **start time**, **active/ended**, Google's category and Google's **related queries**. A trend is listed only when its title or one of Google's related queries contains a design term from `config.json`. The dashboard shows which query matched. |
| **Google News** | Design-related headlines with their real publish time. |
| **Reddit** | New posts from design subreddits with real upvotes, comments and upvotes per hour. Needs free API keys (see below). |
| **designerslab.io sitemap** | Flags topics the site already has a post for. |

Time windows: past 2h, 4h, 24h, 48h and 7 days (Google's own windows; "2h" keeps only trends that started in the last 2 hours).
Filters: minimum searches (default 1K+), country, still-trending-only.

> **Note:** design keywords rarely reach Google's trending list. When the design table is empty, it means Google really had no
> design-related trend at that volume. The summary shows how many trends were checked.

## How it runs

- **Vercel (current):** `api/trends.py` fetches everything live when the page loads. Vercel's CDN caches each window for 15 minutes.
- **GitHub Actions + Pages (optional):** `.github/workflows/update-trends.yml` writes `docs/data/trends-*.json` every 30 minutes. This needs GitHub Actions enabled on the account.

## Reddit API keys (free)

1. Sign in to Reddit, open <https://www.reddit.com/prefs/apps>, click **create another app…**, choose **script** and use `http://localhost` as the redirect URL.
2. In Vercel → project → **Settings → Environment Variables**, add `REDDIT_CLIENT_ID` (the code under the app name) and `REDDIT_CLIENT_SECRET`. Then redeploy.

## Customise

Edit [`config.json`](config.json) to change the countries, design terms, news searches or subreddits.

## Run locally

```bash
python scripts/fetch_trends.py                 # writes docs/data/trends-{4,24,48,168}h.json
python -m http.server 8000 --directory docs
```
