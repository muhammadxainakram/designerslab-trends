# DesignersLab Trend Finder

A free dashboard that finds trending keywords to write about on [designerslab.io](https://designerslab.io).
It's hosted on **Vercel** (free). The page calls `/api/trends`, a small Python function that fetches
every source live. Vercel's CDN caches the result for 30 minutes, so the page stays fast and the sources
aren't hammered.

It can also run on **GitHub Pages + GitHub Actions** (the workflow in `.github/workflows` refreshes
`docs/data/trends.json` every 30 minutes and tracks history, e.g. which Google suggestions are new).
This only works if GitHub Actions is enabled for the account.

## Sources (all free, no API keys needed)

| Source | What it gives you |
|---|---|
| **Google Trends** ("Trending now" RSS) | Real trending searches in US, UK, CA, AU, IN and PK, with search volume, how long each has been trending (e.g. *trending for 2h 15m*) and the news behind it. |
| **Google Search** (Autocomplete) | What people actually type into Google for your niche seeds (fonts, mockups, templates, Canva, Photoshop, AI prompts, upcoming holidays…). Suggestions that newly appear are flagged **New**. |
| **Google News** (RSS, last 24h) | Fresh design-industry news: rebrands, new logos, Adobe/Canva/Figma updates, AI image tools. |
| **Reddit** | Hot posts and questions from design subreddits. Reddit blocks many anonymous requests, so for reliable results add free API keys (see below). |

Each item gets an **opportunity score (0–100)** based on:
- **Relevance** to designerslab.io (fonts, mockups, templates, PSD, AI prompts, seasonal design…)
- **Momentum** (search volume, upvotes per hour)
- **Freshness** (how recently it started trending)
- **Gap check.** The script reads your sitemap, and topics you already cover get a **Covered** badge and a lower score.

Every item also comes with ready-to-use **article title ideas**, a **Copy brief** button, and links to the live Google results and Google Trends.

## Customise

Edit [`config.json`](config.json) to change countries, seed keywords, news queries, subreddits, niche terms or holidays. Pushing a change runs the workflow right away.

## Optional: Reddit API keys (free)

1. Sign in to Reddit, go to <https://www.reddit.com/prefs/apps> and click **create another app…**. Choose the **script** type and use any redirect URL (e.g. `http://localhost`).
2. In this repo, go to **Settings → Secrets and variables → Actions** and add two secrets:
   - `REDDIT_CLIENT_ID`: the short id shown under the app name
   - `REDDIT_CLIENT_SECRET`: the secret

## Run locally

```bash
python scripts/fetch_trends.py         # writes docs/data/trends.json
python -m http.server 8000 --directory docs
```

No pip packages are needed. It uses only the Python standard library.
