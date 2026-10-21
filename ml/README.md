# Dalili: a destination model fine-tuned by distillation

Dalili suggests destinations each traveller is likely to enjoy ("Picked for you"), finds places like a given one and
draws a taste map. These come from a **pretrained language model (MiniLM) that we fine-tuned** so that it understands
what kind of place each destination is - a beach island, a ski resort, a food capital.

The model is an **extra feature**. It never touches prices, flights or the itinerary: every number in a plan still
comes from live data.

---

## This folder

| Path | What it is |
|---|---|
| `recommender.ipynb` | **The model as a notebook**: data → teacher → fine-tuning (loss curve) → evaluation against the model before fine-tuning, the teacher, TF-IDF and random → the served model's check → examples and the taste map. Run it top to bottom. |
| `dataset/` | The exact data: `destinations.csv` (labels, split), `guides.jsonl` and `guides/*.txt` (cleaned text), `teacher.jsonl` (what the teacher wrote), `model_inputs/` (passages, interest queries, learned vectors). See `dataset/README.md`. |
| `models/` | What the website runs: `encoder/` (the fine-tuned model, ONNX int8, 23 MB, and its tokenizer), `recommender.npz` (destination and interest vectors, "known for" words, the map) and `recommender_report.json` (settings, loss curve, every metric). |
| `requirements.txt` | Only for training and the notebook (PyTorch, Transformers, ONNX). The website needs ONNX Runtime only. |

The code is in `travel_agent/recommender/`:

| File | Role |
|---|---|
| `catalog.py` | The destinations and their hand labels |
| `corpus.py` | Download and clean the guides; passages with names masked |
| `finetune.py` | Teacher, fine-tuning, ONNX export, evaluation, saving (offline) |
| `encoder.py` | The fine-tuned model at runtime (ONNX Runtime, no PyTorch) |
| `model.py` | TF-IDF (baseline and "known for" candidates) and PCA, from scratch |
| `evaluate.py` | Split and metrics |
| `engine.py` | Personal recommendations at runtime |
| `export_dataset.py` | Writes `dataset/` |

---

## 1. The problem

| | |
|---|---|
| **Input** | What a traveller did in Dalili: trips planned, places searched, cards opened, suggestions liked or dismissed, and the interests they picked. |
| **Output** | A ranked list of destinations they haven't planned yet, each with **why it was suggested** and what the place is **known for**. |
| **Constraints** | It must work for **one user** (no crowd to learn from, so no collaborative filtering), cost nothing per request, and never invent prices. |

So it is a **content-based recommender**: learn what each *place* is like from text, then match places to a user's taste.

## 2. Data

| | |
|---|---|
| **Destinations** | 228 hand-picked destinations from 91 countries (227 used; St. Anton's guide is too short): beaches, ski resorts, historic cities, safaris, nightlife capitals and more. |
| **Text** | The **Wikivoyage** guide of each one (CC BY-SA): only the sections that describe a place (intro, Understand, See, Do, Buy, Eat, Drink), 946,241 words. |
| **Passages** | Each guide is cut into passages of about 180 words (at most 40 per guide): **5,044 passages**. Place and country names become *the place* / *the country*, so two places are alike for what they are, not for sharing a country. |
| **Labels (evaluation only)** | Every destination has 1-4 hand-labelled interests (beach, culture, history, nature, ski, food, nightlife, shopping, relax, adventure). **Neither the model nor its teacher ever sees them**; they are only used to measure. |

## 3. Method: fine-tuning by knowledge distillation

**Why not train from scratch?** Our earlier model, a Doc2Vec written from scratch in NumPy, had to learn English from
227 guides. A pretrained model already knows the language; it only has to learn *our* task.

**Why distillation?** Fine-tuning needs a signal that says what matters. We tried the plain self-supervised one (two
passages of the same guide belong together) - it made the model *worse* (it learned each place's street names, not its
character). So a large model teaches a small one:

1. **Teacher - gpt-5-mini** reads every guide and writes (`dataset/teacher.jsonl`):
   - a 2-3 sentence description of what kind of place it is, with no names;
   - how central each of the 10 interests is (0-3).
2. **Student - MiniLM** (`sentence-transformers/all-MiniLM-L6-v2`, 22M parameters, 384 dimensions), fine-tuned so that its
   passage vectors carry the teacher's understanding. Each step takes 16 places (2 passages each) and three **soft**
   objectives - soft, so that two beach islands are never pushed apart as if they were opposites:

   | Objective | Pulls together | Target distribution |
   |---|---|---|
   | passages ↔ descriptions | a place's passages and the teacher's descriptions | the teacher's similarity of the places in the batch, the place itself highest |
   | place ↔ place | the places in the batch | the teacher's similarity |
   | interest → places | each interest's words and the places | how central the teacher says that interest is at each place |

   AdamW, learning rate 5e-5 with linear warm-up and decay, temperature 0.05, 500 steps (about 30 minutes on a laptop
   CPU). The loss fell from 12.4 to 6.6.
3. **Export** to ONNX and int8 quantisation with per-channel scales: 23 MB, vectors within ~0.5% of the full model.
   The website runs it with ONNX Runtime; PyTorch is only needed to train.

A place's vector is the mean of its passages' vectors. An interest's vector is its words (*beach: beach, sand,
snorkelling, coral, lagoon…*) through the same model. A city outside the catalog is embedded on the fly from its guide.

## 4. From the model to one person's suggestions (`engine.py`)

Each signal a user gives becomes a weighted place vector, fading with a 60-day half-life:

