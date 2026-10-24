"""
merge.py — de-duplication / merge stage. Runs AFTER extraction, on any components,
independent of the source file or type.

A component is one piece of knowledge; protocols restate the same objective/endpoint in
several places (synopsis + detailed section). We GROUP same-meaning components and merge
each group into one component carrying ALL their source locations — "write once, appears
in many places," first seen within one document.

Grouping is the hard part. Clinical statements are templated ("To evaluate efficacy of X
to prevent ___"), so string similarity over-merges clinically distinct items
('COVID-19' vs 'severe COVID-19' are ~0.82 similar but are DIFFERENT). So the default
grouper is the LLM, which understands that distinction. A deterministic fuzzy grouper is
kept as an offline fallback, deliberately conservative (near-verbatim only).

The grouper is injectable: `grouper(texts, kind) -> list[list[int]]` (index groups).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Callable, Optional

from .models import ComponentInstance
from .config import load_secrets

GROUP_MODEL = "claude-opus-4-8"
_ID_PREFIX = {"objective": "obj", "endpoint": "end", "arm": "arm",
              "population": "pop", "eligibility": "elig", "visit": "vis"}
_LABEL_RE = re.compile(r"^[^:]{0,70}\b(objective|endpoint|estimand|primary|secondary)\b[^:]{0,40}:\s*", re.I)

Grouper = Callable[[list[str], str], list[list[int]]]


# ---------------------------------------------------------------------------
# Grouping strategies
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    t = _LABEL_RE.sub("", text.strip()).lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def fuzzy_grouper(threshold: float = 0.93) -> Grouper:
    """Offline, deterministic. Conservative by design: string similarity cannot tell
    'COVID-19' from 'severe COVID-19', so a high threshold only catches near-verbatim
    repeats. Use for no-API runs; prefer the LLM grouper for real dedup."""
    def group(texts: list[str], kind: str) -> list[list[int]]:
        clusters: list[tuple[str, list[int]]] = []
        for i, text in enumerate(texts):
            n = _norm(text)
            for norm_rep, idxs in clusters:
                if _similar(n, norm_rep) >= threshold:
                    idxs.append(i)
                    break
            else:
                clusters.append((n, [i]))
        return [idxs for _, idxs in clusters]
    return group


def llm_grouper(model: str = GROUP_MODEL) -> Grouper:
    """Group by MEANING using the model (knows 'severe COVID-19' != 'COVID-19')."""
    def group(texts: list[str], kind: str) -> list[list[int]]:
        import anthropic

        load_secrets()
        numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(texts))
        singular = kind[:-1] if kind.endswith("s") else kind
        tool = {
            "name": "record_groups",
            "description": "Group the indices that refer to the same item.",
            "input_schema": {
                "type": "object",
                "properties": {"groups": {"type": "array", "items": {
                    "type": "array", "items": {"type": "integer"}}}},
                "required": ["groups"],
            },
        }
        system = (
            f"You are given a numbered list of clinical-trial {kind}. Group the indices that "
            f"refer to the SAME {singular} — same meaning — even if worded or labelled "
            f"differently (e.g. a synopsis line and its detailed-section twin). Items that "
            f"differ in any clinically meaningful way — a different outcome, severity "
            f"('severe COVID-19' vs 'COVID-19'), population, dose, or timepoint — are "
            f"DIFFERENT and must go in separate groups. Every index must appear exactly once "
            f"across the groups; a unique item is a group of one."
        )
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model, max_tokens=2000, system=system,
            tools=[tool], tool_choice={"type": "tool", "name": "record_groups"},
            messages=[{"role": "user", "content": numbered}],
        )
        for b in msg.content:
            if getattr(b, "type", None) == "tool_use":
                return [g for g in dict(b.input).get("groups", []) if g]
        raise ValueError("grouper did not return groups")
    return group


# ---------------------------------------------------------------------------
# Merge mechanics (grouper-agnostic)
# ---------------------------------------------------------------------------
def merge_components(components: list[ComponentInstance], grouper: Optional[Grouper] = None) -> list[ComponentInstance]:
    """Collapse same-meaning components (grouped per type) into one component each,
    keeping the fullest statement and its single canonical source. Default grouper is
    the LLM; pass fuzzy_grouper() for an offline run. IDs reassigned sequentially per type."""
    if grouper is None:
        grouper = llm_grouper()

    by_type: dict[str, list[Component]] = {}
    for c in components:
        by_type.setdefault(c.type, []).append(c)

    merged, counters = [], {}
    for t, comps in by_type.items():
        groups = grouper([c.data.text for c in comps], t) if comps else []
        # safety net: anything the grouper dropped becomes its own singleton group
        covered = {i for g in groups for i in g}
        groups = groups + [[i] for i in range(len(comps)) if i not in covered]

        for g in groups:
            members = [comps[i] for i in g]
            rep = max(members, key=lambda c: len(c.data.text))   # keep the fullest statement
            counters[t] = counters.get(t, 0) + 1
            merged.append(ComponentInstance(
                id=f"{_ID_PREFIX.get(t, t[:3])}-{counters[t]:03d}", type=t,
                study_id=rep.study_id, version=rep.version, data=rep.data,
                provenance=rep.provenance, definition_ids=rep.definition_ids,
            ))
    return merged
