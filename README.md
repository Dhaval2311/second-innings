# Second Innings 🚀

**Free, fully local job automation — scrape, score, auto-apply, and generate content.**

No subscriptions. No cloud. Runs entirely on your machine using your logged-in browser.

---

## What It Does

| Feature | Details |
|---|---|
| **Scrape** | LinkedIn, Naukri, Hirist, Indeed, Wellfound, Cutshort |
| **Score** | Keyword match (role + JD text) → 0–100. Optional AI scoring via Gemini/Groq |
| **Easy Apply Lane** | Automated form-filling and submission via your browser (LinkedIn, Hirist, Naukri…) |
| **Company Site Lane** | Jobs auto-logged to a manual queue. One-click "Mark Applied" in dashboard |
| **Deduplication** | URL-level (same job never re-added) + cross-source fuzzy (same role/company across sites) |
| **Recent Only** | Configurable `fresh_only_days` (default: 7) — stale jobs are skipped at scrape time |
| **Screening Answers** | Rules → AI (Gemini/Groq) → UI notification. Never blocks the terminal |
| **Cover Letter** | AI or template-based, ≤250 words, tailored to JD |
| **Cold Email** | Concise 180-word outreach with attention-grabbing subject line |
| **LinkedIn DM** | ≤300-char warm connection note, ready to copy-paste |
| **Dashboard** | Local web UI with pipeline stats, charts, job tracker, and notification bell |

---

## Quick Start

### 1. Prerequisites

- **Python 3.11+**
- **Brave** (or Chrome/Chromium) with remote debugging enabled
- A free **Gemini** or **Groq** API key (optional — app works without one)

### 2. Install

```bash
git clone https://github.com/Dhaval2311/second-innings
cd second-innings/second_innings

python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Optional AI providers:
pip install google-generativeai   # for Gemini Free
# OR
pip install groq                  # for Groq
```

### 3. First-time setup

```bash
python -m job_automation setup
```

Walks you through profile, job sites, and AI key. Writes `config.yaml` (git-ignored).

### 4. Launch your browser with remote debugging

```bash
# macOS — Brave
/Applications/Brave\ Browser.app/Contents/MacOS/Brave\ Browser \
  --remote-debugging-port=9222 --no-first-run

# macOS — Chrome
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --no-first-run
```

> Log into LinkedIn, Naukri, Hirist etc. in this browser window before running.

### 5. Run

```bash
# Scrape jobs (browser-based)
python -m job_automation scrape

# Auto-apply to easy-apply jobs, log company-site jobs
python -m job_automation apply

# Do both in one go
python -m job_automation run

# Start the web dashboard
python -m job_automation ui
```

Open **http://localhost:8080** in your normal browser.

---

## AI Setup (Free)

### Option A — Google Gemini Free
1. Go to https://aistudio.google.com/app/apikey
2. Click **Create API Key** — no billing required
3. Add to `config.yaml`:
   ```yaml
   ai:
     provider: gemini_free
     api_key: YOUR_KEY_HERE
   ```

### Option B — Groq (Llama 3)
1. Go to https://console.groq.com and sign up
2. Create a free API key
3. Add to `config.yaml`:
   ```yaml
   ai:
     provider: groq
     api_key: YOUR_KEY_HERE
   ```

### Option C — No AI
Leave `ai.provider: none` — rule-based screening answers still work for common questions (CTC, experience, notice period, location).

---

## CLI Reference

```
python -m job_automation <command>

Commands:
  setup          First-time wizard → generates config.yaml
  scrape         Scrape all enabled sources (recent listings only)
  scrape --sources linkedin hirist   Limit to specific sources
  apply          Two-lane apply pipeline
  run            scrape + apply
  ui             Start dashboard at http://localhost:8080
  ui --port 9090 Custom port
  status         Show pipeline summary from DB
  pending        List unanswered screening questions
  learn          Extract answers from the open browser tab (post-apply form)
  tabs           List open tabs in the attached browser
  cover-letter --company Stripe --role "Data Engineer"
  cold-email   --company Stripe --role "Data Engineer" --to "Jane Smith"
  cold-dm      --company Stripe --role "Data Engineer" --name "Jane"
```

---

## Dashboard

```
python -m job_automation ui
```

Open http://localhost:8080

| Tab | What's There |
|---|---|
| **Overview** | KPI cards, bar chart by source, apply-type doughnut |
| **Tracker** | Filterable job table with status badges and score |
| **Company Queue** | Manual apply queue — click "Open & Apply" then "Mark Applied" |
| **🔔 Pending** | Questions the bot couldn't answer — type answers here, click Save |
| **Content** | Generate cover letter / cold email / LinkedIn DM |
| **History** | Scrape run log with timestamps and job counts |

---

## Configuration

`config.yaml` (git-ignored, created by `setup`) — see `config.example.yaml` for all options.

Key sections:

```yaml
profile:
  resume_path: ~/path/to/Resume.pdf
  full_name: Your Name
  email: you@example.com
  years_experience: 7
  current_ctc_lpa: 20
  expected_ctc_lpa: 30
  notice_period_days: 30

ai:
  provider: gemini_free   # gemini_free | groq | none
  api_key: YOUR_KEY_HERE

scraper:
  fresh_only_days: 7      # Only scrape listings posted in last 7 days
  max_jobs_per_search: 20

applier:
  dry_run: true           # Set to false to actually submit applications
  max_per_run: 20
```

---

## How Screening Answers Work

```
Apply bot hits a form question
         │
   ┌─────▼──────┐
   │  Check DB  │  ← Previous answers + manually learned
   └─────┬──────┘
    Found│    Not found
         │         │
   Use instantly  Try AI (Gemini/Groq)
                        │
                  AI answers│    AI unsure
                        │          │
                  Save to DB    Log to pending_inputs
                                Dashboard bell 🔔 lights up
                                You type answer in dashboard
                                Click Retry → apply continues
```

No terminal blocking. The bot moves to the next job and comes back.

---

## Privacy & Security

- All data is **local** — SQLite DB, no cloud sync
- `config.yaml` and `second_innings.db` are in `.gitignore` — **never committed**
- API keys stay in `config.yaml` on your machine only
- The dashboard is local-only (`localhost:8080`) — not accessible from outside your machine

---

## Adding More Job Sites

1. Create `second_innings/scraper/yoursite.py` extending `BaseScraper`
2. Add to `BROWSER_SCRAPERS` dict in `scraper/orchestrator.py`
3. Add search URLs to your `config.yaml` under `scraper.searches.yoursite`

---

## License

MIT — use freely, fork freely.

---

*Built with Playwright (browser automation), FastAPI (dashboard), SQLite (data), and love for the job search grind.*
