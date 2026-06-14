# Frontend — Sanctions Screening Dashboard

Hey! Welcome to the project. This is the frontend for a sanctions screening AI demo. The goal is to build a dashboard that shows off what the AI model can do — not a production-grade banking UI, but something clear and impressive that communicates how the system makes decisions.

This README is your guide. Read the backend README too (`backend/README.md`) — it has the full API spec.

---

## What You're Building

A demo dashboard for an AI-powered sanctions screening system. The AI model:

- Takes account features + a `match_score` (0–100, how closely an account name matched a sanctions list entry)
- Computes **two dynamic thresholds** per account: `t_block` and `t_review`
- Returns a verdict: **BLOCK** / **REVIEW** / **CLEAR**

The clever part — and what you want to make visually obvious — is that the thresholds **vary per account** based on their risk profile. A high-risk account has lower thresholds (easier to BLOCK), a low-risk account has higher thresholds (harder to BLOCK). That's the key insight to communicate in the UI.

---

## Suggested Tech Stack

Pick whatever you're most comfortable with. Suggestions:

- **Framework**: React + TypeScript (recommended), or Vue 3, or SvelteKit
- **Styling**: Tailwind CSS — keeps things fast to iterate
- **Charts**: Recharts (easy with React) or Chart.js (framework-agnostic)
- **HTTP**: Axios or the native `fetch` API
- **Build tool**: Vite

If you go with React + Vite + Tailwind + Recharts, you'll have a solid setup that's fast to work with.

---

## Backend API

The backend runs at `http://localhost:8000` by default. Configure it via an environment variable so you don't have to hardcode it:

```
VITE_API_URL=http://localhost:8000
```

In your code:

```ts
const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
```

Make sure the backend has CORS enabled for your dev server (usually `http://localhost:5173`). It should — but if you get CORS errors, check in with whoever set up the backend.

---

## Pages / Views

### 1. Dashboard (Home)

The summary view. At a glance, it should tell you the health of the system.

**What to show:**
- Verdict distribution — a pie chart or donut: how many accounts are BLOCK / REVIEW / CLEAR
- Risk band distribution — a bar chart: low / medium / high / critical account counts
- "Verdicts differ" count — how many screenings had the threshold-rule verdict disagree with the model's own probability prediction (shows where the system is uncertain)
- Top 5 highest-risk accounts — a small table with account ID, risk score, verdict, and a link to their detail page

**API call:** `GET /dashboard/stats`

---

### 2. Account Explorer

A searchable, filterable table of all accounts.

**Features:**
- Search by account ID or name
- Filter by risk band (low / medium / high / critical) and by latest verdict (BLOCK / REVIEW / CLEAR)
- Pagination
- Clicking a row goes to the Account Detail page

**Columns to show:** Account ID, Type (individual/business), KYC Status, Risk Band, Risk Score, Latest Verdict.

**API call:** `GET /accounts?page=1&limit=50&risk_band=high&verdict=REVIEW`

---

### 3. Account Detail

The most information-dense page. This is where the interesting stuff lives.

**Sections:**

**Account info** — KYC status, account type, PEP flag, shell company flag, activity tier.

**Risk score breakdown** — the five risk components as a radar chart or horizontal bar chart:
- Geographic risk
- Identity / KYC risk
- PEP & sanctions risk
- Behavioural risk
- Relationship network risk

**Threshold visualisation** — see the dedicated section below. This is the key visual.

**Audit panel** — see the dedicated section below.

**Transaction history** — a table of the account's recent transactions with amount, type, counterparty country, and rolling 7-day / 30-day velocity.

**API calls:**
- `GET /accounts/{account_id}` — account + risk score + latest screening + threshold decision
- `GET /accounts/{account_id}/transactions` — transaction list
- `GET /thresholds/explain/{account_id}` — threshold formula breakdown

---

### 4. Screening Queue

A focused view of accounts currently sitting in REVIEW — the ones waiting for a human analyst.

Show them as a list/table with: Account ID, match score, context (onboarding / transaction / periodic review), and the time they were screened. You could add a "Mark reviewed" button that doesn't do anything real — it's a demo, but the affordance helps people understand the workflow.

**API call:** `GET /screening?verdict=REVIEW`

---

### 5. Live Screener

The most interactive page. A form where you type in account attributes and a match score, hit "Screen", and immediately see the AI's decision.

**The form inputs:**
- Account type (individual / business) — dropdown
- KYC completeness — slider 0–1
- KYC status — dropdown (complete / partial / pending / expired)
- Is PEP — checkbox
- Has complex ownership — checkbox
- Shell company flag — checkbox
- Activity tier — dropdown (low / medium / high)
- Account status — dropdown (active / suspended / closed)
- Match score — slider 0–100 (this is the fun one to drag around)
- Overall risk score — slider 0–100

For risk components (geographic, identity/KYC, PEP/sanctions, behavioural, relationship network), you can either expose them as sliders or derive them from the overall risk score with a simple split — whatever feels right for the demo.

**On submit:** call `POST /screen`, then display:
- The verdict badge (BLOCK / REVIEW / CLEAR) in a big coloured label
- The threshold visualisation showing where the match score landed
- The full audit panel

