# Dalili destination dataset

The data the Dalili recommendation model (Doc2Vec, written from scratch) is trained and evaluated on.
Exported 2026-09-30 03:20 UTC by `python -m travel_agent.recommender.export_dataset`.

## Size

| | |
|---|---|
| Destinations | 228 (227 used; the rest have a guide shorter than 150 tokens) |
| Validation / test split | 112 / 115 destinations |
| Training tokens | 430,333 |
| Vocabulary (words seen at least 3 times) | 14,425 |

## Files

**`destinations.csv`**: one row per destination (opens in Excel).

| Column | Meaning |
|---|---|
| `id`, `name`, `country` | The destination. |
| `tags` | Hand labels (1-4), from: beach, culture, history, nature, ski, food, nightlife, shopping, relax, adventure. Used **only for evaluation**; the model never sees them. |
| `main_tag` | The first, main label. |
| `split` | `validation` (used to choose settings) or `test` (used only for the final numbers). |
| `tokens`, `characters` | Size of the cleaned guide. |
| `wikivoyage_title`, `source_url` | Where the text comes from. |

**`guides/<id>.txt`**: the same content as `guides.jsonl`, one readable file per destination (e.g. `guides/paris.txt`). It has the cleaned guide text first, then the tokens the model trains on.

**`guides.jsonl`**: one JSON object per line.
- `text`: the cleaned guide, with only the sections Understand / See / Do / Buy / Eat / Drink.
- `tokens`: the exact word list the model trains on. It is lowercased, with stop-words and place names removed, plurals folded, and at most 6,000 words.

## `model_inputs/`: exactly what goes into the model

Reproduced from the saved model with the same seed. The first training epoch here has exactly as many pairs as the training log reports.

| File | What it is |
|---|---|
| `vocabulary.csv` | Every word the model knows (seen at least 3 times). For each: its **id**, its count, how many guides contain it, the probability it is **kept** in an epoch (frequent-word subsampling), and its probability of being drawn as a **negative** sample. Words outside this list are ignored. |
| `encoded_guides.csv` | Each guide as the model reads it: a sequence of word ids (`doc_id` is the row of the destination vector). |
| `training_pairs_epoch1.csv.gz` | The (input → target) pairs of epoch 1, in training order. `doc->word` pairs teach a place vector to predict its guide's words (PV-DBOW); `word->context` pairs teach word vectors (skip-gram). Every epoch draws a new random set like this. |
| `interest_seed_words.csv` | The words that define each interest's vector (beach → beach, sand, coral, lagoon…). |
| `destination_vectors.csv` | The **output**: the learned vector of each destination (unit length). Similar places have a high dot product. |

## Labels per interest (destinations used)

| Interest | Destinations |
|---|---|
| beach | 67 |
| culture | 115 |
| history | 88 |
| nature | 70 |
| ski | 13 |
| food | 64 |
| nightlife | 44 |
| shopping | 31 |
| relax | 35 |
| adventure | 44 |

## Source and licence

The guide text comes from [Wikivoyage](https://en.wikivoyage.org), © Wikivoyage contributors, under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Each row links to its article. If you share this dataset, keep this attribution and the same licence.

The labels, the split and the cleaning are Dalili's own work.
