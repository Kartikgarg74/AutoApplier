# AutoApplier

AI-powered job application bot that scrapes jobs from 10+ platforms, scores them against your profile, generates tailored resumes and cover letters, and auto-fills application forms via browser automation.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     AutoApplier                          │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │              Job Scraping Engine                    │  │
│  │  ┌─────────────────────┐  ┌─────────────────────┐ │  │
│  │  │  JobSpy (5 sites)   │  │  Custom Playwright   │ │  │
│  │  │  LinkedIn · Indeed   │  │  Greenhouse · Workday│ │  │
│  │  │  Glassdoor · Google  │  │  Lever · Wellfound   │ │  │
│  │  │  ZipRecruiter        │  │  Naukri              │ │  │
│  │  └─────────────────────┘  └─────────────────────┘ │  │
│  └──────────────────────┬────────────────────────────┘  │
│                         │                                │
│  ┌──────────────────────▼────────────────────────────┐  │
│  │           AI Matching & Scoring                    │  │
│  │  Phase 1: Keyword pre-filter (free, no API)       │  │
│  │  Phase 2: Claude Haiku deep analysis (~$0.01/job) │  │
│  └──────────────────────┬────────────────────────────┘  │
│                         │                                │
│  ┌──────────────────────▼────────────────────────────┐  │
│  │        Resume & Cover Letter Engine                │  │
│  │  Claude Sonnet: tailored resume + cover letter     │  │
│  │  ReportLab: ATS-friendly PDF generation            │  │
│  └──────────────────────┬────────────────────────────┘  │
│                         │                                │
│  ┌──────────────────────▼────────────────────────────┐  │
│  │         Form Filling Engine (Playwright)           │  │
│  │  Platform handlers: LinkedIn · Greenhouse ·        │  │
│  │  Workday · Lever · Indeed · Wellfound · Naukri     │  │
│  │  Anti-detection: human-like typing, random delays  │  │
│  └──────────────────────┬────────────────────────────┘  │
│                         │                                │
│  ┌──────────┐  ┌────────▼────┐  ┌──────────────────┐   │
│  │ Telegram │  │   SQLite    │  │  Google Sheets   │   │
│  │   Bot    │  │   Tracker   │  │  (optional sync) │   │
│  └──────────┘  └─────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

## Workflow

### Full Application Pipeline

```
1. SCRAPE JOBS (twice daily: 8 AM + 6 PM IST)
   ├── JobSpy: LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter
   │   └── 50 results per platform, jobs from last 24 hours
   ├── Custom Playwright scrapers:
   │   ├── Greenhouse (company career pages)
   │   ├── Workday (enterprise career pages)
   │   ├── Lever (mid-market career pages)
   │   ├── Wellfound (startup jobs)
   │   └── Naukri.com (Indian jobs)
   └── Deduplicate across platforms (title + company + location hash)

2. SCORE & MATCH (per job)
   ├── Phase 1: Keyword pre-filter (FREE — no API call)
   │   ├── Check must_have_keywords, nice_to_have, exclude_keywords
   │   ├── Score: 0-100
   │   └── Below 30 → auto-skip (saves API cost)
   │
   └── Phase 2: AI deep analysis (Claude Haiku — ~$0.01/job)
       ├── Compare job description against user profile
       ├── Output: relevance_score (0-100), matching_skills, missing_skills
       ├── AI recommendation: "Strong Match" / "Good Match" / "Weak Match" / "Skip"
       ├── Resume focus areas (what to emphasize)
       └── Cover letter hook (key angle)

3. GENERATE DOCUMENTS (Claude Sonnet — per application)
   ├── Tailored Resume:
   │   ├── Reorder skills to match job requirements
   │   ├── Rewrite bullet points with job keywords
   │   ├── Emphasize relevant experience
   │   ├── ATS-friendly single-column format
   │   └── Output: PDF via ReportLab
   │
   └── Tailored Cover Letter:
       ├── Company-specific opening hook
       ├── 2-3 achievements mapped to job requirements
       ├── Professional but genuine tone (300 words max)
       └── Cached if same company + similar role

4. FILL APPLICATION FORM (Playwright browser automation)
   ├── Load application URL
   ├── Detect platform → select handler (Greenhouse/Workday/LinkedIn/etc.)
   ├── Parse form structure (DOM + Claude Haiku for ambiguous fields)
   ├── Map fields to user profile:
   │   ├── Name, email, phone, LinkedIn → from profile
   │   ├── Resume, cover letter → upload generated PDFs
   │   ├── Custom questions → Claude Haiku generates answers from FAQ bank
   │   └── Diversity questions → from profile config
   ├── Human-like interaction:
   │   ├── Random scroll before action
   │   ├── Random delay between fields (0.5-3 sec)
   │   ├── Variable typing speed (50-150ms per char)
   │   └── Random mouse movements
   └── Screenshot filled form before submission

5. SUBMISSION DECISION
   ├── Mode: "approve_first" (default):
   │   ├── Send screenshot + job details to Telegram
   │   ├── Wait for /approve or /reject
   │   └── User reviews before submission
   │
   ├── Mode: "auto":
   │   ├── Auto-submit if score >= 80
   │   └── Send confirmation to Telegram
   │
   └── Mode: "hybrid":
       ├── Score >= 80 → auto-submit
       ├── Score 60-79 → send for review
       └── Score < 60 → auto-skip

6. TRACK & REPORT
   ├── Log to SQLite: job, score, status, resume version, screenshot
   ├── Sync to Google Sheets (optional — for sharing with family)
   ├── Daily summary at 9 PM via Telegram
   └── Analytics: response rate, interview rate, top platforms
```

