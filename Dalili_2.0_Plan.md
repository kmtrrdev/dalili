# Dalili 2.0: The Plan

> From a strong graduation project to a product people would actually trust with their holiday.

This document is the roadmap. It covers:
- an honest look at where Dalili stands today;
- the idea that should drive everything next;
- the redesign of the experience;
- the AI, data, architecture and quality upgrades;
- a phased plan with clear "done" criteria.

---

## Contents

1. [Where Dalili stands today](#1-where-dalili-stands-today)
2. [The north star](#2-the-north-star)
3. [Experience redesign](#3-experience-redesign)
4. [AI 2.0: from a pipeline with agents to a real agent system](#4-ai-20-from-a-pipeline-with-agents-to-a-real-agent-system)
5. [Prices & data 2.0](#5-prices--data-20)
6. [Architecture 2.0](#6-architecture-20)
7. [Quality: testing and evaluation](#7-quality-testing-and-evaluation)
8. [Security & privacy](#8-security--privacy)
9. [Phased roadmap](#9-phased-roadmap)
10. [How we'll know it's working](#10-how-well-know-its-working)
11. [Risks](#11-risks)
12. [This week](#12-this-week)

---

## 1. Where Dalili stands today

### What is already strong

| Area | State |
|---|---|
| Real data | Google Flights / Hotels / Maps / Travel Explore, Open-Meteo, Frankfurter, Wikivoyage, official websites |
| Planning | LangGraph workflow, OR-Tools day routing, 4 plan modes, TripScore, 8 validators + repair loop |
| AI agents | Understanding, route design, critic (verified reflection), concierge (ReAct), review analyst, idea matcher, AI-knowledge fallback |
| Honest prices | Every price has a source and a certainty level; model quotes must appear word for word in their source |
| Cost control | About 11 SerpApi credits for a new city, about 5 for a cached one; 30-day caches |
| Multi-city | Route design with the traveller, multi-city from the search bar |
| Bilingual | Arabic (RTL) and English end to end |
| Tests | 122 tests on recorded real data; agents tested with a scripted model |

### What holds it back

| Problem | Why it matters |
|---|---|
| **One Python process, SQLite, in-process tools** | Can't serve many users; a slow trip (60–120 s) blocks the flow; no background jobs |
| **Vanilla JS in one large `app.js` (~1,400 lines)** | Hard to keep polishing the UI; no components, no type safety |
| **No accounts** | Trips live in browser storage; no "My trips", no sharing, no alerts |
| **A new trip takes a long time** (up to ~2 min with official-price checks) | Users leave before the plan appears |
| **The free SerpApi tier (250/month)** | A demo budget, not a product budget |
| **Web pages are read into the model** (official sites, Wikivoyage) | A prompt-injection surface that needs explicit defences |
| **The plan workspace is read-only** | You change the plan by chatting, not by dragging an activity to another day |

---

## 2. The north star

> **"Tell Dalili your trip in your own words. Get a plan an expert would sign off on, with prices you can trust, and book it at the price you saw."**

### Three promises

Every feature must strengthen at least one of them:
1. **Understood:** one sentence in Arabic or English is enough; Dalili asks only what's missing.
2. **Trusted:**
   - every price shows its source and date;
   - every plan is validated and reviewed by the critic;
   - no invented facts.
3. **Actionable:** every flight, hotel, ticket and table links to the real booking page, at the planned price.

### Who it's for (in order)

1. Arabic-speaking travellers planning a trip abroad (under-served, and our strongest differentiator).
2. Budget-conscious students and young couples ("where can I go with 50,000 EGP?").
3. Families who need a calm, feasible plan (pace, kids, weather).

---

## 3. Experience redesign

### 3.1 Principles

- **One entry point.** A single "tell me about your trip" box, not a form and a chat competing for attention.
- **Show understanding, then act.** The AI turns text into editable chips. The user sees what was understood before anything slow or costly runs.
- **Progress you can feel.** Long research streams partial results (flights first, then hotel, then days) instead of a spinner.
- **Editable plans.** Drag, drop, swap, lock; the planner re-validates instantly.
- **Calm by default, detail on demand.** Technical depth (sources, agent trace) is always one click away, never in the way.

### 3.2 Phase 0: the home page (done in this iteration)

What didn't make sense on the old home page, and what replaced it:

| Before | Problem | Now |
|---|---|---|
| A chat panel **and** a search form, both open | Two ways to start, neither obvious | **One trip box.** The chat opens only once a conversation starts |
| Six structured fields up front | Feels like a booking form, not a guide | **Free text first:** "A week in Italy in November for two, $3,000". The model fills the fields |
| Eyebrow + title + subtitle + section title | The same message repeated four times | One headline and one line |
| The search panel covering the globe | The best visual hidden | **Split layout:** the box on one side, the globe on the other (it mirrors in Arabic) |
| Vibes and destinations failed without a budget | Clicking led to an error | They **pre-fill the box** and show what's missing as dashed chips |
| One button for every case | "Show trips" was wrong when a place was known | **Context-aware actions:** a place → *Plan my trip / Compare prices*; several cities → *Plan this route*; no place → *Find trips that fit* |
| Hidden form fields blocked submission with no message | Silent failure | Validation opens the details and points at the missing field |

How it works technically:
- `POST /api/parse` uses the understanding model only: no searches, no trip created, about 4 seconds.
- The model fills the existing detailed form, which stays available under "Prefer a form?".

### 3.3 The target information architecture

```
Home (trip box, vibes, destinations, how it works)
 ├─ Ideas  - budget-first discovery results (map + cards), filters, "compare two"
 ├─ Plan workspace
 │    ├─ Timeline (days, drag & drop, lock items)      ├─ Map (day routes, what's nearby)
 │    ├─ Stay & travel (flights, hotels, transfers)    ├─ Budget (certainty bar, what-if)
 │    ├─ Checks & expert review                        └─ Chat (concierge; edits the plan)
 ├─ Trip Book (share link, PDF, offline)
 └─ My trips (saved, shared with me, price alerts)
```

### 3.4 The plan workspace (biggest UX upgrade)

- **Map-first split view:** the day timeline on one side and a live map on the other. Hovering an item highlights its pin, and the route redraws on edit.
- **Direct manipulation:**
  - drag an activity to another day;
  - swap a restaurant from its alternatives;
  - lock items so replanning keeps them;
  - "make this day lighter" on the day header.

  Each edit is a structured replan action (the replanner already supports these) and re-validates in about 1 second.
- **Streaming build:** skeleton days appear immediately. Flights, hotel, then days fill in as research finishes. The critic's review appears as a final "Expert review" card.
- **Compare modes side by side:** balanced / budget / comfort / experience in columns, with the differences highlighted.
- **Explain everything:** "Why this?" on every item, from the existing explanations.

### 3.5 Design system

- **Tokens:** colour (dark/light, with contrast checked to WCAG AA), type scale, spacing, radius, elevation, motion.
- **Components:** Button, Chip, Card, Sheet, Dialog, Tabs, Toast, PriceTag (with certainty), SourceBadge, DayTimeline, MapPin.
- **RTL-native:** logical CSS properties only; mirrored icons; the Cairo font for Arabic.
- **Accessibility:**
  - keyboard paths for every action;
  - focus rings;
  - `prefers-reduced-motion`;
  - screen-reader labels;
  - an axe audit in CI.

---

## 4. AI 2.0: from a pipeline with agents to a real agent system

### 4.1 Supervisor + specialists

Today, LangGraph runs a fixed pipeline, and agents act at fixed points. The next step is a **supervisor agent** that owns the conversation and delegates:

| Agent | Role |
|---|---|
| Supervisor | Decides the next step: ask, research, plan, refine, answer; keeps the goal and constraints |
| Researcher(s) | Parallel tool use per domain (flights, stay, places, prices) with budgets |
| Planner | The deterministic optimiser (unchanged; the LLM never schedules) |
| Critic | Verified reflection (keep / roll back); expand to multi-city and budget trade-offs |
| Concierge | ReAct Q&A plus **plan edits** as tool calls (add / move / remove / swap) |
| Price verifier | The price cascade as an agent: decides which source to try next per item |
| Memory keeper | Long-term traveller profile (see 4.3) |

Guardrails stay:
- deterministic validation;
- whitelisted actions;
- bounded steps;
- every fact from a tool.

### 4.2 Model routing (quality and cost)

| Task | Model class |
|---|---|
| Parse / classify / extract prices | Small, fast model (latency is UX) |
| Route design, critic, narration | Strong model |
| Fallback knowledge | Strong model, always labelled |

In addition:
- Cache model outputs by input hash, as already done for the fallback.
- Version prompts; log prompt, model and latency per call.

### 4.3 Memory and personalisation

- **Long-term profile** per account: pace, food, budgets, places loved or skipped, learned from feedback across trips. Explicit instructions always win.
- **Embeddings** (pgvector) of places the traveller liked, to rank candidates ("more like the tavern you loved in Athens").
- **"Why you'll like it"** explanations grounded in that memory.

### 4.4 New inputs

- **Voice:** speech to text in Egyptian Arabic and English into the same trip box.
- **Photo:** "take me somewhere like this". A vision model describes the scene, which is matched to destinations.
- **Screenshots of flight/hotel offers:** extract and compare against Dalili's prices.

### 4.5 Evaluation of AI behaviour

- **Scripted-model tests** for control logic (existing).
- **Golden sets** checked nightly:
  - understanding: 200 labelled Arabic/English requests;
  - price extraction: 100 official pages with known prices;
  - critic: 50 plans with human-rated issues.
- **LLM-as-judge with human spot checks** for narration quality and grounding.
- **Per-agent dashboard:**
  - grounded-answer rate;
  - quote faithfulness (already enforced at 100%);
  - refinements kept vs rolled back;
  - average tool calls per answer.

---

## 5. Prices & data 2.0

| Upgrade | Detail |
|---|---|
| **Headless price reader** | Official sites built with JavaScript (e.g. the Sintra parks) need a headless browser (Playwright) in a sandboxed worker. It would raise official-price coverage from about 60% of sites to a much higher share. |
| **PDF / image menus** | Text extraction and OCR for restaurant menus, with the same verbatim-quote verification |
| **Price history & alerts** | Store every price observed (Postgres); "tell me when flights to Rome drop below X" as background jobs |
| **Freshness rules** | Flights/hotels: minutes to hours. Tickets: 30 days. Tariffs: 90 days. Each shown as "checked on …" |
| **Paid search budget** | Move off the free tier; per-user and per-trip credit budgets; cache shared across users |
| **Booking-capable APIs** | Evaluate flight and hotel APIs that allow real booking or deep links with affiliate tracking. Availability, pricing and terms change often, so compare the current offerings before choosing. |
| **Events & transit** | An events API with a free tier; GTFS feeds for accurate public transport in major cities |
| **Data licences** | Keep attribution for Wikivoyage (CC BY-SA), OpenStreetMap and Wikipedia images; check each API's terms for caching and display |

---

## 6. Architecture 2.0

### 6.1 Today to target

```
TODAY                                    TARGET
Browser (vanilla JS)                     Next.js (React, TypeScript) - SSR home, app routes, PWA
  │                                        │  REST + Server-Sent Events / WebSocket
FastAPI (one process)                    API gateway (FastAPI) - auth, rate limits, validation
  ├─ LangGraph in-request                   │
  ├─ MCP servers in-process              Job queue (Redis + arq/Celery) ─► Worker pool
  ├─ SQLite (trips + HTTP cache)            │    (LangGraph runs, research, price reader, alerts)
  └─ Playwright (tests only)             MCP servers as separate services (stdio → HTTP transport)
                                         Postgres (+pgvector): users, trips, versions, prices, memory
                                         Redis: HTTP/tool cache, sessions, rate limits
                                         Object storage: Trip Book PDFs, images
                                         Observability: OpenTelemetry → traces/metrics; LLM tracing
```

### 6.2 Key decisions

1. **Long work is a job, not a request.**
   - `POST /trips` returns a job id immediately.
   - Progress streams over SSE.
   - A crash never loses a half-built plan: LangGraph checkpoints in Postgres.
2. **One source of truth for a trip:** versioned Trip State in Postgres, with diffs between versions. This enables undo, "compare with yesterday", and sharing.
3. **The MCP servers become services.** The protocol boundary already exists, so they can scale and deploy independently.
4. **Accounts:** email or Google sign-in. Anonymous trips can be claimed after sign-up.
5. **Configuration and secrets:** environment variables locally; a secret manager in the cloud; keys never in logs (already enforced).
6. **Deployment:**
   - Docker Compose for local development.
   - One container per service in the cloud. Since the model is already on Azure AI Foundry, Azure Container Apps is a natural fit.
   - CI/CD with GitHub Actions: test → build → deploy to staging → smoke test → production.

### 6.3 Frontend migration without a big-bang rewrite

1. Put the current UI behind a clean API contract (OpenAPI + generated TypeScript types).
2. Build the new Next.js app page by page, starting with the Home and the Plan workspace.
3. Keep the globe (Three.js) and the Trip Book as isolated components.
4. Switch routes over one at a time, then retire `app.js`.

---

## 7. Quality: testing and evaluation

| Layer | What | When |
|---|---|---|
| Unit | Parsers, validators, pricing rules, matching | Every commit |
| Contract | MCP tools and providers against recorded real responses (existing replay cache) | Every commit |
| Agent | Scripted-model tests for the supervisor, critic, concierge and price verifier | Every commit |
| End to end | Playwright flows: trip box → plan → edit → book dialog, in Arabic and English, dark and light | Every pull request |
| Visual | Screenshot diffs of key screens | Every pull request |
| Accessibility | axe audit, keyboard-only run | Every pull request |
| Live canary | 3 real trips per night on a small credit budget; alert on failures or price-coverage drops | Nightly |
| Golden sets | Understanding, price extraction, critic (see 4.5) | Nightly |

---

## 8. Security & privacy

- **Prompt injection from the web.** Official websites and Wikivoyage are untrusted input:
  - pass page text only as data;
  - never follow instructions found in it;
  - strip hidden text;
  - accept only verbatim-verified values (already the rule for prices);
  - limit which agent can see raw pages.
- **SSRF:** page fetching accepts only public http(s) hosts (done). Add DNS rebinding checks and a size and time budget in the worker.
- **Keys:**
  - in a secret manager;
  - rotated regularly;
  - redacted everywhere (done);
  - a separate key per environment.
- **Personal data:**
  - store only what planning needs;
  - "delete my data" button;
  - trip share links are unguessable and revocable.
- **Abuse:** per-user rate limits and credit budgets (protects the paid APIs), and bot protection on sign-up.

---

## 9. Phased roadmap

Durations are estimates for one developer. Each phase ends with a demo and its "done" checks.

| Phase | Weeks | Deliverables | Done when |
|---|---|---|---|
| **0. Home v3** ✅ | done | Trip box + AI parse + chips + context-aware actions; split layout with the globe | Arabic/English flows pass; no layout overflow; chat only after the conversation starts |
| **1. Plan workspace** | 2–3 | Map-first split view, drag & drop between days, lock items, per-day "lighter / swap", mode comparison | Any edit re-validates in < 2 s; an undo exists |
| **2. Speed & streaming** | 2 | Research as background jobs; SSE partial results (flights → hotel → days); parallel price checks with budgets | First useful result < 10 s; full plan < 45 s (p50) |
| **3. Accounts & trips** | 2 | Sign-in, My trips, versions, share links, claim anonymous trips | A trip survives a device change; share link is read-only |
| **4. Platform** | 3 | Postgres (+pgvector), Redis, workers, Docker, cloud deploy, CI/CD, tracing | Staging + production environments; one-command local setup |
| **5. Frontend migration** | 3–4 | Next.js + design system; Home and Workspace migrated; Trip Book as a shareable page | Visual parity + accessibility audit clean |
| **6. AI 2.0** | 3 | Supervisor agent, concierge plan edits, model routing, memory, golden-set evals | Golden sets meet targets; cost per trip tracked |
| **7. Prices 2.0** | 2–3 | Headless reader, PDF/OCR menus, price history, alerts | Official-price coverage ≥ 80% of sites with a price page |
| **8. Mobile & offline** | 2 | Installable app on the phone (PWA), offline Trip Book, push alerts | Trip Book usable with no network |
| **9. Booking (stretch)** | — | Affiliate or API booking for flights and hotels | A test booking completes end to end in sandbox |

**For the graduation defence**, phases 1 and 2 (plus a slice of 3) give the most visible jump. Phases 4 onward make it a product.

---

## 10. How we'll know it's working

| Metric | Now (approx.) | Target |
|---|---|---|
| Time to first useful result | 60–120 s (spinner) | < 10 s (streaming) |
| Full plan time (p50) | 60–120 s | < 45 s |
| SerpApi credits per new city | ~11 | ≤ 8 (shared cache across users) |
| Share of plan cost from published prices | ~70% in tests | ≥ 85% |
| Official-price coverage (sites with a price page) | ~3 of 5 | ≥ 4 of 5 |
| Requests understood without a follow-up question | not measured | ≥ 80% |
| Critic refinements kept | not tracked | tracked; ≥ 70% |
| Plans that pass all hard checks | 99.8% | ≥ 99.5% (keep) |
| Accessibility issues (axe, serious) | not measured | 0 |

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| API costs grow with users | Shared caches, per-user budgets, model routing, a paid plan sized from real usage |
| Official sites block automated reading | Respect robots.txt, identify the reader, cache 30 days, fall back to labelled estimates |
| Model changes break behaviour | Pinned model versions, golden-set gates in CI, prompt versioning |
| Rewrite fatigue (frontend migration) | Page-by-page migration behind a stable API; never a big-bang switch |
| Scope creep before the defence | Freeze after phase 2 for the defence; everything else is the post-graduation roadmap |
| Legal (data licences, scraping, booking) | Keep attribution; read each API's terms; booking only through official partner programmes |

---

## 12. This week

- [ ] Plan workspace: turn the itinerary list into a timeline with drag handles (front end only, behind a flag).
- [ ] Wire drag & drop to existing replan actions (`replace_item`, day moves) and show the diff toast.
- [ ] Stream partial results: emit `flights.ready`, `hotels.ready`, `day.ready` events from the workflow and render skeleton days.
- [ ] Add `/api/parse` to the eval: 50 Arabic + 50 English requests with expected fields.
- [ ] Write the OpenAPI contract for the endpoints the new front end will use.
