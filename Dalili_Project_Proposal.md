# Dalili (دليلي): An Agentic AI Travel Planner

> **"Tell me your budget, when you can go, and what you love. I'll plan the whole trip, from real data, and you book it."**

Graduation Project Proposal

---

## Table of Contents

1. [The Idea in One Page](#1-the-idea-in-one-page)
2. [The Problem](#2-the-problem)
3. [Why Existing Solutions Fall Short](#3-why-existing-solutions-fall-short)
4. [Proposed Solution](#4-proposed-solution)
5. [Objectives](#5-objectives)
6. [Scope](#6-scope)
7. [Target Users and a Sample Journey](#7-target-users-and-a-sample-journey)
8. [Core Features](#8-core-features)
9. [System Architecture](#9-system-architecture)
10. [The AI Approach: Agents, Tools and Orchestration](#10-the-ai-approach-agents-tools-and-orchestration)
11. [Real Data Sources](#11-real-data-sources)
12. [Planning and Optimization Algorithms](#12-planning-and-optimization-algorithms)
13. [Validation, Repair and Trustworthiness](#13-validation-repair-and-trustworthiness)
14. [Personalization, Feedback and Replanning](#14-personalization-feedback-and-replanning)
15. [Multi-City Journeys and Route Design](#15-multi-city-journeys-and-route-design)
16. [Trip Ideas for a Budget](#16-trip-ideas-for-a-budget)
17. [From Plan to Booking](#17-from-plan-to-booking)
18. [User Experience and Interface](#18-user-experience-and-interface)
19. [Data Model: the Trip State](#19-data-model-the-trip-state)
20. [Technology Stack](#20-technology-stack)
21. [Reliability, Cost and Security](#21-reliability-cost-and-security)
22. [Testing and Evaluation Plan](#22-testing-and-evaluation-plan)
23. [Risks and Mitigations](#23-risks-and-mitigations)
24. [Known Limitations](#24-known-limitations)
25. [Work Plan](#25-work-plan)
26. [Future Work](#26-future-work)
27. [Expected Contributions](#27-expected-contributions)
28. [Glossary](#28-glossary)
29. [Suggested Presentation Outline](#29-suggested-presentation-outline)

---

## 1. The Idea in One Page

**Dalili** (Arabic *دليلي*, "my guide") will be an **AI travel agent** that plans a complete trip for any city in the world that has an airport:

- flights,
- hotel,
- a day-by-day itinerary (sights, restaurants, free time),
- transport between places,
- the weather,
- a budget breakdown,
- a printable **Trip Book**.

What makes it different from a chatbot that "suggests a trip":

| Typical AI chatbot | Dalili |
|---|---|
| Invents flights, prices and opening hours | Uses **real, live data** (Google Flights, Google Hotels, Google Maps, weather, exchange rates) |
| One long text answer | A **structured plan** that is optimized, validated and scored |
| No guarantee the plan is feasible | **8 automatic checks** (budget, schedule, opening hours, walking distance, weather…) with an automatic **repair loop** |
| Starts over when you change something | **Targeted replanning**: "make it cheaper", "I don't want to wake up before 10", "add the Pyramids" |
| Never checks its own work | A **critic agent** reviews every new plan like a senior travel planner, fixes what it safely can, and **verifies** the refined plan is better before showing it |
| Answers questions from memory | A **concierge agent** that reasons step by step and calls **live tools** before answering (ReAct) |
| No path to booking | Every flight and hotel links to its **real booking page, at the planned price** |

**The AI plans; the user books.** Dalili will never pay for or book anything on the user's behalf. It hands over a verified plan and the links to book it.

---

## 2. The Problem

Planning a trip is a long, fragmented, error-prone task:

1. **Too many tools:** flights on one site, hotels on another, maps, reviews, weather, currency converters, blogs, and forums.
2. **Hours of work:** travellers typically spend many hours researching a single trip, jumping across dozens of tabs.
3. **Hidden conflicts:**
   - A museum is closed on the only day you planned it.
   - A 6 am flight means a 3 am hotel checkout.
   - Two sights are 40 minutes apart but scheduled 10 minutes apart.
4. **Budget uncertainty:** people don't know whether a destination is affordable until they have added everything up by hand.
5. **Language barrier:** most planning tools are English-first. Arabic-speaking travellers are poorly served.
6. **Generic AI answers can't be trusted:** large language models (LLMs) produce confident itineraries with **invented prices, closed restaurants and non-existent places** ("hallucinations").

---

## 3. Why Existing Solutions Fall Short

| Category | Examples | Limitation |
|---|---|---|
| Booking sites | Booking.com, Expedia, Skyscanner | Sell one component (flight *or* hotel). No itinerary, no reasoning about the whole trip. |
| Map / review apps | Google Maps, TripAdvisor | Great data, but the user still has to assemble the plan. |
| Itinerary apps | Wanderlog, TripIt | Organize what *you* already decided. They don't plan or check feasibility. |
| General chatbots | ChatGPT, Gemini (plain) | Fluent but **ungrounded**: invented prices and hours, no validation, no live availability. |

**The gap:** no tool combines **natural conversation**, **real live data**, **mathematical optimization** and **automatic verification** into one trustworthy plan.

---

## 4. Proposed Solution

Dalili will combine six ideas:

1. **Conversational understanding (LLM).** The traveller writes naturally, in **Arabic or English**. An LLM extracts a structured *Trip Contract*: destination(s), dates, budget, travellers, interests, pace and constraints.
2. **Tool-using agents (MCP).** Specialized agents call **real APIs** through **8 MCP servers** (flights, hotels, places, activities, transport, weather, currency, knowledge). The LLM never invents facts; it reasons over retrieved data.
3. **Optimization.** Each day is solved as a **routing problem with time windows** (Google OR-Tools): the best visiting order that respects opening hours, meal times and walking limits.
4. **Validation and repair.** Deterministic validators check every plan. Violations trigger a **repair loop** that fixes the plan and re-validates it before the user ever sees it.
5. **Continuous personalization.** The system learns from feedback ("fewer museums", "more food") and replans only what needs to change.
6. **A team of specialist AI agents.** Beyond understanding, dedicated agents handle what needs judgement:
   - a **critic** that reviews and refines each plan (self-reflection);
   - a **concierge** that answers questions by planning tool calls over live data (ReAct);
   - a **review analyst** that reads real guest reviews (aspect-based sentiment);
   - a **route designer** that negotiates multi-country routes with the traveller;
   - a **matcher** that scores destination ideas against the traveller's interests.

```
LLM understanding + LangGraph orchestration + 8 MCP servers over real APIs + structured Trip State
+ OR-Tools optimization + 8 validators + repair loop + critic (self-reflection) + concierge (ReAct)
+ review analyst + feedback learning  =  a verified, expert-reviewed Trip Book
```

---

## 5. Objectives

### Main objective

Build an AI agent that turns a free-text travel request into a **complete, feasible, budget-accurate and personalized trip plan grounded in real data**.

### Specific objectives

1. Understand travel requests in **Arabic and English**, and ask only for missing essentials.
2. Retrieve **real** flights, hotels, places, events, transfers, weather and exchange rates.
3. Produce **four plan variants**: balanced, budget, comfort and experience. Each is scored by a comparable **TripScore (0–100)**.
4. Guarantee feasibility with **automatic validation and repair**.
5. Support **replanning** from natural feedback in about a second, without re-searching.
6. Support **multi-city / multi-country journeys**, with a route designed *together with* the traveller.
7. Suggest **destinations that fit a budget and the traveller's interests**.
8. Be **honest**: label every estimate and never present a guess as a fact.
9. Stay **usable when a data source fails**, through a clearly labelled AI-knowledge fallback.
10. Deliver a polished, bilingual, accessible interface with a **Trip Book** that can be exported.

---

## 6. Scope

### In scope

- Leisure trips to any city with an airport; single-city and multi-city.
- Flights (round trip and one-way legs), hotels, restaurants, attractions, events, airport transfers, intercity train/coach legs.
- Weather-aware and budget-aware planning in any currency.
- Arabic (Egyptian dialect in replies) and English, with right-to-left layout.
- A web application (chat + live trip board + Trip Book).

### Out of scope

- **Payments and booking.** The user books through the linked providers.
- Visa processing and travel insurance purchase (informational tips only).
- Real-time trip tracking during travel.

---

## 7. Target Users and a Sample Journey

**Users:**
- Students and young travellers on a budget.
- Couples and families.
- Arabic-speaking travellers.
- Anyone who wants a trustworthy plan without spending hours researching.

**Sample journey:**

1. Mariam opens Dalili and writes, in Arabic: *"عايزة أسافر برشلونة من دبي من 4 لـ 9 ديسمبر، اتنين، 4000 دولار، بنحب الفن والبحر، طيران مباشر بس."* ("I want to go to Barcelona from Dubai, December 4 to 9, two people, 4,000 dollars, we love art and the sea, direct flights only.")
2. Dalili understands the request and shows friendly progress messages ("Searching flights…", "Planning each day…"). A 3D globe spins, then locks onto the Dubai → Barcelona route.
3. Within about 30 seconds she gets:
   - direct flights at real prices;
   - a hotel with photos and reviews;
   - a 6-day itinerary with a beach day (because she loves the sea);
   - weather for each day;
   - a budget breakdown;
   - a TripScore.
4. She types *"make it cheaper and I don't want to wake up before 10."* The plan is updated in about a second, and Dalili explains exactly what changed.
5. She clicks **Book this trip**. Every flight and the hotel open on real booking pages at the planned price.
6. She downloads the **Trip Book**: a 21-section travel guide with maps, phrases, a packing list and emergency information.

---

## 8. Core Features

### 8.1 Conversation and understanding
- Free-text requests in Arabic or English. Replies follow the traveller's language.
- Asks only for what is missing (e.g. no origin → "Where are you travelling from?"), and never guesses vague destinations.
- Answers travel questions ("Do I need to tip?") from travel-guide knowledge (retrieval-augmented generation, RAG).

### 8.2 Research on real data
- Live flight fares and schedules, hotel prices, ratings, amenities and photos.
- Restaurants and sights with real opening hours, ratings and price levels.
- Local events, airport transfer times, walking and driving times.
- Weather forecast (and last year's observed weather for distant dates).
- Currency conversion into the traveller's currency.

### 8.3 Planning
- Four modes (balanced, budget, comfort, experience), each a full plan.
- Day-by-day itinerary optimized for opening hours, meals, walking distance and energy.
- Interest-aware: a traveller who loves the sea gets a real beach on a suitable day. One who loves food gets food experiences.
- **Named places are guaranteed:** "I want to visit the Pyramids" places that exact site in the plan, marked "★ you asked".

### 8.4 Verification
- 8 validators plus a repair loop (Section 13).
- A TripScore that breaks down budget fit, comfort, food, activities, transport, personal fit and schedule quality.

### 8.5 Replanning and "what-if"
- "Make it cheaper", "fewer museums", "more free time", "stay two more days", "remove the Colosseum".
- **What-if analysis:** "What if I increase my budget by $500?" gives a side-by-side comparison on a copy, applied only if the user accepts.
- A clear **diff** of what changed.

### 8.6 Multi-city journeys
- "A Europe tour: Italy, France and Spain."
- Dalili proposes a route (bases, nights, day trips), discusses it with the traveller, and plans it once accepted (Section 15).

### 8.7 Trip ideas for your budget
- Enter a budget, dates (or a flexible month), who is travelling and interests.
- Get real destinations with live flight and hotel prices, a **match percentage** and a reason for each (Section 16).

### 8.8 Booking handoff
- "Book this trip" lists every leg and hotel in booking order.
- Hotel offers from several booking sites for the exact dates, with the offer matching the plan's price highlighted.

### 8.9 Trip Book
- A 21-section guide:
  - overview, profile, flights, hotel, destination overview, daily itinerary, restaurants, activities;
  - transport, budget, daily spending, packing list, documents checklist, weather;
  - local tips, useful phrases, emergency information, maps, alternatives, important notes;
  - sources with data timestamps.
- Printable and exportable to PDF and Markdown.

---

## 9. System Architecture

```text
┌───────────────────────────── Web client (HTML/CSS/JS) ─────────────────────────────┐
│  Chat panel  ·  3D globe (Three.js)  ·  Trip board (tabs, maps)  ·  Trip Book      │
│  Arabic/English (RTL) · dark/light theme · booking & hotel-offer dialogs           │
└──────────────────────────────────────┬──────────────────────────────────────────────┘
                                       │  REST + Server-Sent Events (live progress)
┌──────────────────────────────────────▼──────────────────────────────────────────────┐
│  FastAPI backend (api.py)  →  Service layer (sessions, what-if, persistence)        │
│                                                                                     │
│  LangGraph "Travel Manager" workflow                                                │
│  understand ─┬→ question → CONCIERGE agent (ReAct over live tools) → answer         │
│              └→ check requirements → (ask | ROUTE-DESIGN agent | research)          │
│      → research in parallel [flights | hotels | restaurants | attractions+events    │
│                              | weather]                                             │
│      → collect & enrich (FX, city price level, transfers, REVIEW-ANALYST agent,     │
│                          travel-time matrices)                                      │
│      → plan (4 modes) → validate ─┬─→ repair → plan   (loop)                        │
│                                   └─→ finalize (TripScore, diff)                    │
│      → CRITIC agent ─┬─→ safe fixes → plan → validate → finalize → verify (keep     │
│                      │                                   only if not worse)         │
│                      └─→ respond (+ one-tap suggestions)                            │
└──────────────────────────────────────┬──────────────────────────────────────────────┘
                                       │  Model Context Protocol (MCP)
┌──────────────────────────────────────▼──────────────────────────────────────────────┐
│  8 MCP servers: flights · hotels · places · activities · transport · weather ·      │
│                 currency · knowledge                                                │
│  Each tool → real provider; on failure → labelled AI-knowledge fallback             │
└──────────────────────────────────────┬──────────────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────────────┐
│  HTTP layer: persistent cache with per-source TTL · quota guard · key redaction ·   │
│              record/replay for testing                                              │
│  Providers: SerpApi (Google Flights/Hotels/Maps/Travel Explore/Directions),         │
│             Geoapify, openrouteservice, Open-Meteo, Frankfurter, Wikivoyage         │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### Main modules (planned)

| Module | Responsibility |
|---|---|
| `nlu.py`, `llm.py` | Language understanding with structured LLM outputs |
| `workflow.py` | LangGraph state machine (the "Travel Manager") |
| `mcp_servers/*`, `mcp_hub.py` | 8 MCP tool servers and the client hub |
| `providers/*` | Real API integrations and the AI fallback |
| `research.py` | Parallel research agents and data enrichment |
| `engine/optimizer.py` | Routing with time windows (OR-Tools) |
| `engine/planner.py` | Itineraries, meals, energy-aware days, 4 modes |
| `engine/validators.py`, `repair.py`, `scoring.py` | Checks, repair loop, TripScore |
| `replanner.py` | Feedback, learning, targeted replanning, diffs |
| `agents/critic.py` | Critic agent: expert review, safe fixes, verified refinement |
| `agents/concierge.py` | Concierge agent: ReAct loop over live MCP tools, follow-up actions |
| `agents/review_analyst.py` | Review-analyst agent: aspect-based sentiment over real guest reviews |
| `agents/trace.py` | Agent trace (thoughts, tool calls, observations, decisions) for transparency |
| `journey.py`, `route_design.py` | Multi-city journeys and collaborative route design |
| `suggest.py` | Trip ideas for a budget and interests |
| `knowledge.py` | Travel-guide RAG (Wikivoyage) |
| `tripbook.py` | Trip Book generation (HTML and Markdown) |
| `api.py`, `service.py`, `store.py` | HTTP API, sessions, SQLite persistence |

---

## 10. The AI Approach: Agents, Tools and Orchestration

### 10.1 Division of labour

The LLM is used for what it is good at, and **deterministic code** for what must be correct:

| Task | Done by |
|---|---|
| Understanding free text in any language; route design; explaining; ranking ideas by fit | **LLM** |
| Fetching prices, hours, distances, weather | **Real APIs via MCP tools** |
| Choosing and ordering activities | **Optimization algorithm** |
| Checking feasibility and budget | **Deterministic validators** |
| Fixing violations | **Repair loop** (rules + re-optimization) |
| Judging whether a feasible plan is actually *good* | **Critic agent** (LLM), with fixes verified by code |
| Answering open questions about the trip | **Concierge agent** (LLM + live tools) |
| Reading hundreds of guest reviews | **Review-analyst agent** (LLM), quotes checked against the source |

### 10.2 Structured understanding

The LLM returns a **typed JSON object** (validated with Pydantic), not free text. Its fields include:
- destinations and countries;
- dates;
- budget and currency;
- travellers;
- interests, pace, dietary needs and must-visit places;
- the travellers' answer to a route proposal.

This makes understanding **testable and safe**: an invalid output is rejected, not executed.

Understanding must come from the model, not hand-written keyword rules, so that any phrasing in Arabic or English works. A small rule-based parser is kept only as an **offline backup**.

### 10.3 Model Context Protocol (MCP)

Every data capability is exposed as an **MCP tool** (an open standard for connecting AI systems to tools):

| Server | Example tools |
|---|---|
| flights | `search_flights`, `search_one_way_flights`, `autocomplete_airports`, `find_flight_deals` |
| hotels | `search_hotels`, `get_hotel_reviews`, `get_hotel_photos`, `get_hotel_offers` |
| places | `search_restaurants`, `search_places`, `find_place`, `get_place_reviews` |
| activities | `search_attractions`, `search_events`, `explore_destinations` |
| transport | `get_directions`, `travel_time_matrix`, `get_airport_transfers`, `get_intercity_journeys` |
| weather | `get_weather_forecast`, `get_weather_risk` |
| currency | `get_exchange_rates`, `convert_currency` |
| knowledge | `resolve_place`, `get_destination_info`, `search_travel_knowledge` |

**Benefits:**
- **Modularity:** each server can run as a separate process.
- **Replaceability:** swapping a provider does not touch the planner.
- **Clean separation:** reasoning is separate from data access.

### 10.4 LangGraph orchestration

The workflow is an explicit **state graph**, not an open-ended agent loop. This gives:
- **predictable** control flow (understand → research → plan → validate → repair);
- **parallel** research branches;
- **observable** progress: each node streams a status to the UI;
- **bounded** loops: the repair loop has a maximum number of iterations.

### 10.5 The agent team

Dalili is a **multi-agent system**. Each agent has one job, its own tools, a typed output schema and a deterministic fallback:

| Agent | Pattern | Input → Output | Tools |
|---|---|---|---|
| **Understanding agent** | Structured extraction | Free text (AR/EN) → Trip Contract, feedback actions, route decisions | — |
| **Route-design agent** | Planning + human-in-the-loop | Countries, must-see places → bases, nights, day trips; iterates with the traveller | Google Maps, Geoapify |
| **Research agents** (×5, parallel) | Tool use | Trip Contract → flights, hotels, restaurants, sights, weather | 8 MCP servers |
| **Review-analyst agent** | Aspect-based sentiment analysis | Guest reviews → verdict, 1–5 score per aspect, pros/cons, noise level with verbatim quotes | Google Hotels reviews |
| **Planner** (not an LLM) | Constraint optimization | Research → 4 day-by-day plans | OR-Tools |
| **Validator + repair** (not an LLM) | Rule checking | Plan → violations → fixes | — |
| **Critic agent** | Reflection (generate → critique → refine → verify) | Plan + profile + unused top sights → quality score, issues, safe fixes | Planner actions |
| **Concierge agent** | ReAct (reason + act) | Question → multi-step tool calls → grounded answer + follow-up actions | Places search, directions, weather, currency, travel guide, plan lookup |
| **Idea-matcher agent** | LLM-as-judge ranking | Destinations with live prices + interests, company, season → match % and reason | Google Travel Explore |
| **Fallback-knowledge agent** | Graceful degradation | Failed live tool → labelled estimates, location-verified | Geoapify |
| **Narrator** | Grounded generation | Plan facts → friendly reply in the traveller's language | — |

### 10.6 Agentic design patterns used

1. **Tool use over a standard protocol (MCP):** agents never guess facts; they call tools.
2. **ReAct:** the concierge alternates *thought → tool call → observation* for up to 5 steps, then must answer. Each observation is added to its scratchpad, so later steps build on real data.
3. **Reflection / self-critique:** the critic judges quality where rules can't (a missing icon, a heavy first day, outdoor visits on the rainy day), proposes fixes as planner actions, and the system **re-plans, re-validates and re-scores**. The refinement is **kept only if it is not worse** (no new errors, TripScore not lower by more than a point). Otherwise it is rolled back.
4. **Guardrails on agent actions:**
   - Only whitelisted, data-grounded fixes run automatically (e.g. add a place *that exists in the research data*, lighten a *specific* day).
   - Anything else becomes a one-tap suggestion for the traveller.
   - Review quotes the model cites must appear in the real reviews.
5. **Human in the loop:** route proposals wait for the traveller's approval, and agent suggestions are offered, never forced.
6. **Structured outputs:** every agent returns a Pydantic-validated schema. Invalid output is rejected and the deterministic fallback runs.
7. **Memory:** the traveller profile learns from feedback across turns; explicit instructions always win.
8. **Bounded autonomy:** loops have hard limits (5 ReAct steps, 1 reflection round, N repair iterations).
9. **Observability:** every agent step (thought, tool, observation, decision, fix) is recorded in an **agent trace**, which a developer "AI view" can display.

### 10.7 Illustration: the concierge at work

> **Traveller:** "فيه مطعم سوشي كويس قريب من الفندق؟ وهل هتمطر يوم 3؟" ("Is there a good sushi place near the hotel? And will it rain on day 3?")

| Step | Thought | Tool | Observation (real data) |
|---|---|---|---|
| 1 | I need the hotel and day 3's date. | `plan_lookup` | Hotel NLH Kerameikos; day 3 = Sat 5 Dec, 80% rain, 12–15 °C |
| 2 | Search sushi near the hotel. | `search_nearby("sushi", near=hotel)` | Sushimou 4.8★ (1,134 reviews) 1.2 km; Kyoko 4.9★ 1.7 km… |
| 3 | I have enough. | `final_answer` | Answer in Egyptian Arabic, plus follow-ups: "Add Sushimou to day 3 dinner" |

The follow-up is a one-tap reply. Tapping it makes the planner add the restaurant to the plan.

### 10.8 Illustration: the critic at work

Take a 6-day Athens plan that the critic scores **68/100**. It can make two safe fixes automatically:
- lighten the first day after arrival;
- add the Panathenaic Stadium, an iconic sight that is missing.

The system then re-plans and re-validates. It **keeps** the refinement only if the plan is not worse (for example, TripScore 93 → 92 is within tolerance, with no new errors). Issues that need the traveller's judgement, such as "replace an outdoor visit on the rainy day 2", are offered as suggestions.

### 10.9 LLM provider

- **Default:** a hosted model through **Azure AI Foundry** (OpenAI-compatible API).
- **Alternative:** Anthropic Claude.

The provider is configurable, and the system degrades gracefully when the model is unavailable.

---

## 11. Real Data Sources

| Domain | Source | Used for |
|---|---|---|
| Flights | **SerpApi → Google Flights** | Real fares, schedules, stops, carbon, booking links |
| Hotels | **SerpApi → Google Hotels** | Nightly prices, ratings, amenities, photos, reviews, **per-site booking offers** |
| Places & food | **SerpApi → Google Maps / Local** | Restaurants and sights with opening hours, ratings, price levels, reservation links |
| Events & ideas | **SerpApi → Google Events, Google Travel Explore** | Local events; destination ideas with prices |
| Transport | **SerpApi → Google Maps Directions**, **openrouteservice** | Airport transfers, intercity legs, walking/driving matrices |
| Geocoding | **Geoapify** | Coordinates, countries, reverse geocoding |
| Weather | **Open-Meteo** | Forecast (≤ 14–16 days) and historical archive |
| Currency | **Frankfurter** (central-bank rates) | Converting every price to the traveller's currency |
| Knowledge | **Wikivoyage** + CLDR | Destination guides, phrases, emergency numbers, etc. |

### Honesty rules

1. A price is either **known** (published by a provider) or **estimated** (e.g. entry tickets). Estimates are always labelled.
2. When opening hours are unknown, typical hours are assumed, flagged "check before going", and the validator issues a *warning* only.
3. Weather beyond the forecast range uses **last year's observations**, with low confidence.
4. Unknown facts (e.g. cancellation terms) are shown as **unknown**, never guessed.
5. Every data point carries **metadata**: source, timestamp and confidence.

---

## 12. Planning and Optimization Algorithms

### 12.1 Candidate ranking

Places are ranked by:
- relevance to the traveller's interests (with interest expansion, e.g. "art" → galleries, museums, street art);
- quality (rating weighted by review count);
- price level versus the plan mode;
- distance from the hotel.

"Hidden gems" (well-rated, fewer reviews) can be boosted.

### 12.2 Daily route optimization: VRP with time windows

Each day is modelled as a **single-vehicle routing problem with time windows (VRPTW)**:
- **Nodes:** hotel + candidate stops, each with a visit duration, opening-hour windows and a priority.
- **Edges:** real walking/driving times from openrouteservice matrices.
- **Constraints:** opening hours, a lunch break, day start and end times, maximum walking per leg.
- **Objective:** minimize travel time while maximizing the priority of visited stops. Low-priority stops can be dropped at a penalty when not everything fits.

It is solved with **Google OR-Tools**, with a greedy fallback when no solution is found.

### 12.3 Itinerary construction

- **Energy-aware pacing:** relaxed / moderate / packed day capacity; rest blocks after heavy days.
- **Food timeline:** breakfast, lunch and dinner at suitable places near the route (dietary filters such as vegetarian or halal); coffee and dessert stops for food lovers.
- **Arrival/departure days** adapt to flight times (no activities before landing; checkout respects the flight).
- **Weather:** outdoor activities are moved away from rainy days where possible.

### 12.4 Four plan modes

Every request produces four complete plans. They differ in hotel choice, flight choice, activity density and restaurant price level:

| Mode | Emphasis |
|---|---|
| Balanced | Overall quality |
| Budget | Lowest cost |
| Comfort | Better hotel, direct flights, more rest |
| Experience | More activities and food experiences |

### 12.5 TripScore (0–100)

A weighted score over seven dimensions:
- budget fit,
- comfort,
- food,
- activities,
- transportation,
- personal fit,
- schedule quality.

The weights differ per mode, for example:
- **budget:** budget fit weighs 30%;
- **comfort:** comfort weighs 26%.

This lets the user compare plans on one scale, with the breakdown shown as a radar chart.

---

## 13. Validation, Repair and Trustworthiness

### 13.1 The 8 validators

| Validator | Checks |
|---|---|
| Budget | Total ≤ limit (with a safety buffer); category breakdown |
| Schedule | No overlaps; meals at sensible times; respects day start/end and flights |
| Distance | Every walking leg within the traveller's tolerance |
| Opening hours | Each visit falls inside real opening hours |
| Preferences | Interests covered; dislikes avoided; must-visit places present |
| Energy | Daily load matches the chosen pace |
| Weather | Outdoor plans on high-risk days are flagged or moved |
| Reality | Every place comes from retrieved data (**no hallucinated places**) |

### 13.2 Repair loop

```
plan → validate → violations? → repair actions (swap hotel, drop/replace stop, move to another day,
                                change flight, reduce density) → re-plan → validate … (bounded)
```

The user only sees plans that pass, or plans whose remaining issues are **explained transparently**.

### 13.3 Graceful degradation (AI-knowledge fallback)

If a live source fails or runs out of quota, the MCP tool falls back to the LLM's general knowledge. Examples:
- airlines that fly a route and typical fares;
- well-known hotels and attractions;
- estimated transfer times.

These results are:
- labelled `ai_knowledge` / "estimated";
- **location-verified** with Geoapify;
- shown with a visible "AI estimates · verify before booking" badge.

Free sources (weather, exchange rates, Wikivoyage) stay live.

---

## 14. Personalization, Feedback and Replanning

- **Traveller profile:** pace, interests, food preferences, dietary needs, walking tolerance, start time, flight preferences, noise tolerance, nightlife.
- **Feedback understanding:** "fewer museums", "more hidden gems" and "I'm tired of walking" become structured actions.
- **Targeted replanning:**
  - Only the affected parts are recomputed, over cached research, so no new searches are needed (about **1 second**).
  - Changing dates re-searches only flights and hotels.
- **Learning:** repeated feedback updates the profile ("learned from your feedback"). Explicit instructions always override learned preferences.
- **Diffs:** every change is explained, e.g. "Day 2: removed Roman Forum; starts 10:00 instead of 08:30."
- **What-if:** budget scenarios are computed on a copy and compared side by side before being applied.

---

## 15. Multi-City Journeys and Route Design

### 15.1 Collaborative route design

When the traveller names **countries or a region** instead of cities, for example:

> *"A Europe tour: Spain, Italy and France. I want the Leaning Tower of Pisa, the Eiffel Tower and the famous church in Barcelona."*

Dalili will:

1. Locate each named place on Google Maps (real coordinates).
2. Ask the LLM to design **bases, nights and day trips** (e.g. Florence as the base for Pisa).
3. Verify every city against real data. A named place far from every base triggers a redesign, or moves that country's base next to it.
4. Order the stops for the **shortest total travel** (unless the user fixed an order) and fit the nights to the dates.
5. Show the proposal in the chat and on the globe, and **wait for the traveller**. They can accept ("Plan this route") or reply in their own words: "more nights in Paris", "drop Spain", "you decide". Each reply produces a new proposal.

### 15.2 Journey planning

- Each city is researched in parallel.
- Each leg is priced as a **flight** (≥ 350 km) and/or **train/coach** (≤ 700 km). Ground options are preferred only when they are not much slower than flying.
- The day you move between cities becomes one **travel day**: morning in city A, arrival in city B.
- The budget is shared across cities, and validation and scoring run on the whole journey.

---

## 16. Trip Ideas for a Budget

For travellers who don't know where to go yet.

### Inputs
- Budget and currency.
- Departure city and number of travellers.
- **When:** a flexible month and length, or exact dates.
- **Who's going:** solo, couple, honeymoon, family, friends.
- **Interests:** beaches, museums & culture, history, nature, snow & skiing, food, nightlife, shopping, relaxation, adventure.
- Optional: direct flights only, maximum flight time, free-text wishes ("warm weather, not crowded").

### Method
1. Search **Google Travel Explore** from the traveller's airport with their dates, passengers and flight limits. Interests Google supports (beaches, museums, history, outdoors, skiing) get dedicated searches.
2. Cost each destination for the group: `flights × travellers + hotel nights × rooms`.
3. Classify each destination:
   - **Comfortable:** ≥ 25% of the budget left for food and activities.
   - **Tight:** within budget, but with little left.
   - **Over budget:** shown only if too few destinations fit, and clearly marked.
4. The LLM scores every destination's **fit (0–100%)** against the interests, the company, the wishes and the **season of the dates** (a beach lover shouldn't get a cold city in December), and writes a one-line reason in the traveller's language.
5. Clicking an idea starts planning with all the preferences carried over.

---

## 17. From Plan to Booking

The AI plans; the user books. To make booking effortless:

- **Book this trip:** one dialog listing every flight / train leg and every hotel in booking order, with the estimated trip total.
- **Flights:** deep links to Google Flights with the exact itinerary.
- **Hotels:**
  - Live **offers from several booking sites** (e.g. Booking.com, Hostelworld, the hotel's official site) for the exact dates and guests.
  - Each offer shows its nightly and total price, free-cancellation or official-site badges, and a link to **that site's booking page**.
  - The offer closest to the price used in the plan is highlighted as **"price in your plan"**.
- **Places:** every activity and restaurant links to Google Maps, its official website, and ticket or table-reservation pages when available. Each day links to its full route in Google Maps.

---

## 18. User Experience and Interface

| Element | Description |
|---|---|
| **Chat panel** | Conversational planning with friendly progress messages; can be closed and reopened |
| **3D globe** | Spins with live "air traffic" while idle, then locks onto the journey and draws each leg with an animated plane |
| **Trip board** | Tabs: Itinerary (day maps, timeline, links), Flights & hotel, Budget (charts, what-if), Checks (validator results), Weather, Profile, Sources |
| **Plan cards** | The four modes with TripScore rings and budget status |
| **Expert review** | The critic's verdict and quality score, what it already improved (✓), and open ideas as one-tap buttons |
| **What guests say** | The review analyst's verdict, a bar per aspect (cleanliness, location, staff, quietness, value…), pros and cons |
| **Smart replies** | The agents' next-step ideas appear as ✨ quick replies above the chat box |
| **"Expert pick" badge** | Places the critic added are marked separately from places the traveller asked for |
| **AI view** (`?ai=1`) | A developer/demo tab that replays the agents' reasoning: thoughts, tool calls, observations, decisions |
| **Trip ideas** | Budget-and-interest form with destination cards (photo, match %, reason, prices, fit badge) |
| **Trip Book** | Scroll-animated guide with a globe cover, contents, day maps, checklists; print/PDF |
| **Bilingual** | Full Arabic (RTL, Arabic typography) and English interface; replies in the user's language |
| **Themes** | Dark and light mode (the globe switches between night lights and a daytime Earth) |
| **Transparency** | Estimates and AI-sourced data are labelled; the only technical detail shown is the remaining search quota |
| **Accessibility** | Keyboard navigation, reduced-motion support, responsive down to phone width |

---

## 19. Data Model: the Trip State

All of a trip's state lives in one structured, versioned object (Pydantic models, persisted in SQLite):

```text
Trip
├── conversation            (messages in both directions)
├── requirement draft       (what is known so far; missing fields; route proposal)
├── trip_contract           (confirmed: origin, destination(s)/stops, dates, travellers, budget, currency)
├── traveler_profile        (explicit + learned preferences)
├── research bundle         (flights, hotels, places, events, weather, FX, transfers, matrices; per stop)
├── plans{balanced|budget|comfort|experience}
│     ├── flights / legs, hotel(s), days[] → items[] (time, place, cost, travel, links)
│     ├── budget breakdown, validation report, TripScore, explanations
│     └── requested places (name → day)
├── selected_plan, feedback history, event log, versions/diffs
```

Every fact inside carries **metadata** (source, fetched-at time, confidence, price type).

---

## 20. Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3 |
| Web API | FastAPI + Uvicorn (REST + Server-Sent Events) |
| Agent orchestration | LangGraph |
| Tool protocol | Model Context Protocol (MCP) — 8 servers, in-process or stdio |
| LLM | Azure AI Foundry (OpenAI-compatible) or Anthropic Claude; structured outputs |
| Data validation | Pydantic v2 |
| Optimization | Google OR-Tools (VRPTW) |
| HTTP | httpx (async) with a persistent SQLite cache |
| Storage | SQLite (trips, events, HTTP cache) |
| Frontend | Vanilla JavaScript (ES modules), HTML, CSS |
| 3D / maps | Three.js globe; Leaflet + OpenStreetMap day maps |
| Testing | pytest with recorded real API responses (record/replay) |
| External APIs | SerpApi (Google Flights/Hotels/Maps/Travel Explore/Directions/Events), Geoapify, openrouteservice, Open-Meteo, Frankfurter, Wikivoyage |

---

## 21. Reliability, Cost and Security

### Cost control
- The main paid source (SerpApi) has a **free tier of 250 searches/month**. A new single-city trip needs about 10–14 searches, and replans need **0**.
- A **persistent cache** stores responses with per-source lifetimes (flights/hotels 6 h, places 7–14 days, reviews 30 days).
- A **per-turn quota guard** limits live searches. The remaining quota is shown in the header.
- Unsupported engines are remembered and not retried.

### Reliability
- Parallel research with timeouts.
- An AI-knowledge fallback for any failing source.
- Stale cache beats nothing when the quota is exhausted.
- A bounded repair loop.

### Security and privacy
- API keys live only in environment variables (`.env`).
- Keys are **never stored** in cache rows, **redacted** from error messages, and kept **out of logs** (the HTTP client loggers are silenced).
- No payment data is ever handled; booking happens on the providers' sites.
- Technical internals are hidden from end users.

---

## 22. Testing and Evaluation Plan

### 22.1 Automated tests (offline and deterministic)

**Record/replay:**
- Real API responses are recorded once into a fixture database.
- Tests then run **offline, deterministically, and without spending quota**.

Unit and integration tests will cover:
- understanding;
- planning;
- validators and repair;
- replanning;
- multi-city journeys;
- the fallback;
- trip ideas.

### 22.2 Scenario-based evaluation

A suite of about **26 scenarios** on real recorded data, for example:
- **Requirements:** missing budget/dates → asks only for those; vague destination → not guessed.
- **Planning:** tight budget, low walking tolerance, relaxed pace, no early flights, vegetarian.
- **Reality (fault injection):** a restaurant closes, an attraction is delisted, an impossible schedule, a hallucinated place. The system must **detect** each one and **recover**.
- **Replanning:** fewer museums, later start, budget cut, more food, extend trip, remove a named activity.

### 22.3 Metrics and targets

| Metric | Target |
|---|---|
| Scenarios passed | 100% |
| Constraint satisfaction (all checks, all modes) | ≥ 99% |
| Schedule feasibility | 100% |
| Budget accuracy | 100% |
| Tool-selection accuracy | 100% |
| Grounded recommendation rate (every place from real data) | 100% |
| Reality-violation rate | 0% |
| Injected-violation detection | 100% |
| Replanning success | 100% |
| Share of cost backed by published prices | reported (honesty metric) |
| Scheduled places with verified opening hours | reported (honesty metric) |
| Latency | new trip ≤ ~60 s live (research + planning + expert review); replan ≈ 1 s; concierge answer ≤ ~15 s |

**Agent-specific evaluation.** Agents are tested with a **scripted model**, so their *control logic* is checked deterministically on recorded real data. The model's *judgement quality* is measured separately:

| Agent | Metric | Target |
|---|---|---|
| Concierge | Grounded answers: every place, time and price in the answer appears in a tool observation | ≥ 95% |
| Concierge | Tool efficiency: average tool calls per question | ≤ 3 |
| Critic | Refinements kept (not rolled back) | reported |
| Critic | TripScore / expert-quality change after refinement | ≥ 0 on average |
| Critic | Human agreement: evaluators judge the critic's issues as real | ≥ 80% |
| Review analyst | Quote faithfulness: cited quotes found verbatim in the reviews | 100% (enforced) |
| Review analyst | Aspect accuracy vs. manual labels on a sample of hotels | ≥ 85% |
| Idea matcher | Relevance of the top 3 ideas to stated interests (human-rated) | ≥ 80% |

### 22.4 User evaluation

A small usability study with students will measure:
- planning time compared with doing it manually;
- perceived trust;
- ease of use in Arabic;
- willingness to book from the generated plan.

---

## 23. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| LLM hallucinations | LLM never supplies facts in the main path; reality validator; retrieved data only |
| API quota exhaustion | Caching, per-turn quota guard, replans without search, labelled AI fallback |
| API outages / format changes | MCP isolation per provider, fallback, recorded tests catch regressions |
| Missing data (hours, ticket prices) | Explicit estimates with labels; warnings instead of silent guesses |
| Arabic dialect understanding | LLM-based understanding (no keyword rules); replies in the user's language |
| Infeasible user constraints | Repair loop + transparent explanation + what-if alternatives |
| Cost of LLM calls | Structured, compact prompts; memoization; deterministic code where possible |
| Price changes before booking | Timestamps on all prices; live hotel offers at booking time; "prices can change" notice |

---

## 24. Known Limitations

- Entry-ticket and most restaurant prices aren't published by any free API. They are **estimated** and labelled.
- In-city public transport time is approximated from driving/walking data (no free transit API).
- Train/coach timetables and fares between cities are estimated. Travel times are real.
- Some sources (e.g. Google Events) are unavailable on free plans.
- Hotel prices in destination ideas are typical rates. The detailed plan searches real, often cheaper, hotels.

---

## 25. Work Plan

| Phase | Weeks | Deliverables |
|---|---|---|
| 1. Research & design | 1–2 | Requirements, architecture, data-source study, Trip State model |
| 2. Data layer | 3–4 | Providers, MCP servers, cache/quota, record/replay |
| 3. Understanding & orchestration | 5–6 | LLM structured understanding, LangGraph workflow, requirement dialogue |
| 4. Planning engine | 7–9 | Ranking, OR-Tools optimizer, itinerary builder, 4 modes, TripScore |
| 5. Validation & repair | 10–11 | 8 validators, repair loop, honesty labels |
| 6. Replanning & personalization | 12–13 | Feedback actions, learning, diffs, what-if |
| 7. Multi-city & route design | 14–15 | Journeys, collaborative route proposals, named-place guarantees |
| 8. Frontend & Trip Book | 16–18 | Chat, globe, trip board, Arabic/English, themes, Trip Book, booking dialogs |
| 9. Specialist agents | 19–20 | Critic (reflection + verification), concierge (ReAct), review analyst, idea matcher, AI-knowledge fallback, agent trace |
| 10. Evaluation & documentation | 21–22 | Test suite, scenario evaluation, user study, thesis and presentation |

---

## 26. Future Work

- **Booking partnerships:** affiliate APIs for in-app booking with explicit user confirmation.
- **Mobile app** with offline Trip Book and live notifications (delays, weather changes).
- **Group trips:** shared planning and voting on activities.
- **Scalable storage:** PostgreSQL + pgvector for semantic search over places and reviews.
- **Transit data** (GTFS) for accurate in-city public transport.
- **Carbon-aware planning:** prefer lower-emission legs when the difference is small.
- **More languages** beyond Arabic and English.

---

## 27. Expected Contributions

1. An **agentic architecture** that separates LLM reasoning, real-data tools (MCP) and deterministic optimization/validation, making AI travel planning **trustworthy**.
2. A **validation-and-repair** methodology with measurable grounding and honesty metrics.
3. **Verified self-reflection:** an LLM critic whose improvements pass through the same validators and scoring and are rolled back if they make the plan worse. The model's judgement is combined with guarantees from code.
4. A **ReAct concierge** grounded in live travel tools, whose answers turn into executable plan changes.
5. **Collaborative multi-country route design** in which the LLM and the traveller iterate on a proposal grounded in real geography.
6. **Budget- and interest-aware destination discovery** that combines live prices with LLM fit scoring.
7. A **bilingual (Arabic/English) travel planner** that serves an under-served audience.
8. A **reproducible evaluation** on recorded real-world data.

---

## 28. Glossary

| Term | Meaning |
|---|---|
| **LLM** | Large Language Model: an AI model that understands and generates text |
| **Agent** | An AI component that takes actions (calls tools) toward a goal |
| **MCP** | Model Context Protocol: an open standard for exposing tools and data to AI models |
| **LangGraph** | A library for building AI workflows as explicit state graphs |
| **RAG** | Retrieval-Augmented Generation: answering from retrieved documents instead of memory |
| **VRPTW** | Vehicle Routing Problem with Time Windows: finding optimal visit orders under time constraints |
| **OR-Tools** | Google's open-source optimization library |
| **Hallucination** | A confident but false statement generated by an LLM |
| **Grounding** | Tying every recommendation to verifiable data |
| **TripScore** | Dalili's 0–100 comparable plan-quality score |
| **Trip Contract** | The confirmed, structured version of the traveller's request |
| **Fallback** | An alternative used when the primary data source fails, clearly labelled |
| **Multi-agent system** | Several specialised AI agents, each with its own role, tools and output schema, coordinated by a workflow |
| **ReAct** | "Reason + Act": an agent alternates thoughts and tool calls, reading each result before deciding the next step |
| **Reflection** | An agent critiques an output (here, a plan) and the system refines it; our loop also *verifies* the refinement |
| **LLM-as-judge** | Using a language model to score quality where no simple rule exists (plan quality, destination fit) |
| **Aspect-based sentiment analysis** | Extracting opinions per aspect (cleanliness, location, staff…) from reviews |
| **Human in the loop** | The system proposes and the person approves or edits (route proposals, suggestions) |
| **Guardrails** | Rules that limit what an agent may do on its own (whitelisted, data-grounded actions only) |

---

## 29. Suggested Presentation Outline

| # | Slide | Content |
|---|---|---|
| 1 | Title | Dalili: an agentic AI travel planner. Team, supervisor |
| 2 | The problem | Fragmented planning, hours of research, hidden conflicts, untrustworthy AI answers |
| 3 | Existing solutions | Comparison table (Section 3) and the gap |
| 4 | Our idea | One-page idea (Section 1): "The AI plans, you book" |
| 5 | Objectives | Section 5 |
| 6 | User journey | Mariam's story (Section 7) with mock screens |
| 7 | Architecture | Diagram (Section 9) |
| 8 | AI approach | LLM + MCP tools + LangGraph; who does what (Section 10.1) |
| 9 | The agent team | 11 agents: pattern, input/output, tools (Section 10.5) |
| 10 | Agentic patterns | ReAct, reflection with verification, guardrails, human in the loop, bounded autonomy (Section 10.6) |
| 11 | Concierge demo | A ReAct trace step by step (Section 10.7) — live demo with the AI view |
| 12 | Critic demo | Critique → safe fixes → re-plan → verify → keep/rollback (Section 10.8) |
| 13 | Real data | Sources and honesty rules (Section 11) |
| 14 | Optimization | VRPTW per day, 4 modes, TripScore (Section 12) |
| 15 | Trust | 8 validators + repair loop + fallback (Section 13) |
| 16 | Personalization | Feedback, replanning, what-if (Section 14) |
| 17 | Multi-city | Collaborative route design (Section 15) |
| 18 | Trip ideas | Budget + interests → matched destinations (Section 16) |
| 19 | Booking handoff | Book this trip, hotel offers at the planned price (Section 17) |
| 20 | Interface | Chat, globe, board, expert review, guest insights, Trip Book, Arabic/English, dark/light (Section 18) |
| 21 | Tech stack | Section 20 |
| 22 | Evaluation plan | Metrics and targets, including per-agent metrics (Section 22) |
| 23 | Risks | Section 23 |
| 24 | Timeline | Work plan (Section 25) |
| 25 | Future work & contributions | Sections 26–27 |
| 26 | Q&A | — |