### Anti-Detection System

```
Browser Fingerprinting:
  ├── Disable navigator.webdriver flag
  ├── Use real Chrome profile with cookies/history
  └── Consistent user agent (rotating looks suspicious)

Behavioral Mimicry:
  ├── Human-like typing with variable speed
  ├── Random scrolling before actions
  ├── Random mouse movements
  ├── 15-45 min sessions with 5-15 min breaks
  └── 2-10 min gaps between applications

Rate Limits (per platform):
  ├── LinkedIn: 5/hour, 25/day, 100/week
  ├── Indeed: 10/hour, 50/day
  ├── Greenhouse: 8/hour, 30/day
  ├── Workday: 5/hour, 20/day
  └── Wellfound: 6/hour, 15/day

Error Handling:
  ├── CAPTCHA → pause + Telegram alert (never auto-solve)
  ├── Ban warning → immediate stop + notify
  └── Rate limit → exponential backoff (1m, 2m, 4m, 8m...)
```

## APIs Used

### Job Scraping

| API/Tool | Purpose | Cost | Platforms Covered |
|----------|---------|------|-------------------|
| **JobSpy** (python-jobspy) | Bulk job scraping | Free, open-source | LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter |
| **Playwright** | Custom ATS scraping + form filling | Free, open-source | Greenhouse, Workday, Lever, Wellfound, Naukri |

### AI APIs

| API | Purpose | Model | Cost |
|-----|---------|-------|------|
| **Anthropic Claude API** | Job scoring & matching | Claude Haiku 4.5 | ~$0.01/job |
| **Anthropic Claude API** | Resume tailoring | Claude Sonnet 4.6 | ~$0.05/resume |
| **Anthropic Claude API** | Cover letter generation | Claude Sonnet 4.6 | ~$0.03/letter |
| **Anthropic Claude API** | Form field answers (custom questions) | Claude Haiku 4.5 | ~$0.01/form |
| **Groq** (fallback) | All tasks when Claude unavailable | Llama 3.3 70B | Free (14,400 req/day) |

### MCP Integrations

| MCP Server | Purpose | Capabilities |
|------------|---------|-------------|
| `adhikasp/mcp-linkedin` | LinkedIn integration for Claude Desktop | Search people, companies, jobs |

### Notifications & Tracking

| Service | Purpose |
|---------|---------|
| **Telegram Bot API** | Application alerts, approval workflow (/approve, /reject), daily analytics |
| **Google Sheets API** (gspread) | Optional sync of application tracker for sharing with family |
| **Email (SMTP/Gmail)** | Optional weekly reports |

