"""HotpotQA loader + haystack builder.

Real corpus only (SPEC-11 §5 forbids synthetic data). The HotpotQA distractor split
(Apache-2.0) ships JSON of the form:

    {
      "_id": "...",
      "question": "Were Scott Derrickson and Ed Wood of the same nationality?",
      "answer": "yes",
      "type": "comparison",  # or "bridge"
      "supporting_facts": [["Scott Derrickson", 0], ["Ed Wood", 0]],
      "context": [["Scott Derrickson", ["Scott Derrickson (born July 16, 1966) ..."]],
                  ...]
    }

`load_hotpotqa` reads the file you downloaded and returns typed records. The loader does
NOT download — pin the file at `HOTPOTQA_PATH` (env var) so reproducibility is in your
hands. `build_haystack` ALWAYS includes every gold supporting passage for every question
in the run (SPEC-11 §3 Invariant 1) and pads to the tier's size with filler from the
distractor contexts (also real Wikipedia text — never synthetic).
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any, cast

from benchmarks.niah.schema import Document, HaystackTier, HotpotQuestion

ENV_HOTPOTQA_PATH = "HOTPOTQA_PATH"
"""Env var pointing at hotpot_dev_distractor_v1.json (or any HotpotQA-shaped file)."""


def load_hotpotqa(*, n: int, seed: int, path: Path | None = None) -> tuple[HotpotQuestion, ...]:
    """Load the first `n` questions from a HotpotQA distractor JSON file, deterministically.

    `seed` selects which `n` of the file's questions are kept (a stable, hashed sample so
    we can rerun and get identical questions). Raises FileNotFoundError with an explicit
    fix-instruction if the dataset hasn't been downloaded yet.
    """
    resolved = path or Path(os.environ.get(ENV_HOTPOTQA_PATH, "")).expanduser()
    if not resolved or not resolved.is_file():
        raise FileNotFoundError(
            f"HotpotQA file not found. Set {ENV_HOTPOTQA_PATH} to the path of "
            "hotpot_dev_distractor_v1.json (download from https://hotpotqa.github.io/, "
            "Apache-2.0)."
        )
    payload = cast(list[dict[str, Any]], json.loads(resolved.read_text(encoding="utf-8")))
    rng = random.Random(seed)
    indices = list(range(len(payload)))
    rng.shuffle(indices)
    sampled = [payload[i] for i in indices[:n]]
    return tuple(_to_question(raw) for raw in sampled)


def _to_question(raw: dict[str, Any]) -> HotpotQuestion:
    """Adapt one HotpotQA JSON record to our typed schema."""
    supporting_titles = {fact[0] for fact in raw.get("supporting_facts", [])}
    gold_passages: list[str] = []
    for title, sentences in raw.get("context", []):
        if title in supporting_titles:
            gold_passages.append(" ".join(sentences))
    return HotpotQuestion(
        question_id=str(raw["_id"]),
        question=str(raw["question"]),
        gold_answer=str(raw["answer"]),
        gold_supporting_passages=tuple(gold_passages),
        # HotpotQA `type` is "bridge" (multi-hop chain) or "comparison" (multi-hop synthesis).
        is_multi_hop=str(raw.get("type", "")) in {"bridge", "comparison"},
    )


def build_haystack(
    *,
    tier: HaystackTier,
    questions: tuple[HotpotQuestion, ...],
    filler_path: Path | None = None,
    seed: int = 0,
) -> tuple[Document, ...]:
    """Assemble a haystack of approximately `tier.size_bytes` real Wikipedia text.

    Invariant: every gold supporting passage of every question is in the haystack. Filler
    comes from `filler_path` (a JSON list of {title, text} records — pinned Wikipedia
    slice) shuffled deterministically with `seed`. Falls back to padding from the
    HotpotQA distractor passages if no filler file is set, so the loader stays usable
    on a laptop without a separate Wikipedia dump.
    """
    docs: list[Document] = []
    seen_titles: set[str] = set()
    for q in questions:
        for idx, passage in enumerate(q.gold_supporting_passages):
            doc_id = f"gold:{q.question_id}:{idx}"
            docs.append(Document(doc_id=doc_id, title=doc_id, text=passage))
            seen_titles.add(doc_id)
    current_size = sum(d.size_bytes for d in docs)

    filler = _load_filler(path=filler_path, seed=seed)
    for raw in filler:
        if current_size >= tier.size_bytes:
            break
        title = str(raw.get("title", ""))
        if title in seen_titles:
            continue
        text = str(raw.get("text", ""))
        if not text:
            continue
        doc = Document(doc_id=f"filler:{title}", title=title, text=text)
        docs.append(doc)
        seen_titles.add(title)
        current_size += doc.size_bytes
    return tuple(docs)


def _load_filler(*, path: Path | None, seed: int) -> list[dict[str, Any]]:
    """Load a pinned Wikipedia slice for filler; shuffled deterministically by `seed`."""
    if path is None or not path.is_file():
        return []
    payload = cast(list[dict[str, Any]], json.loads(path.read_text(encoding="utf-8")))
    rng = random.Random(seed)
    rng.shuffle(payload)
    return payload
