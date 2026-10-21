"""The fine-tuned destination encoder at runtime: text -> unit vector, with ONNX Runtime (no PyTorch on the server).

The model is MiniLM (sentence-transformers/all-MiniLM-L6-v2) fine-tuned on the destination guides (finetune.py),
exported to ONNX and quantised to int8. A place's vector is the mean of its passages' vectors, each the
attention-masked mean of the token states - exactly as in training.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..config import PROJECT_DIR

ENCODER_DIR = PROJECT_DIR / "ml" / "models" / "encoder"
MAX_LEN = 256   # model tokens per passage (a 180-word passage fits)
BATCH = 16


def unit(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.maximum(n, 1e-9)


class Encoder:
    def __init__(self, path: Path = ENCODER_DIR):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.tok = Tokenizer.from_file(str(path / "tokenizer.json"))
        self.tok.enable_truncation(MAX_LEN)
        self.tok.enable_padding()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2  # a web request, not a training job: leave the cores to the other requests
        self.session = ort.InferenceSession(str(path / "model.onnx"), opts, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}

    def embed(self, texts: list[str]) -> np.ndarray:
        """One unit vector per text."""
        out = []
        for i in range(0, len(texts), BATCH):
            enc = self.tok.encode_batch(texts[i:i + BATCH])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
            hidden = self.session.run(None, {k: v for k, v in feed.items() if k in self.inputs})[0]
            m = mask[..., None].astype(np.float32)
            out.append(unit((hidden * m).sum(1) / np.maximum(m.sum(1), 1e-9)))
        return np.vstack(out) if out else np.zeros((0, 0), dtype=np.float32)

    def place(self, passages: list[str]) -> np.ndarray | None:
        """A place's vector from its guide's passages (None without text)."""
        return unit(self.embed(passages).mean(axis=0)) if passages else None


def available(path: Path = ENCODER_DIR) -> bool:
    return (path / "model.onnx").exists() and (path / "tokenizer.json").exists()