## Tech Stack

- **Language:** Python 3.11+
- **Scraping:** python-jobspy, Playwright (Chromium)
- **AI:** anthropic (Claude API), groq
- **PDF Generation:** ReportLab
- **Database:** SQLAlchemy + SQLite
- **Scheduling:** APScheduler
- **Notifications:** python-telegram-bot
- **Sheets:** gspread (Google Sheets sync)
- **Security:** cryptography (Fernet encryption for secrets at rest)
- **Deployment:** Docker + docker-compose

## Setup

```bash
# Clone
git clone https://github.com/Kartikgarg74/AutoApplier.git
cd AutoApplier

# Virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Configure
cp .env.example .env
# Edit .env with your API keys

# Edit your profile
# config/users/kartik/profile.yaml   — your resume data
# config/users/kartik/preferences.yaml — target roles, platforms, thresholds

# Run
python main.py                              # Default: approve_first mode
python main.py --mode auto                  # Fully automatic
python main.py --mode hybrid                # Auto for high scores, review for medium
python main.py --scan-once                  # Single scan cycle (testing)
python main.py --dry-run                    # Scrape + score only, no submissions
python main.py --user kartik                # Specify user profile
```

### Docker

```bash
docker-compose up -d
```

## Application Modes

| Mode | Behavior | Best For |
|------|----------|----------|
| **approve_first** (default) | Fills form → sends screenshot to Telegram → waits for /approve | First-time use, high-stakes roles |
| **auto** | Auto-submits if score >= 80 | Volume applications, trusted scoring |
| **hybrid** | Auto for 80+, review for 60-79, skip below 60 | Balanced approach |

## Scoring Thresholds

| Score | Action |
|-------|--------|
| 0-29 | Auto-skip (keyword pre-filter, no API call) |
| 30-59 | AI-scored, but below threshold — skipped |
| 60-79 | "Good Match" — sent for review in approve_first/hybrid |
| 80-100 | "Strong Match" — auto-applied in auto/hybrid mode |

## Safety Limits

- **30 applications/day** max across all platforms
- **100 applications/week** max
- Per-platform daily caps: LinkedIn 25, Indeed 50, Greenhouse 30, Workday 20
- Session duration: 15-45 min with mandatory breaks
- CAPTCHA: pause and notify (never auto-solve)
- Ban warning: immediate stop

## Estimated Monthly Cost

| Component | Cost |
|-----------|------|
| Claude Haiku (scoring 1000 jobs) | ~$10 |
| Claude Sonnet (200 resumes + cover letters) | ~$10-15 |
| Groq (fallback) | Free |
| JobSpy | Free |
| Playwright | Free |
| **Total** | **~$20-25/month** |

## Telegram Commands

```
/status          - Current run status & queue
/analytics       - Application stats (30-day summary)
/today           - Today's applications
/approve         - Approve pending application
/reject          - Reject pending application
/edit            - Modify answers before submission
/pause           - Pause the bot
/resume          - Resume the bot
/platforms       - Platform-specific stats
```

## Supported Platforms

| Platform | Scraping | Form Filling | Handler |
|----------|----------|-------------|---------|
| LinkedIn | JobSpy | Easy Apply automation | `LinkedInHandler` |
| Indeed | JobSpy | Direct apply | `IndeedHandler` |
| Glassdoor | JobSpy | Redirects to ATS | — |
| Google Jobs | JobSpy | Redirects to ATS | — |
| ZipRecruiter | JobSpy | Direct apply | `GenericHandler` |
| Greenhouse | Custom Playwright | Multi-page forms | `GreenhouseHandler` |
| Workday | Custom Playwright | Dynamic forms | `WorkdayHandler` |
| Lever | Custom Playwright | Standard forms | `LeverHandler` |
| Wellfound | Custom Playwright | Startup-style forms | `WellfoundHandler` |
| Naukri.com | Custom Playwright | Indian job portal | `NaukriHandler` |

## License

Personal use. Built for automating tedious job applications — not for spamming.
