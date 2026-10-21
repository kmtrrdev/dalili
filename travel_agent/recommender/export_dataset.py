"""Export the exact dataset the destination model is trained on.

    python -m travel_agent.recommender.export_dataset          # writes ml/dataset/

ml/dataset/
  destinations.csv   one row per destination: labels, split, sizes, source
  guides.jsonl       one JSON object per destination: cleaned guide text + its tokens (TF-IDF baseline, "known for")
  README.md          what every field means, and the licence
"""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import datetime, timezone
from urllib.parse import quote

from ..config import PROJECT_DIR
from . import catalog, corpus, evaluate
from .finetune import MIN_TOKENS

OUT = PROJECT_DIR / "ml" / "dataset"


async def build() -> dict:
    dests = catalog.load()
    texts = await corpus.fetch_guides([d.wikivoyage for d in dests])
    banned = corpus.banned_words(dests)
    rows = []
    for d in dests:
        clean = corpus.keep_sections(texts.get(d.wikivoyage, ""))
        tokens = corpus.tokenize(clean, banned)[:corpus.MAX_TOKENS]
        rows.append((d, clean.strip(), tokens))
    used = [r for r in rows if len(r[2]) >= MIN_TOKENS]
    val, test = evaluate.split([r[0] for r in used])
    split = {used[i][0].id: "validation" for i in val} | {used[i][0].id: "test" for i in test}

    OUT.mkdir(exist_ok=True)
    with open(OUT / "destinations.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "country", "tags", "main_tag", "split", "tokens", "characters", "wikivoyage_title", "source_url"])
        for d, clean, tokens in rows:
            w.writerow([d.id, d.name, d.country, " ".join(d.tags), d.tags[0], split.get(d.id, "excluded (guide too short)"),
                        len(tokens), len(clean), d.wikivoyage,
                        f"https://en.wikivoyage.org/wiki/{quote(d.wikivoyage.replace(' ', '_'))}"])
    with open(OUT / "guides.jsonl", "w", encoding="utf-8") as f:
        for d, clean, tokens in rows:
            f.write(json.dumps({"id": d.id, "name": d.name, "country": d.country, "tags": list(d.tags),
                                "split": split.get(d.id, "excluded"), "wikivoyage_title": d.wikivoyage,
                                "text": clean, "tokens": tokens}, ensure_ascii=False) + "\n")
    # The same text, one readable file per city (guides/paris.txt ...): the cleaned guide, then its tokens.
    (OUT / "guides").mkdir(exist_ok=True)
    for d, clean, tokens in rows:
        (OUT / "guides" / f"{d.id}.txt").write_text(
            f"{d.name}, {d.country}\nLabels: {', '.join(d.tags)} | Split: {split.get(d.id, 'excluded')}\n"
            f"Source: https://en.wikivoyage.org/wiki/{quote(d.wikivoyage.replace(' ', '_'))} (CC BY-SA 4.0)\n\n"
            f"===== CLEANED GUIDE TEXT ({len(clean):,} characters) =====\n\n{clean}\n\n"
            f"===== TOKENS (TF-IDF BASELINE, KNOWN-FOR WORDS) ({len(tokens):,}) =====\n\n{' '.join(tokens)}\n", encoding="utf-8")
    stats = {"destinations": len(rows), "used": len(used), "validation": len(val), "test": len(test),
             "tokens": sum(len(r[2]) for r in used),
             "tag_counts": {t: sum(t in r[0].tags for r in used) for t in catalog.INTERESTS}}
    (OUT / "README.md").write_text(_readme(stats), encoding="utf-8")
    return stats


def export_model_inputs(out=None) -> dict:
    """Everything that goes into and comes out of the fine-tuned model: the passages it reads (names masked), the
    interest queries, and the vector it learned for every destination. The teacher's view is ml/dataset/teacher.jsonl."""
    import numpy as np

    from .finetune import MODEL_PATH, REPORT_PATH, query_text

    out = (out or OUT) / "model_inputs"
    out.mkdir(parents=True, exist_ok=True)
    a = np.load(MODEL_PATH, allow_pickle=False)
    ids = a["ids"].tolist()
    dests = {d.id: d for d in catalog.load()}
    texts = asyncio.run(corpus.fetch_guides([d.wikivoyage for d in dests.values()]))  # same batches as training
    style = json.loads(REPORT_PATH.read_text(encoding="utf-8"))["config"]["query"]

    n = 0
    with open(out / "passages.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["destination_id", "name", "passage_no", "passage"])
        for did in ids:
            d = dests[did]
            for k, p in enumerate(corpus.place_passages(texts.get(d.wikivoyage, ""), [d.name, d.wikivoyage],
                                                        list(dests.values()))):
                w.writerow([did, d.name, k, p])
                n += 1
    with open(out / "interest_queries.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["interest", "query_text"])
        for name in catalog.INTERESTS:
            w.writerow([name, query_text(name, style)])
    X = a["X"]
    with open(out / "destination_vectors.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["destination_id", "name", "known_for"] + [f"d{j}" for j in range(X.shape[1])])
        for did, kw, v in zip(ids, a["keywords"].tolist(), X):
            w.writerow([did, dests[did].name, kw] + [f"{x:.5f}" for x in v])
    return {"destinations": len(ids), "passages": n, "dim": int(X.shape[1])}

def _readme(s: dict) -> str:
    tags = "\n".join(f"| {t} | {n} |" for t, n in s["tag_counts"].items())
    return f"""# Dalili destination dataset

The data the Dalili recommendation model (MiniLM fine-tuned by distillation from gpt-5-mini) is trained and evaluated on.
Exported {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `python -m travel_agent.recommender.export_dataset`.

## Size

| | |
|---|---|
| Destinations | {s['destinations']} ({s['used']} used; the rest have a guide shorter than {MIN_TOKENS} tokens) |
| Validation / test split | {s['validation']} / {s['test']} destinations |
| Tokens (TF-IDF baseline) | {s['tokens']:,} |

## Files

**`destinations.csv`**: one row per destination (opens in Excel).

| Column | Meaning |
|---|---|
| `id`, `name`, `country` | The destination. |
| `tags` | Hand labels (1-4), from: {", ".join(catalog.INTERESTS)}. Used **only for evaluation**; neither the model nor its teacher ever sees them. |
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
{tags}

## Source and licence

The guide text comes from [Wikivoyage](https://en.wikivoyage.org), © Wikivoyage contributors, under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Each row links to its article. If you share this dataset, keep this attribution and the same licence.

The labels, the split and the cleaning are Dalili's own work.
"""


if __name__ == "__main__":
    print(json.dumps(asyncio.run(build()), indent=2))
    print(json.dumps(export_model_inputs(), indent=2))
