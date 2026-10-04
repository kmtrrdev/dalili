# Dalili: A Destination Recommender Built from Scratch

Dalili suggests destinations each traveller is likely to enjoy ("Picked for you"). The suggestions come from a neural embedding model that we implemented and trained ourselves, in NumPy only.

The model is an **extra feature**. It never touches prices, flights or the itinerary: every number in a plan still comes from live data.

---

## This folder

| Path | What it is |
|---|---|
| `recommender.ipynb` | **The model as a notebook**: data → cleaning → the from-scratch Doc2Vec → training (loss curve) → evaluation against TF-IDF and random → examples and the taste map. Run it top to bottom. |
| `dataset/` | The exact data the model trains on: `destinations.csv` (228 destinations, labels, split), `guides.jsonl` and `guides/*.txt` (cleaned text + tokens), `model_inputs/` (vocabulary, encoded guides, epoch-1 training pairs, learned vectors). See `dataset/README.md`. |
| `models/` | The trained model the website uses (`recommender.npz`) and its evaluation report (`recommender_report.json`). |
| `requirements.txt` | Extra packages for running the notebook only (the model itself needs NumPy). |

The same code runs inside the app from `travel_agent/recommender/`:

| File | Role |
|---|---|
| `catalog.py` | The destinations and their hand labels |
| `corpus.py` | Download and clean the guides |
| `model.py` | Doc2Vec, TF-IDF and PCA, from scratch |
| `train.py` | Tune, train, evaluate, save |
| `evaluate.py` | Split and metrics |
| `engine.py` | Personal recommendations at runtime |
| `export_dataset.py` | Writes `dataset/` |
---

## 1. The problem

| | |
|---|---|
| **Input** | What a traveller did in Dalili: trips planned, places searched, cards opened, suggestions liked or dismissed, and the interests they picked. |
| **Output** | A ranked list of destinations they haven't planned yet. Each one comes with **why it was suggested** and what the place is **known for**. |
| **Constraints** | It must work for **one user**; we have no crowd of users to learn from, so no collaborative filtering. It must work without any paid API, and must never invent prices. |

This makes it a **content-based recommender**: we learn what each *place* is like from text, then match places to a user's taste.

## 2. Data

