"""Export the exact dataset the destination model is trained on.

    python -m travel_agent.recommender.export_dataset          # writes ml/dataset/

ml/dataset/
  destinations.csv   one row per destination: labels, split, sizes, source
  guides.jsonl       one JSON object per destination: cleaned guide text + the tokens the model trains on
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
from .train import MIN_TOKENS

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
    # The same text, one readable file per city (guides/paris.txt ...): the cleaned guide, then the training tokens.
    (OUT / "guides").mkdir(exist_ok=True)
    for d, clean, tokens in rows:
        (OUT / "guides" / f"{d.id}.txt").write_text(
            f"{d.name}, {d.country}\nLabels: {', '.join(d.tags)} | Split: {split.get(d.id, 'excluded')}\n"
            f"Source: https://en.wikivoyage.org/wiki/{quote(d.wikivoyage.replace(' ', '_'))} (CC BY-SA 4.0)\n\n"
            f"===== CLEANED GUIDE TEXT ({len(clean):,} characters) =====\n\n{clean}\n\n"
            f"===== TOKENS THE MODEL TRAINS ON ({len(tokens):,}) =====\n\n{' '.join(tokens)}\n", encoding="utf-8")
    stats = {"destinations": len(rows), "used": len(used), "validation": len(val), "test": len(test),
             "tokens": sum(len(r[2]) for r in used), "vocabulary_min3": None,
             "tag_counts": {t: sum(t in r[0].tags for r in used) for t in catalog.INTERESTS}}
    from collections import Counter

    c = Counter(w for r in used for w in r[2])
    stats["vocabulary_min3"] = sum(1 for n in c.values() if n >= 3)
    (OUT / "README.md").write_text(_readme(stats), encoding="utf-8")
    return stats


def export_model_inputs(out=None) -> dict:
    """Everything that goes *into* the trained model, reproduced exactly from the saved model and the corpus:
    the vocabulary (word -> id, with its sampling probabilities), every guide as the id sequence the model reads,
    the (input, target) pairs of the first training epoch, the interest seed words, and the learned vectors."""
    import gzip

    import numpy as np

    from .interests import seed_tokens
    from .model import Config, Doc2Vec, unit
    from .train import MODEL_PATH

    out = (out or OUT) / "model_inputs"
    out.mkdir(parents=True, exist_ok=True)
    a = np.load(MODEL_PATH, allow_pickle=False)
    saved = Doc2Vec.from_arrays(a)
    ids = a["ids"].tolist()
    dests = {d.id: d for d in catalog.load()}
    tokens = asyncio.run(corpus.build(list(dests.values())))
    docs = [tokens[i] for i in ids]

    m = Doc2Vec(Config(**{k: getattr(saved.cfg, k) for k in vars(saved.cfg)}))
    m.build_vocab(docs)
    assert m.vocab == saved.vocab, "the corpus changed since the model was trained - retrain first"
    encoded = [m.encode(d) for d in docs]
    keep, cdf = m._keep_prob(), m._neg_cdf()
    neg_p = np.diff(np.r_[0.0, cdf])
    df = a["df"] if "df" in a.files else np.zeros(len(m.vocab))

    with open(out / "vocabulary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["word_id", "word", "count", "guides_containing", "keep_probability", "negative_sample_probability"])
        for i, word in enumerate(m.vocab):
            w.writerow([i, word, int(m.counts[i]), int(df[i]), round(float(keep[i]), 5), f"{neg_p[i]:.3e}"])

    with open(out / "encoded_guides.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "destination_id", "name", "tokens_in_vocabulary", "word_ids"])
        for di, (did, enc) in enumerate(zip(ids, encoded)):
            w.writerow([di, did, dests[did].name, enc.size, " ".join(map(str, enc.tolist()))])

    # Epoch 1 exactly as fit() generated it: same seed, same random draws in the same order.
    rng = np.random.default_rng(m.cfg.seed)
    rng.random((len(docs) + len(m.vocab), m.cfg.dim))  # the weight initialisation comes first
    ins, tgt = m._epoch_pairs(encoded, rng)
    n_docs = len(docs)
    with gzip.open(out / "training_pairs_epoch1.csv.gz", "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["step_order", "pair_type", "input_id", "input", "target_word_id", "target_word"])
        for k, (i, t) in enumerate(zip(ins.tolist(), tgt.tolist())):
            if i < n_docs:
                w.writerow([k, "doc->word (PV-DBOW)", i, ids[i], t, m.vocab[t]])
            else:
                w.writerow([k, "word->context (skip-gram)", i - n_docs, m.vocab[i - n_docs], t, m.vocab[t]])

    with open(out / "interest_seed_words.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["interest", "seed_words_in_vocabulary"])
        for name in catalog.INTERESTS:
            w.writerow([name, " ".join(x for x in seed_tokens(name) if x in m.w2i)])

    X = unit(saved.D)
    with open(out / "destination_vectors.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["destination_id", "name"] + [f"d{j}" for j in range(X.shape[1])])
        for did, v in zip(ids, X):
            w.writerow([did, dests[did].name] + [f"{x:.5f}" for x in v])

    n_dbow = int((ins < n_docs).sum())
    return {"vocabulary": len(m.vocab), "docs": n_docs, "epoch1_pairs": int(ins.size), "doc_pairs": n_dbow,
            "word_pairs": int(ins.size) - n_dbow, "epochs": m.cfg.epochs, "dim": m.cfg.dim}


def _readme(s: dict) -> str:
    tags = "\n".join(f"| {t} | {n} |" for t, n in s["tag_counts"].items())
    return f"""# Dalili destination dataset

The data the Dalili recommendation model (Doc2Vec, written from scratch) is trained and evaluated on.
Exported {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `python -m travel_agent.recommender.export_dataset`.

## Size

| | |
|---|---|
| Destinations | {s['destinations']} ({s['used']} used; the rest have a guide shorter than {MIN_TOKENS} tokens) |
| Validation / test split | {s['validation']} / {s['test']} destinations |
| Training tokens | {s['tokens']:,} |
| Vocabulary (words seen at least 3 times) | {s['vocabulary_min3']:,} |

## Files

**`destinations.csv`**: one row per destination (opens in Excel).

| Column | Meaning |
|---|---|
| `id`, `name`, `country` | The destination. |
| `tags` | Hand labels (1-4), from: {", ".join(catalog.INTERESTS)}. Used **only for evaluation**; the model never sees them. |
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
{tags}

## Source and licence

The guide text comes from [Wikivoyage](https://en.wikivoyage.org), © Wikivoyage contributors, under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Each row links to its article. If you share this dataset, keep this attribution and the same licence.

The labels, the split and the cleaning are Dalili's own work.
"""


if __name__ == "__main__":
    print(json.dumps(asyncio.run(build()), indent=2))
    print(json.dumps(export_model_inputs(), indent=2))
