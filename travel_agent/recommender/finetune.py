"""Fine-tune the destination encoder, export it, evaluate it, save what the website uses.

    python -m travel_agent.recommender.finetune            # teacher labels (cached) -> fine-tune -> ONNX -> evaluate
    python -m travel_agent.recommender.finetune --tune     # first compare training settings on the validation split
    python -m travel_agent.recommender.finetune --teacher  # ask the teacher again (else ml/dataset/teacher.jsonl)

Offline only: needs ml/requirements.txt (PyTorch, Transformers, ONNX). The website runs the exported model with ONNX
Runtime (encoder.py). The steps, with charts, are in ml/recommender.ipynb.

Method - knowledge distillation into a small pretrained encoder:
1. Teacher: gpt-5-mini reads each guide and writes what kind of place it is (no names) and how central each interest
   is (0-3). The hand labels in the catalog are never shown to it - they are only used to measure.
2. Student: MiniLM (all-MiniLM-L6-v2, 22M parameters), fine-tuned so that its passage vectors carry the teacher's
   understanding. Every target is soft (places of the same kind are never pushed apart):
   - a place's passages <-> the teacher's descriptions of the places in the batch (target: the teacher's similarity
     of those places, the place itself highest);
   - place <-> place (target: the teacher's similarity);
   - each interest's words -> the places (target: the teacher's strength of that interest at each place).
3. Export to ONNX, quantised to int8 (~23 MB), and measure THAT model - the one the website runs.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from ..config import PROJECT_DIR
from . import catalog, corpus, evaluate
from .catalog import INTERESTS
from .encoder import ENCODER_DIR, Encoder, unit
from .interests import SEEDS, seed_tokens
from .model import TfIdf, distinctive_words, pca_2d

MODEL_DIR = PROJECT_DIR / "ml" / "models"
MODEL_PATH = MODEL_DIR / "recommender.npz"
REPORT_PATH = MODEL_DIR / "recommender_report.json"
TEACHER_PATH = PROJECT_DIR / "ml" / "dataset" / "teacher.jsonl"
BASE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MIN_TOKENS = 150  # a guide shorter than this is too thin to learn a place from


@dataclass
class Config:
    steps: int = 300
    lr: float = 5e-5
    batch: int = 16             # places per step (2 passages each)
    tau: float = 0.05           # temperature of the student's similarities
    passage_len: int = 128      # tokens per passage while training (inference reads 256)
    query: str = "words"        # how an interest is written: its seed words, or "a destination for <x>: <words>"
    seed: int = 7


# Compared by --tune on the validation split (earlier runs: 150 steps at 4e-5 scored below 300 at 5e-5).
GRID = [Config(steps=300, lr=5e-5), Config(steps=500, lr=5e-5)]


def query_text(interest: str, style: str) -> str:
    words = SEEDS[interest]
    return words if style == "words" else f"a destination for {interest}: " + ", ".join(words.split())


# ---------------------------------------------------------------------------------------------- data + teacher

def load() -> tuple[list[catalog.Destination], list[str], list[list[str]], list[list[str]], list[str]]:
    """(destinations kept, cleaned guides, passages, tokens, places skipped as too short)."""
    dests_all = catalog.load()
    raw = asyncio.run(corpus.fetch_guides([d.wikivoyage for d in dests_all]))
    banned = corpus.banned_words(dests_all)
    kept, texts, passages, tokens, skipped = [], [], [], [], []
    for d in dests_all:
        clean = corpus.keep_sections(raw.get(d.wikivoyage, ""))
        toks = corpus.tokenize(clean, banned)[:corpus.MAX_TOKENS]
        if len(toks) < MIN_TOKENS:
            skipped.append(d.name)
            continue
        kept.append(d)
        texts.append(clean)
        # From the raw guide, exactly as the website embeds a new city (engine.Recommender.vector).
        passages.append(corpus.place_passages(raw.get(d.wikivoyage, ""), [d.name, d.wikivoyage], dests_all))
        tokens.append(toks)
    return kept, texts, passages, tokens, skipped


Level = Literal[0, 1, 2, 3]


class Strengths(BaseModel):
    beach: Level
    culture: Level
    history: Level
    nature: Level
    ski: Level
    food: Level
    nightlife: Level
    shopping: Level
    relax: Level
    adventure: Level


class TeacherView(BaseModel):
    description: str = Field(description=(
        "Two or three sentences on what kind of destination this is and what a trip there is about - landscape, "
        "atmosphere, what travellers do. NO proper names at all (no place, country, region or landmark names)."))
    interests: Strengths = Field(description=(
        "How central each interest is to a trip there: 0 not really, 1 some, 2 a strong reason to go, "
        "3 one of the main reasons to go"))


TEACHER_SYSTEM = ("You are a travel expert. Read the travel guide excerpt and characterise the destination for a "
                  "recommender. Judge from the guide and your knowledge of the place.")


def teacher(dests, texts, refresh: bool = False) -> dict[str, dict]:
    """The teacher's view of every destination (cached in ml/dataset/teacher.jsonl)."""
    from .. import llm

    have = {} if refresh or not TEACHER_PATH.exists() else \
        {r["id"]: r for r in map(json.loads, TEACHER_PATH.read_text(encoding="utf-8").splitlines()) if r}
    todo = [(d, t) for d, t in zip(dests, texts) if d.id not in have]

    async def ask_all():
        sem = asyncio.Semaphore(8)

        async def one(d, text):
            async with sem:
                return d.id, await llm.parse(TEACHER_SYSTEM, json.dumps({"guide": text[:12000]}, ensure_ascii=False),
                                             TeacherView)
        return await asyncio.gather(*(one(d, t) for d, t in todo))

    if todo:
        if not llm.available():
            raise SystemExit("the teacher needs the Azure model (AZURE_AI_KEY / AZURE_AI_ENDPOINT in .env)")
        for did, view in asyncio.run(ask_all()):
            if view is None:
                raise SystemExit(f"the teacher failed on {did} - run again (answers so far are kept)")
            have[did] = {"id": did, **view.model_dump()}
        TEACHER_PATH.write_text("".join(json.dumps(have[d.id], ensure_ascii=False) + "\n" for d in dests
                                        if d.id in have), encoding="utf-8")
    return have


