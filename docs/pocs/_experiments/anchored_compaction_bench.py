"""POC: Anchored compaction template (M1 vs M2 vs M3).

Scenario: 30-turn session with seeded facts.
- Turn 1: user states a goal ("build a CSV→Parquet ETL with idempotent writes")
- Turn 2: user states constraints ("must not write to /tmp; budget < 200ms p99")
- Turn 5: a decision is made ("we'll use pyarrow over fastparquet")
- Turns 3-30: a mix of progress, tool calls, and noise
- Turn 28: a critical late constraint ("DO NOT modify the schema")
- Turn 30: a current task ("write the writer.py module")

Then we compact to a tight budget and ask: do M1/M2/M3 retain the seeded facts?

Recall is measured by substring presence (a deterministic, conservative proxy for "the LLM would still know this").

Run: uv run python docs/pocs/_experiments/anchored_compaction_bench.py
"""

from __future__ import annotations

import re
import statistics
import time
from dataclasses import dataclass
from typing import Any

CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class Turn:
    role: str
    content: str

    @property
    def chars(self) -> int:
        return len(self.content)


def make_session() -> list[Turn]:
    turns: list[Turn] = [
        Turn("user", "Goal: build a CSV→Parquet ETL pipeline with idempotent writes."),
        Turn("user", "Constraint: must not write to /tmp; p99 latency budget < 200ms."),
        Turn("assistant", "Acknowledged. I'll start by surveying available libraries."),
        Turn("tool", "search_pypi(query='parquet writer'): pyarrow, fastparquet, pyspark, dask..."),
        Turn("assistant", "Decision: we'll use pyarrow over fastparquet for stable schema enforcement."),
    ]
    # Filler turns 6..27 — repetitive and verbose
    for i in range(6, 28):
        turns.append(Turn("assistant", f"Turn {i}: incremental progress on parsing logic, intermediate code chunks, and minor edits. " * 3))
        if i % 3 == 0:
            turns.append(Turn("tool", f"bash(cmd='ls -la'): file_a, file_b, file_c, ... output {i} ..."))
    turns.append(Turn("user", "DO NOT modify the schema — we have downstream consumers depending on the v2 layout."))
    turns.append(Turn("assistant", "Understood. Schema is frozen."))
    turns.append(Turn("user", "Current task: write the writer.py module that handles the parquet output."))
    return turns


# Seeded facts we expect any honest compactor to retain
SEEDED_FACTS: list[tuple[str, str]] = [
    ("Goal", "CSV→Parquet ETL"),
    ("Constraint /tmp", "/tmp"),
    ("Constraint latency", "200ms"),
    ("Decision", "pyarrow"),
    ("Late constraint", "DO NOT modify the schema"),
    ("Current task", "writer.py"),
]


def chars(turns: list[Turn]) -> int:
    return sum(t.chars for t in turns)


# --- M1: flat truncation ---


def m1_compact(turns: list[Turn], budget_chars: int) -> str:
    blob = "\n".join(f"[{t.role}] {t.content}" for t in turns)
    if len(blob) <= budget_chars:
        return blob
    return blob[: budget_chars - 3] + "..."


# --- M2: tail preservation only ---


def m2_compact(turns: list[Turn], budget_chars: int) -> str:
    kept: list[Turn] = []
    used = 0
    for t in reversed(turns):
        cost = t.chars + 20  # role tag overhead
        if used + cost > budget_chars:
            break
        kept.append(t)
        used += cost
    kept.reverse()
    return "\n".join(f"[{t.role}] {t.content}" for t in kept)


# --- M3: anchored template + tail (deterministic extractor, no LLM) ---


GOAL_RE = re.compile(r"\b(goal|objective)\s*[:\-]?\s*(.+)", re.IGNORECASE)
CONSTRAINT_RE = re.compile(r"\b(constraint|must not|do not|cannot|never)\b[:\-]?\s*(.*)", re.IGNORECASE)
DECISION_RE = re.compile(r"\b(decision|decided|we'll use|chose)\b[:\-]?\s*(.*)", re.IGNORECASE)
NEXT_RE = re.compile(r"\b(current task|next step|now i'll|next, i'll)\b[:\-]?\s*(.*)", re.IGNORECASE)
FILE_RE = re.compile(r"([\w./_-]+\.(?:py|ts|md|json|yaml|yml|sql|sh|tf))")