| | |
|---|---|
| **Destinations** | 228 hand-picked destinations (227 used; St. Anton's guide is too short), from 91 countries, covering beaches, ski resorts, historic cities, safaris, nightlife capitals and more (`travel_agent/recommender/catalog.py`). |
| **Text** | The **Wikivoyage** guide of each one (CC BY-SA), downloaded 50 pages per request and cached (`travel_agent/recommender/corpus.py`). |
| **Labels (evaluation only)** | Every destination has 1–4 hand-labelled interests (beach, culture, history, nature, ski, food, nightlife, shopping, relax, adventure). **The model never sees them in training**; they are used only to measure it. |

### Pre-processing (our own code, no NLP library)

1. **Keep the sections that describe a place:** intro, *Understand*, *See*, *Do*, *Buy*, *Eat*, *Drink*. Drop logistics that read the same everywhere (*Get in*, *Sleep*, *Connect*…).
2. **Wikitext to plain text:**
   - links become their text;
   - listing templates `{{see|name=…|content=…}}` keep their name and description;
   - other templates, references, tables and image markup are removed.
3. **Tokenise:**
   - lowercase, and fold accents to ASCII;
   - remove stop-words (English plus guide boilerplate);
   - fold simple plurals (*beaches → beach*, *galleries → gallery*).
4. **Remove every destination and country name,** so the model learns what a place *feels like*, not where it is. Otherwise Sofia and Plovdiv would be "similar" only because both say *Bulgaria*.
5. **Cap each guide at 6,000 tokens,** so big cities don't dominate.

Result: **227 guides, 430,333 tokens, a vocabulary of 14,425 words** (words seen at least 3 times).

## 3. The model: Doc2Vec (PV-DBOW) with skip-gram, trained with negative sampling

Every destination *d* gets a vector **D_d**. Every word *w* gets an input vector **W_w** and an output vector **C_w** (all 96–128 dimensions).

Training pushes up the probability of real (input, word) pairs and pushes down random "negative" pairs:

```
maximise   log σ(v · C_w)  +  Σ_{n ∈ negatives}  log σ(− v · C_n)
```

- **Document pairs (PV-DBOW):** v = D_d, and w is a word from destination d's guide. The place vector must predict its own words.
- **Word pairs (skip-gram):** v = W_w, and the target is a word within a window of w (randomly sized from 1 to 4). This learns word meanings.
- **Negatives:** drawn with probability proportional to frequency^0.75.

Place vectors and word vectors predict through the **same output vectors C**, so they live in one space:
- *Santorini* ends up near *Mykonos*;
- the word *beach* ends up near both.

That shared space gives us place-to-place similarity, interest-to-place matching and a user taste vector, all from one model.

### Training algorithm (`travel_agent/recommender/model.py`)

- **Gradients written by hand.** For a score s = v · c, the loss derivative is σ(s) − 1 for the true word and σ(s) for each negative. Those derivatives update v and c.
- **Mini-batch SGD.** 2,048 pairs per step. The learning rate decays linearly from 0.025 to 0.0001.
- **Frequent-word subsampling.** A word is kept with probability (√(f/t) + 1)·t/f, so very common words don't dominate.
- **Shared negatives.** Each batch draws 64 negatives that all its examples use, weighted k/64. In expectation this equals k private negatives, but it turns the work into dense matrix products.
- **Fast scatter-add.** Gradient rows for repeated indices are summed with a sort plus segment-sum, much faster than `np.add.at`.
- **Inference for unseen places.** For a city outside the catalog (e.g. *Hallstatt*), we download its guide, freeze **C**, and train only a new vector for it. It can then be compared with everything else.

Loss per epoch (it decreases every epoch): see `ml/models/recommender_report.json → loss_per_epoch`, also drawn in the dashboard.

## 4. From the model to one person's suggestions (`travel_agent/recommender/engine.py`)

Each signal a user gives becomes a weighted place vector. Weights fade with a 60-day half-life (a recent search matters more than an old one):

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

- **Interest vector:** the mean of the vectors of a few describing words, e.g. *beach* comes from {beach, sand, snorkelling, coral, lagoon, …}.
- **Excluded:** places the user already planned, searched, opened or dismissed are never suggested back.
- **Match %:** the share of all destinations this one out-ranks. A comparable, honest number.
- **Why:** the signal that contributed most to the score, e.g. *"Because you planned Rome"* or *"Matches your love of beaches"*.
- **Known for:** the words the place predicts much more strongly than an average place does (lift of D_d · C_w over the mean). Only words found in several guides count, e.g. Santorini → *volcanic, caldera, crater*; Borovets → *ski, piste, slope, hut*.
- **Taste profile:** cos(taste, interest vector) for every interest, rescaled to 15–100.
- **Taste map:** a 2-D PCA of all place vectors, with the user's taste projected onto it as a star.

## 5. Evaluation

### Protocol

- **Split.** The destinations are split in two halves by a hash of their id, so the split is stable and never changes:
  - **validation (112)** is used for choosing settings;
  - **test (115)** is used only for the final numbers.
- **Settings compared on validation:** epochs, dimension, window, negatives and subsampling. They trained in parallel, one process each. The best is retrained and measured once on test.

### Metrics

- **Similar places, Precision@5.** For each test destination, how many of its 5 nearest neighbours are "the same kind of place"? That means the same main label, or at least half of the labels shared.
- **Interests, MAP and Precision@10.** For each interest, rank the test destinations; are the labelled ones at the top?

### Results on the test split

**Chosen on validation:** 64 dimensions, window 3, 30 epochs (all five candidates are listed in the report). Final training took about 3 minutes; the loss fell from **3.79 to 2.00** over 30 epochs.

| Task (test destinations only) | **Our Doc2Vec** | TF-IDF baseline | Random |
|---|---|---|---|
| Similar places, Precision@5 | **0.558** | 0.520 | 0.278 |
| Interest ranking, MAP | **0.631** | 0.601 | 0.248 |
| Interest ranking, Precision@10 | **0.640** | 0.600 | - |

Per interest (test, average precision / Precision@10):

| Interest | AP | P@10 | Random |
|---|---|---|---|
| Beach | 0.90 | 0.9 | 0.29 |
| Ski | 0.86 | 0.6 | 0.06 |
| Nature | 0.83 | 0.8 | 0.30 |
| Culture | 0.80 | 0.9 | 0.50 |
| History | 0.79 | 0.9 | 0.43 |
| Shopping | 0.49 | 0.4 | 0.09 |
| Adventure | 0.46 | 0.5 | 0.17 |
| Relax | 0.42 | 0.5 | 0.17 |
| Food | 0.41 | 0.4 | 0.28 |
| Nightlife | 0.37 | 0.5 | 0.20 |

Places with a clear physical character (beaches, ski, nature, history) are learned very well. Softer interests (food, nightlife, relax) are harder: almost every guide has an *Eat* and a *Drink* section, so the text separates them less. These interests are still ranked above random.

Example neighbours:
- **Kyoto** → Tokyo, Taipei, Hokkaido.
- **Borovets** → Bansko, Whistler, Zermatt, Aspen.
- **Santorini** → Cyprus, Mykonos, Crete, Rhodes.
- **Hurghada** → Sharm El Sheikh, Dubai, Dahab.
- **Hallstatt**, which was never in training and was embedded by inference → Salzburg, Plitvice Lakes, Zurich.

Reading the numbers:
- The model is well above random on both tasks.
- It is compared honestly with a strong classical baseline (TF-IDF over the same text, also written from scratch).
- Its advantage over TF-IDF: it gives dense vectors that power user taste, inference for new places, the taste map and "known for" explanations. TF-IDF can do none of these.

## 6. Where it appears in the product

- **Home page:** *Picked for you* appears as soon as the model has a signal, for guests too.
- **Dashboard:** suggestions with reasons, the travel-taste bars, the taste map, and *How your suggestions work* with the live metrics and the loss curve.
- **API:** `/api/recommendations`, `/api/recommendations/similar?city=Kyoto`, `/api/recommendations/map`, `/api/recommendations/model`.

## 7. Limitations and next steps

- The catalog is fixed at 228 destinations. Unseen cities can be embedded (inference) but are not yet suggested.
- The labels come from one annotator.
- With many users, a **hybrid** model could add collaborative signals ("people who planned Rome also planned…") on top of these content vectors.

## 8. Reproduce

Either open **`ml/recommender.ipynb`** and run all cells, or from the project folder:

```powershell
.\.venv\Scripts\python -m travel_agent.recommender.train --tune            # fetch (cached) → tune on validation → train → test
.\.venv\Scripts\python -m travel_agent.recommender.export_dataset          # rewrite ml/dataset/
.\.venv\Scripts\python -m pytest tests/test_recommender.py                 # unit tests (learns topics, inference, API)
```

Outputs: `ml/models/recommender.npz` (vectors, vocabulary, PCA) and `ml/models/recommender_report.json` (config, loss curve, validation and test metrics, every tuning run).