# ---------------------------------------------------------------------------------------------- the student (torch)

class Student:
    """The encoder being fine-tuned (PyTorch): the same mean pooling as encoder.Encoder."""

    def __init__(self, name: str = BASE_MODEL):
        from transformers import AutoModel, AutoTokenizer

        self.tok = AutoTokenizer.from_pretrained(name)
        self.model = AutoModel.from_pretrained(name)

    def embed(self, texts: list[str], max_len: int = 256, batch: int = 64):
        import torch
        import torch.nn.functional as F

        out = []
        for i in range(0, len(texts), batch):
            b = self.tok(texts[i:i + batch], padding=True, truncation=True, max_length=max_len, return_tensors="pt")
            h = self.model(**b).last_hidden_state
            m = b["attention_mask"].unsqueeze(-1).float()
            out.append(F.normalize((h * m).sum(1) / m.sum(1).clamp(min=1e-9), dim=-1))
        return torch.cat(out)

    def vectors(self, passages: list[list[str]], queries: list[str]) -> tuple[np.ndarray, np.ndarray]:
        import torch

        self.model.eval()
        with torch.no_grad():
            X = np.vstack([unit(self.embed(p).mean(0).numpy()) for p in passages])
            return X, self.embed(queries).numpy()


def distill(student: Student, passages, descriptions, S: np.ndarray, cfg: Config, log=print) -> list[float]:
    """Fine-tune the student on the teacher's view (see the module docstring). Returns the loss every 10 steps."""
    import torch
    import torch.nn.functional as F

    rng = random.Random(cfg.seed)
    torch.manual_seed(cfg.seed)
    m = student.model
    opt = torch.optim.AdamW(m.parameters(), lr=cfg.lr, weight_decay=0.01)
    warm = max(1, cfg.steps // 10)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warm) * max(0.0, (cfg.steps - s) / cfg.steps))
    Sn = S / np.linalg.norm(S, axis=1, keepdims=True).clip(1e-6)
    queries = [query_text(i, cfg.query) for i in INTERESTS]
    B, eye = cfg.batch, torch.eye(cfg.batch)
    losses, curve, t0 = [], [], time.time()
    for step in range(cfg.steps):
        m.train()
        ids = rng.sample(range(len(passages)), B)  # distinct places
        texts = [t for i in ids for t in (rng.sample(passages[i], 2) if len(passages[i]) > 1 else passages[i] * 2)]
        P = F.normalize(student.embed(texts, cfg.passage_len, 2 * B).view(B, 2, -1).mean(1), dim=-1)
        D = student.embed([descriptions[i] for i in ids], 96, B)
        Q = student.embed(queries, 32, len(queries))
        teach = torch.tensor(Sn[ids] @ Sn[ids].T)
        # 1. passages <-> descriptions
        target = F.softmax((teach + 2.0 * eye) / 0.25, dim=1)
        logits = P @ D.T / cfg.tau
        l1 = -(target * F.log_softmax(logits, 1)).sum(1).mean() - (target.T * F.log_softmax(logits.T, 1)).sum(1).mean()
        # 2. place <-> place
        tp = F.softmax(teach / 0.1 - 1e4 * eye, dim=1)
        l2 = -(tp * F.log_softmax(P @ P.T / cfg.tau - 1e4 * eye, 1)).sum(1).mean()
        # 3. interests -> places
        st = torch.tensor(S[ids].T)
        keep = st.max(1).values > 0
        l3 = -(F.softmax(st[keep] * 1.5, 1) * F.log_softmax((Q @ P.T)[keep] / cfg.tau, 1)).sum(1).mean()
        loss = l1 + l2 + l3
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
        opt.step()
        sched.step()
        losses.append(loss.item())
        if (step + 1) % 10 == 0:
            curve.append(round(float(np.mean(losses[-10:])), 4))
            log(f"  step {step + 1}/{cfg.steps}  loss {curve[-1]:.3f}  [{time.time() - t0:.0f}s]")
    return curve


def export_onnx(student: Student, out=ENCODER_DIR) -> None:
    """ONNX export, then int8 dynamic quantisation (4x smaller: ~23 MB)."""
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic

    class Hidden(torch.nn.Module):  # named inputs in, token states out (the encoder pools them like Student.embed)
        def __init__(self, model):
            super().__init__()
            self.model = model

        def forward(self, input_ids, attention_mask, token_type_ids):
            return self.model(input_ids=input_ids, attention_mask=attention_mask,
                              token_type_ids=token_type_ids).last_hidden_state

    out.mkdir(parents=True, exist_ok=True)
    fp32 = out / "model.fp32.onnx"
    student.model.eval()
    sample = student.tok(["a sample passage"], return_tensors="pt")
    torch.onnx.export(Hidden(student.model), (sample["input_ids"], sample["attention_mask"], sample["token_type_ids"]),
                      str(fp32), input_names=["input_ids", "attention_mask", "token_type_ids"],
                      output_names=["last_hidden_state"], opset_version=17, dynamo=False,
                      dynamic_axes={k: {0: "batch", 1: "tokens"} for k in
                                    ("input_ids", "attention_mask", "token_type_ids", "last_hidden_state")})
    # Per-channel scales keep the vectors within ~0.5% of the fp32 model (per-tensor int8 lost 3-8%).
    quantize_dynamic(str(fp32), str(out / "model.onnx"), per_channel=True, weight_type=QuantType.QInt8)
    fp32.unlink()
    student.tok.backend_tokenizer.save(str(out / "tokenizer.json"))


# ---------------------------------------------------------------------------------------------- evaluation

def known_for(tf: TfIdf, tokens: list[list[str]], X: np.ndarray, enc: Encoder, k: int = 4) -> list[list[str]]:
    """Each place's "known for" words: its 20 most distinctive guide words (TF-IDF), re-ranked by how close each word
    is in meaning to the place (the fine-tuned encoder) - so "alps, lake" beat a supermarket chain's name."""
    cands = distinctive_words(tf, tokens, k=20)
    vocab = sorted({w for c in cands for w in c})
    W = enc.embed(vocab)
    row = {w: i for i, w in enumerate(vocab)}

    def z(v: np.ndarray) -> np.ndarray:
        return (v - v.mean()) / (v.std() + 1e-9)

    out = []
    for i, c in enumerate(cands):
        meaning = np.array([W[row[w]] @ X[i] for w in c])
        weight = np.array([tf.X[i, tf.w2i[w]] for w in c])
        out.append([c[j] for j in np.argsort(-(z(meaning) + 0.5 * z(weight)))[:k]])
    return out


def scores(X: np.ndarray, Q: np.ndarray, dests, part) -> dict:
    r = evaluate.interest_scores(X, Q, dests, subset=part)
    return {"sim_p@5": evaluate.similarity_p_at_k(X, dests, queries=part), "map": r["map"], "p@10": r["p@10"]}


def objective(s: dict) -> float:
    return (s["sim_p@5"] + s["map"]) / 2


def main(tune: bool = False, refresh_teacher: bool = False) -> dict:
    import torch

    torch.set_num_threads(os.cpu_count() or 4)
    started = time.time()
    dests, texts, passages, tokens, skipped = load()
    val, test = evaluate.split(dests)
    print(f"{len(dests)} guides, {sum(map(len, passages))} passages; validation {len(val)} / test {len(test)}; "
          f"skipped {skipped}", flush=True)
    view = teacher(dests, texts, refresh_teacher)
    descriptions = [view[d.id]["description"] for d in dests]
    S = np.array([[view[d.id]["interests"][i] for i in INTERESTS] for d in dests], dtype=np.float32)

    def trained(cfg: Config) -> tuple[Student, list[float], dict]:
        student = Student()
        curve = distill(student, passages, descriptions, S, cfg)
        val_s = {}
        for style in ("words", "phrase"):  # how to write an interest is chosen on validation too
            X, Q = student.vectors(passages, [query_text(i, style) for i in INTERESTS])
            val_s[style] = scores(X, Q, dests, val)
        return student, curve, val_s

    tuning, cfg = [], Config()
    if tune:
        best = None
        for c in GRID:
            print(f"tuning {asdict(c)}", flush=True)
            student, curve, val_s = trained(c)
            style = max(val_s, key=lambda k: objective(val_s[k]))
            tuning.append({"config": asdict(replace(c, query=style)), "validation": val_s[style]})
            if best is None or objective(val_s[style]) > best[0]:
                best = (objective(val_s[style]), replace(c, query=style), student, curve, val_s[style])
        _, cfg, student, curve, val_best = best
    else:
        student, curve, val_s = trained(cfg)
        cfg = replace(cfg, query=max(val_s, key=lambda k: objective(val_s[k])))
        val_best = val_s[cfg.query]
    print(f"chosen on validation: {asdict(cfg)}", flush=True)

    # The model the website runs: ONNX int8. Its vectors are what gets saved and measured.
    export_onnx(student)
    enc = Encoder()
    queries = [query_text(i, cfg.query) for i in INTERESTS]
    X = np.vstack([enc.place(p) for p in passages])
    Q = enc.embed(queries)

    # References, measured the same way on the same test places.
    base = Student()
    Xb, Qb = base.vectors(passages, queries)
    T = unit(S + np.random.RandomState(0).rand(*S.shape) * 1e-3)
    tf = TfIdf().fit(tokens)
    Qt = np.vstack([tf.transform(seed_tokens(n)) for n in INTERESTS])
    ours = scores(X, Q, dests, test)
    report_test = {
        "similar_places_p@5": {"model": ours["sim_p@5"], "pretrained": scores(Xb, Qb, dests, test)["sim_p@5"],
                               "teacher": scores(T, np.eye(len(INTERESTS)), dests, test)["sim_p@5"],
                               "tfidf": evaluate.similarity_p_at_k(tf.X, dests, queries=test),
                               "random": evaluate.similarity_random(dests, queries=test)},
        "interests": {"model": {"map": ours["map"], "p@10": ours["p@10"]},
                      "pretrained": {k: v for k, v in scores(Xb, Qb, dests, test).items() if k != "sim_p@5"},
                      "teacher": {k: v for k, v in scores(T, np.eye(len(INTERESTS)), dests, test).items() if k != "sim_p@5"},
                      "tfidf": {k: v for k, v in evaluate.interest_scores(tf.X, Qt, dests, subset=test).items()
                                if k in ("map", "p@10")},
                      "random": {"map": evaluate.interest_scores(tf.X, Qt, dests, subset=test)["random"]}},
    }

    points, mu, comps = pca_2d(X)
    MODEL_DIR.mkdir(exist_ok=True)
    np.savez_compressed(MODEL_PATH, X=X.astype(np.float32), Q=Q.astype(np.float32),
                        keywords=np.array([" ".join(w) for w in known_for(tf, tokens, X, enc)]),
                        ids=np.array([d.id for d in dests]), names=np.array([d.name for d in dests]),
                        countries=np.array([d.country for d in dests]),
                        tags=np.array([" ".join(d.tags) for d in dests]),
                        pca_points=points.astype(np.float32), pca_mu=mu.astype(np.float32),
                        pca_comps=comps.astype(np.float32))

    def r3(x):  # 3 significant digits: a metric stays 0.738, a learning rate stays 5e-05
        return {k: r3(v) for k, v in x.items()} if isinstance(x, dict) else \
            [r3(v) for v in x] if isinstance(x, list) else float(f"{x:.3g}") if isinstance(x, float) else x

    report = r3({
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.time() - started, 1),
        "model": f"{BASE_MODEL} fine-tuned by distillation from gpt-5-mini (ONNX int8)",
        "base_model": BASE_MODEL, "config": asdict(cfg),
        "data": {"source": "Wikivoyage guides (CC BY-SA)", "destinations": len(dests), "skipped": skipped,
                 "passages": int(sum(map(len, passages))), "words": int(sum(len(t.split()) for t in texts)),
                 "validation": len(val), "test": len(test)},
        "loss_curve": curve, "test": report_test, "validation": val_best,
        "test_per_interest": evaluate.interest_scores(X, Q, dests, subset=test)["per_interest"], "tuning": tuning,
    })
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["test"], indent=2))
    return report


if __name__ == "__main__":
    main(tune="--tune" in sys.argv, refresh_teacher="--teacher" in sys.argv)