def extract_anchor(turns: list[Turn], prior_anchor: str | None = None) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {
        "Goal": [],
        "Constraints": [],
        "Progress": [],
        "Decisions": [],
        "Next Steps": [],
        "Critical Context": [],
        "Relevant Files": [],
    }
    seen_files: set[str] = set()

    def add_unique(section: str, value: str) -> None:
        v = value.strip().rstrip(".")
        if v and v not in sections[section]:
            sections[section].append(v)

    if prior_anchor:
        current_section: str | None = None
        for line in prior_anchor.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                section_name = stripped[3:].strip()
                current_section = section_name if section_name in sections else None
            elif current_section and stripped.startswith("- ") and stripped != "- (none)":
                add_unique(current_section, stripped[2:])

    for t in turns:
        text = t.content
        m = GOAL_RE.search(text)
        if m and t.role == "user":
            add_unique("Goal", m.group(2).strip())
        for m in CONSTRAINT_RE.finditer(text):
            add_unique("Constraints", m.group(0).strip())
        for m in DECISION_RE.finditer(text):
            add_unique("Decisions", m.group(0).strip())
        for m in NEXT_RE.finditer(text):
            add_unique("Next Steps", m.group(0).strip())
        for fm in FILE_RE.finditer(text):
            f = fm.group(1)
            if f not in seen_files:
                seen_files.add(f)
                sections["Relevant Files"].append(f)

    return sections


def render_anchor(sections: dict[str, list[str]]) -> str:
    parts: list[str] = []
    for sec, items in sections.items():
        parts.append(f"## {sec}")
        if items:
            for it in items[:10]:
                parts.append(f"- {it}")
        else:
            parts.append("- (none)")
    return "\n".join(parts)


def m3_compact(turns: list[Turn], budget_chars: int, *, tail_fraction: float = 0.25, prior_anchor: str | None = None) -> str:
    tail_budget = int(budget_chars * tail_fraction)
    tail_str = m2_compact(turns, tail_budget)
    anchor_budget = budget_chars - len(tail_str) - 50
    anchor_sections = extract_anchor(turns, prior_anchor=prior_anchor)
    anchor_md = render_anchor(anchor_sections)
    if len(anchor_md) > anchor_budget:
        anchor_md = anchor_md[: anchor_budget - 3] + "..."
    return f"# Anchored Summary\n{anchor_md}\n\n# Recent Turns (verbatim)\n{tail_str}"


# --- Recall scoring ---


def recall(compacted: str) -> dict[str, bool]:
    return {label: needle.lower() in compacted.lower() for label, needle in SEEDED_FACTS}


def main() -> None:
    turns = make_session()
    total_chars = chars(turns)
    budget_chars = total_chars // 4  # quarter-budget — forces compaction

    print(f"Session: {len(turns)} turns, {total_chars} chars")
    print(f"Budget: {budget_chars} chars (~{budget_chars // CHARS_PER_TOKEN} tokens)\n")

    def time_compact(fn):
        durs = []
        out = ""
        for _ in range(50):
            t0 = time.perf_counter()
            out = fn()
            durs.append((time.perf_counter() - t0) * 1000)
        return out, statistics.median(sorted(durs))

    m1_out, m1_p50 = time_compact(lambda: m1_compact(turns, budget_chars))
    m2_out, m2_p50 = time_compact(lambda: m2_compact(turns, budget_chars))
    m3_out, m3_p50 = time_compact(lambda: m3_compact(turns, budget_chars))

    # Turn-over-turn anchoring: simulate compacting twice
    first_half = turns[:15]
    second_half = turns[15:]
    first_anchor = render_anchor(extract_anchor(first_half))
    m3_anchored_out = m3_compact(second_half, budget_chars, prior_anchor=first_anchor)

    rows: list[dict[str, Any]] = []
    for label, out, p50 in [("M1 (flat truncate)", m1_out, m1_p50), ("M2 (tail only)", m2_out, m2_p50), ("M3 (anchored+tail)", m3_out, m3_p50)]:
        r = recall(out)
        rows.append(
            {
                "label": label,
                "out_chars": len(out),
                "fits_budget": len(out) <= budget_chars + 100,
                "recall_pct": round(sum(r.values()) / len(r) * 100, 1),
                "missing": [k for k, v in r.items() if not v],
                "p50_ms": round(p50, 3),
            }
        )

    # Anchored multi-pass evaluation: does prior_anchor preserve early facts?
    # Compact only second half WITHOUT prior anchor — must lose turn-1 goal
    m3_no_anchor = m3_compact(second_half, budget_chars, prior_anchor=None)
    rows.append(
        {
            "label": "M3 (2nd half, no prior anchor)",
            "out_chars": len(m3_no_anchor),
            "fits_budget": len(m3_no_anchor) <= budget_chars + 100,
            "recall_pct": round(sum(recall(m3_no_anchor).values()) / len(SEEDED_FACTS) * 100, 1),
            "missing": [k for k, v in recall(m3_no_anchor).items() if not v],
            "p50_ms": "n/a",
        }
    )
    rows.append(
        {
            "label": "M3 (2nd half + prior anchor)",
            "out_chars": len(m3_anchored_out),
            "fits_budget": len(m3_anchored_out) <= budget_chars + 100,
            "recall_pct": round(sum(recall(m3_anchored_out).values()) / len(SEEDED_FACTS) * 100, 1),
            "missing": [k for k, v in recall(m3_anchored_out).items() if not v],
            "p50_ms": "n/a",
        }
    )

    headers = list(rows[0].keys())
    print(" | ".join(headers))
    print("-" * 130)
    for r in rows:
        print(" | ".join(str(r[h]) for h in headers))


if __name__ == "__main__":
    main()