The really fun thing here is the match score slider. If you update the result live as the slider moves (debounced), users can watch the verdict flip as they cross t_review and t_block. That's a powerful demo moment.

**API call:** `POST /screen`

---

## The Threshold Visualisation (Key Visual)

This is the most important piece of UI in the whole app. Get this right and the demo will make sense to anyone who sees it.

**What it is:** A horizontal bar spanning 0–100, divided into three coloured zones:

```
|←————————— CLEAR (green) ————————→|←—— REVIEW (amber) ——→|←— BLOCK (red) —→|
0                                t_review              t_block              100
                                    ↑                     ↑
                                 boundary              boundary

                                              ●  ← match_score (dot/marker)
```

- The **green zone** (0 to t_review) = account will automatically CLEAR
- The **amber zone** (t_review to t_block) = account is routed to a human analyst
- The **red zone** (t_block to 100) = account is automatically blocked
- The **dot** shows where the account's current match score sits
- The **boundary lines** at t_review and t_block are labelled with their values

**Why this varies per account:** The zones shift left or right depending on the account's overall risk score.

- A **low-risk account** (risk score ~10): t_block ≈ 87, t_review ≈ 62 — the red and amber zones are pushed far right. The account needs a very high match score before anything happens.
- A **high-risk account** (risk score ~85): t_block ≈ 63, t_review ≈ 38 — the zones are pushed left. Even a moderate match score triggers REVIEW or BLOCK.

Show this contrast explicitly — maybe a small "comparison mode" toggle, or a tooltip that says "For a low-risk account (risk=10), t_block would be 87.5".

**Implementation tip:** Render this as an SVG or as three `div`s with percentage widths. The zone widths are:
- Green zone width: `t_review / 100 * 100%`
- Amber zone width: `(t_block - t_review) / 100 * 100%`
- Red zone width: `(100 - t_block) / 100 * 100%`
- Dot position: `match_score / 100 * 100%`

---

## The Audit Panel

Every verdict should be accompanied by an audit panel. This is the **explainability section** — it answers "why did the AI decide this?". Make it prominent, not tucked away.

**What to show:**

1. **Verdict badge** — a large, colour-coded chip: green for CLEAR, amber for REVIEW, red for BLOCK.

2. **Audit narrative** — the `audit_narrative` string from the API. This is a single paragraph written in plain English by the model. Display it as body text directly.

   Example:
   > Verdict: REVIEW. The account's overall risk score of 30.0/100 raised the block threshold from the static baseline of 75.0 to 85.0 and the review threshold to 60.0, reflecting a low-risk profile. The screening system produced a match score of 72.5/100. match score 72.5 is between review threshold 60.0 and block threshold 85.0 → routed to human analyst.

3. **Audit factors** — the `audit_factors` list. Each item is a bullet point. These name the specific features that drove the decision.

4. **Probability breakdown** — a small bar or set of badges showing the model's probability estimates:
   - P(BLOCK): shown in red
   - P(REVIEW): shown in amber
   - P(CLEAR): shown in green

   This is useful when the verdict is borderline — you might see REVIEW with P(BLOCK)=0.48 and P(REVIEW)=0.41, which tells you it was close.

5. **Top feature contributions** — a small table or mini bar chart from `feature_contributions`. Show the top 5: feature name, its value, and its contribution percentage.

---

## Key API Calls

Quick reference for what you'll use most:

| Page              | Endpoint                                      | Notes                              |
|-------------------|-----------------------------------------------|------------------------------------|
| Dashboard         | `GET /dashboard/stats`                        |                                    |
| Account Explorer  | `GET /accounts`                               | Use query params for filters       |
| Account Detail    | `GET /accounts/{id}`                          |                                    |
| Account Detail    | `GET /accounts/{id}/transactions`             |                                    |
| Account Detail    | `GET /thresholds/explain/{id}`                | For the formula breakdown tooltip  |
| Screening Queue   | `GET /screening?verdict=REVIEW`               |                                    |
| Screening Detail  | `GET /screening/{id}`                         |                                    |
| Live Screener     | `POST /screen`                                | Full feature dict in body          |

Full endpoint specs with example request/response bodies are in `backend/README.md`.

---

## Getting Started

```bash
# Clone (if you haven't already)
git clone <repo-url>
cd garaza/frontend

# Install dependencies
npm install

# Copy env file and configure backend URL
cp .env.example .env
# Edit .env: VITE_API_URL=http://localhost:8000

# Start dev server
npm run dev
```

The dev server will start at `http://localhost:5173`.

Make sure the backend is running first (`cd ../backend && uvicorn main:app --reload --port 8000`), otherwise API calls will fail.

---

## A Few Tips

- Start with the **Live Screener** page first. It's self-contained (just one POST call), it's the most fun to build, and it forces you to understand the data shape before you touch anything else.
- The threshold visualisation is worth spending real time on. Get the colours and layout right — it's what people will remember from the demo.
- Use placeholder/loading states everywhere. The model has a ~1-second cold start on first call; show a spinner so it doesn't look broken.
- Don't over-engineer the state management for a demo. Context or simple prop-drilling is fine. You don't need Redux.
- If you want to make the match score slider in the Live Screener feel snappy, debounce the API call by ~300ms so it doesn't fire on every pixel of movement.
