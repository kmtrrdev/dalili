# Dalili destination dataset

The data the Dalili recommendation model (MiniLM fine-tuned by distillation from gpt-5-mini) is trained and evaluated on.
Exported 2026-10-21 22:42 UTC by `python -m travel_agent.recommender.export_dataset`.

## Size

| | |
|---|---|
| Destinations | 228 (227 used; the rest have a guide shorter than 150 tokens) |
| Validation / test split | 112 / 115 destinations |
| Tokens (TF-IDF baseline) | 429,970 |

## Files

**`destinations.csv`**: one row per destination (opens in Excel).

| Column | Meaning |
|---|---|
| `id`, `name`, `country` | The destination. |
| `tags` | Hand labels (1-4), from: beach, culture, history, nature, ski, food, nightlife, shopping, relax, adventure. Used **only for evaluation**; neither the model nor its teacher ever sees them. |
| `main_tag` | The first, main label. |
| `split` | `validation` (used to choose settings) or `test` (used only for the final numbers). |
| `tokens`, `characters` | Size of the cleaned guide. |
| `wikivoyage_title`, `source_url` | Where the text comes from. |

**`guides/<id>.txt`**: the same content as `guides.jsonl`, one readable file per destination (e.g. `guides/paris.txt`): the cleaned guide text, then its tokens.

**`guides.jsonl`**: one JSON object per line.
- `text`: the cleaned guide, with only the sections Understand / See / Do / Buy / Eat / Drink.
- `tokens`: lowercased words, with stop-words and place names removed, plurals folded, at most 6,000. Used by the
  TF-IDF baseline and for each place's "known for" words.

**`teacher.jsonl`**: what the teacher (gpt-5-mini) wrote about each destination after reading its guide: a short
description without names, and how central each interest is (0-3). This is what the student model is fine-tuned on.
The hand labels above are never shown to the teacher.

## `model_inputs/`: what goes into the model and what comes out

| File | What it is |
|---|---|
| `passages.csv` | Every passage the model reads (about 180 words each, place and country names masked). A place's vector is the mean of its passages' vectors. |
| `interest_queries.csv` | The text each interest is encoded from. |
| `destination_vectors.csv` | The **output**: each destination's vector (unit length) and its "known for" words. Similar places have a high dot product. |
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