| Signal | Weight |
|---|---|
| Planned a trip there | 1.0 |
| Liked a suggestion ("Plan a trip") | 1.0 |
| Searched it | 0.6 |
| Opened its card | 0.35 |
| Dismissed it ("Not for me") | −0.5 |
| Each interest picked | 0.8, through its interest vector |

```
taste      = Σ weight_i · vector_i
score(p)   = 0.65 · cos(taste, p)  +  0.35 · mean over picked interests of cos(interest, p)
```

- **Excluded:** places the user already planned, searched, opened or dismissed are never suggested back.
- **Match %:** the share of all destinations this one out-ranks.
- **Why:** the signal that contributed most, e.g. *"Because you planned Rome"*.
- **Known for:** the guide's 20 most distinctive words (TF-IDF), re-ranked by how close each is in meaning to the place
  (the fine-tuned model): Santorini → *caldera, volcanic, eruption*; Hurghada → *kite, coral, nile, reef*.
- **Taste map:** a 2-D PCA of all place vectors, with the user's taste projected onto it.

## 5. Evaluation

**Protocol.** The destinations are split in two halves by a hash of their id (stable): **validation (112)** chooses
the settings (training length, how an interest is written); **test (115)** is used only for the final numbers. The
numbers are for the **exported int8 ONNX model** - the one the website runs.

- **Similar places, Precision@5:** are a test destination's 5 nearest neighbours "the same kind of place" (same main
  label, or at least half the labels shared)?
- **Interests, MAP and Precision@10:** for each interest, rank the test destinations; are the labelled ones on top?

### Results on the test split

| Model | Similar places P@5 | Interests MAP | Interests P@10 |
|---|---|---|---|
| Random | 0.278 | 0.248 | - |
| TF-IDF baseline (from scratch) | 0.518 | 0.599 | 0.60 |
| MiniLM before fine-tuning | 0.546 | 0.614 | 0.64 |
| Our previous model: Doc2Vec from scratch | 0.558 | 0.631 | 0.64 |
| **MiniLM fine-tuned by distillation (ours)** | **0.624** | **0.738** | **0.77** |
| Teacher: gpt-5-mini (the ceiling) | 0.699 | 0.776 | 0.81 |

The fine-tuned model is well above its own starting point and the previous model, and reaches about 95% of the
teacher's interest ranking - at a fraction of the cost (no API call; reading a new city's guide takes about a second on a CPU).

What was tried on the way (validation split unless noted):

| Attempt | Similar P@5 | Interests MAP |
|---|---|---|
| Self-supervised fine-tuning (passages of the same guide = positives), test | 0.513 | 0.579 |
| Distillation, 150 steps (first prototype) | 0.634 | 0.694 |
| Distillation, 300 steps | 0.654 | 0.726 |
| **Distillation, 500 steps (chosen)** | 0.643 | **0.751** |

Per interest (test, average precision / Precision@10 / random):

| Interest | AP | P@10 | Random |
|---|---|---|---|
| Ski | 1.00 | 0.7 | 0.06 |
| Beach | 0.95 | 1.0 | 0.29 |
| Culture | 0.91 | 1.0 | 0.50 |
| Food | 0.76 | 0.8 | 0.28 |
| Shopping | 0.71 | 0.7 | 0.09 |
| Nature | 0.67 | 0.7 | 0.30 |
| History | 0.67 | 0.7 | 0.43 |
| Relax | 0.66 | 0.8 | 0.17 |
| Nightlife | 0.58 | 0.7 | 0.20 |
| Adventure | 0.49 | 0.6 | 0.17 |

The softer interests that the old model found hardest (food, shopping, relax, nightlife) improved the most.

Example neighbours: **Kyoto** → Tokyo, Osaka, Taipei · **Santorini** → Rhodes, Crete, Sicily, Tenerife ·
**Hallstatt** (never in training, read from its guide on the fly) → Lucerne, Interlaken, Salzburg, Zurich, Lake Bled.

## 6. Where it appears in the product

- **Home page:** *Picked for you* as soon as the model has a signal, for guests too.
- **Trip ideas:** the traveller's long-term taste is blended into the ranking of trip ideas.
- **Dashboard:** suggestions with reasons, the travel-taste bars, the taste map, and *How your suggestions work* with the live metrics and the loss curve.
- **API:** `/api/recommendations`, `/api/recommendations/similar?city=Kyoto`, `/api/recommendations/map`, `/api/recommendations/model`.

## 7. Limitations and next steps

- The catalog is fixed at 228 destinations; unseen cities can be embedded but are not suggested.
- The labels come from one annotator, and the teacher is a single model run.
- With many users, collaborative signals ("people who planned Rome also planned…") could be added on top.

## 8. Reproduce

Either open **`ml/recommender.ipynb`** and run all cells (set `TRAIN = True` to retrain), or from the project folder:

```powershell
.\.venv\Scripts\python -m pip install -r ml\requirements.txt                 # PyTorch (CPU), Transformers, ONNX
.\.venv\Scripts\python -m travel_agent.recommender.finetune --tune            # teacher (cached) -> fine-tune -> ONNX -> test
.\.venv\Scripts\python -m travel_agent.recommender.export_dataset             # rewrite ml/dataset/
.\.venv\Scripts\python -m pytest tests/test_recommender.py                    # the served model reproduces the saved vectors
```

The teacher's answers are cached in `dataset/teacher.jsonl` (add `--teacher` to ask again; it needs the Azure model
in `.env`).
