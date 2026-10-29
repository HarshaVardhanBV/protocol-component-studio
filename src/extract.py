"""
extract.py — protocol PDF -> validated ComponentInstances (objectives + endpoints)
with single-source provenance, tied to a study.

This is the ONBOARDING step: it seeds the component store from an existing document
(we don't have the sponsor's upstream source for public data). It produces INSTANCES
(content hydrated for one study). Definition induction (grouping instances across
studies into content-less Definitions) is a later, separate stage.

Uses Anthropic TOOL MODE (forced structured output) so the model returns a dict we
read directly — no text/JSON parsing. `fitz`/`anthropic` import lazily; the page
loader and tool call are injectable for offline tests.

CLI:
    python -m src.extract "<protocol.pdf>" --protocol-id moderna_cove --out out.json
"""
from __future__ import annotations

from typing import Callable, Optional

from .models import ComponentInstance, ExtractionResult, component_text
from .config import load_secrets

EXTRACT_MODEL = "claude-opus-4-8"
MAX_CHARS = 45_000
MAX_TOKENS = 8192


# ---- 1. PDF -> pages -------------------------------------------------------
def load_pages(pdf_path: str) -> list[tuple[int, str]]:
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    try:
        return [(i + 1, page.get_text()) for i, page in enumerate(doc)]
    finally:
        doc.close()


# ---- 2. Keep only relevant pages, tagged with page markers -----------------
def find_relevant_text(pages: list[tuple[int, str]], keywords: list[str],
                       max_chars: int = MAX_CHARS) -> str:
    """Pick pages that mention any keyword, favouring keyword DENSITY over raw
    page order. A long document's front matter (amendment history, synopsis,
    TOC) often mentions these terms in passing; if we fill max_chars in page
    order, that incidental front-matter can exhaust the budget before the
    actual target section (e.g. a numbered Inclusion/Exclusion Criteria list
    deep in the document) is ever seen. Scoring by hit count surfaces the
    dense, on-topic pages first regardless of where they fall in the doc."""
    kw = [k.lower() for k in keywords]

    def score(t: str) -> int:
        tl = t.lower()
        return sum(tl.count(k) for k in kw)

    scored = [(n, t, score(t)) for (n, t) in pages]
    picked = [(n, t) for (n, t, s) in scored if s > 0]
    if not picked:
        picked = pages[:10]
    else:
        picked.sort(key=lambda nt: -score(nt[1]))

    out, total, selected = [], 0, []
    for n, t in picked:
        block = f"\n\n===== PAGE {n} =====\n{t}"
        if total + len(block) > max_chars:
            continue
        selected.append((n, block))
        total += len(block)
    for n, block in sorted(selected, key=lambda nb: nb[0]):
        out.append(block)
        total += len(block)
    return "".join(out)


# ---- 3. Tool schemas (force structured output) -----------------------------
_PROV_PROPS = {
    "page": {"type": "integer", "description": "PAGE number (from the markers) where this appears"},
    "section": {"type": "string", "description": "nearest heading, e.g. '3.1 Primary Objective'"},
    "quote": {"type": "string", "description": "exact source sentence, under 200 characters"},
}
OBJECTIVES_TOOL = {
    "name": "record_objectives",
    "description": "Record every study objective found in the protocol text.",
    "input_schema": {"type": "object", "properties": {"objectives": {"type": "array", "items": {
        "type": "object", "properties": {
            "role": {"type": "string", "enum": ["primary", "secondary", "exploratory"],
                     "description": "the objective's level/importance (ICH M11 §3)"},
            "text": {"type": "string", "description": "the objective, verbatim or lightly cleaned"},
            **_PROV_PROPS},
        "required": ["role", "text", "page"]}}}, "required": ["objectives"]},
}
ENDPOINTS_TOOL = {
    "name": "record_endpoints",
    "description": "Record every study endpoint (outcome measure) found in the protocol text.",
    "input_schema": {"type": "object", "properties": {"endpoints": {"type": "array", "items": {
        "type": "object", "properties": {
            "role": {"type": "string", "enum": ["primary", "secondary", "exploratory"],
                     "description": "importance/level of the endpoint (ICH M11 §3) — NOT its purpose"},
            "purpose": {"type": ["string", "null"],
                        "enum": ["efficacy", "safety", "immunogenicity", "pharmacokinetic",
                                 "pharmacodynamic", "other", None],
                        "description": "what the endpoint measures; orthogonal to role (safety endpoints still have a role)"},
            "text": {"type": "string", "description": "the endpoint, verbatim or lightly cleaned"},
            "timeframe": {"type": ["string", "null"], "description": "assessment timeframe if stated, else null"},
            **_PROV_PROPS},
        "required": ["role", "text", "page"]}}}, "required": ["endpoints"]},
}
ARMS_TOOL = {
    "name": "record_arms",
    "description": "Record every study arm (treatment group) found in the protocol text.",
    "input_schema": {"type": "object", "properties": {"arms": {"type": "array", "items": {
        "type": "object", "properties": {
            "name": {"type": "string", "description": "arm name, e.g. 'mRNA-1273' or 'Placebo'"},
            "type": {"type": "string", "enum": ["experimental", "active_comparator", "placebo_comparator",
                                                "sham_comparator", "no_intervention", "other"],
                     "description": "CDISC Study Arm Type (C174222)"},
            "intervention": {"type": ["string", "null"], "description": "the intervention/treatment, if stated"},
            "description": {"type": ["string", "null"]},
            **_PROV_PROPS},
        "required": ["name", "type", "page"]}}}, "required": ["arms"]},
}
POPULATION_TOOL = {
    "name": "record_population",
    "description": "Record the study population(s) described in the protocol.",
    "input_schema": {"type": "object", "properties": {"population": {"type": "array", "items": {
        "type": "object", "properties": {
            "description": {"type": "string", "description": "the target population description"},
            "condition": {"type": ["string", "null"], "description": "disease/indication if stated"},
            "planned_enrollment": {"type": ["integer", "null"], "description": "planned N if stated"},
            **_PROV_PROPS},
        "required": ["description", "page"]}}}, "required": ["population"]},
}
ELIGIBILITY_TOOL = {
    "name": "record_eligibility",
    "description": "Record every inclusion and exclusion criterion found in the protocol text.",
    "input_schema": {"type": "object", "properties": {"eligibility": {"type": "array", "items": {
        "type": "object", "properties": {
            "text": {"type": "string", "description": "the criterion, verbatim or lightly cleaned"},
            "kind": {"type": "string", "enum": ["inclusion", "exclusion"]},
            "number": {"type": ["string", "null"], "description": "criterion number/label if present"},
            **_PROV_PROPS},
        "required": ["text", "kind", "page"]}}}, "required": ["eligibility"]},
}
VISITS_TOOL = {
    "name": "record_visits",
    "description": "Record every scheduled visit/encounter in the Schedule of Activities.",
    "input_schema": {"type": "object", "properties": {"visits": {"type": "array", "items": {
        "type": "object", "properties": {
            "name": {"type": "string", "description": "visit/encounter name, e.g. 'Screening', 'Day 1'"},
            "study_day": {"type": ["string", "null"], "description": "timing / study day / window if stated"},
            "procedures": {"type": "array", "items": {"type": "string"},
                           "description": "activities/procedures at this visit"},
            **_PROV_PROPS},
        "required": ["name", "page"]}}}, "required": ["visits"]},
}
OBJ_SYSTEM = ("You extract STUDY OBJECTIVES from a clinical trial protocol. Call record_objectives "
              "with every objective actually present in the text — do not invent any. Ground each in "
              "its page and a short exact quote. If none are present, pass an empty list.")
ARM_SYSTEM = ("You extract STUDY ARMS (treatment groups) from a clinical trial protocol. Classify each "
              "with its CDISC arm type. Do not invent any. Ground each in its page and a short exact quote.")
POP_SYSTEM = ("You extract the STUDY POPULATION from a clinical trial protocol (the target population, "
              "condition, and planned enrollment). Ground each in its page and a short exact quote.")
ELIG_SYSTEM = ("You extract ELIGIBILITY CRITERIA from a clinical trial protocol — every inclusion and "
               "exclusion criterion, labelled as such. Do not invent any. Ground each in its page and quote.")
VIS_SYSTEM = ("You extract the SCHEDULE OF ACTIVITIES (visits/encounters and their procedures) from a "
              "clinical trial protocol. Do not invent any. Ground each in its page and a short exact quote.")
END_SYSTEM = ("You extract STUDY ENDPOINTS (outcome measures) from a clinical trial protocol. Call "
              "record_endpoints with every endpoint actually present — do not invent any, and do NOT "
              "include objectives. For each, give BOTH its `role` (primary/secondary/exploratory — its "
              "importance) AND its `purpose` (efficacy/safety/immunogenicity/… — what it measures); these "
              "are independent, so a safety endpoint still has a role. Ground each in its page and a short "
              "exact quote. If none, pass an empty list.")


# ---- 4. Forced tool call (lazy anthropic import) -> dict --------------------
def call_tool(system: str, user: str, tool: dict, model: str = EXTRACT_MODEL) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model, max_tokens=MAX_TOKENS, system=system,
        tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": user}],
    )
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input)
    raise ValueError(f"Model did not call {tool['name']} (stop_reason={msg.stop_reason}).")


# ---- 5. Tool-input dict -> validated ComponentInstances --------------------
def _page_int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_objectives(data: dict, study_id: str) -> list[ComponentInstance]:
    items = data.get("objectives", []) if isinstance(data, dict) else (data or [])
    out = []
    for i, it in enumerate(items, 1):
        out.append(ComponentInstance(
            id=f"obj-{i:03d}", type="objective", study_id=study_id,
            data={"role": it.get("role", it.get("level", "secondary")), "text": it["text"]},
            provenance={"protocol_id": study_id, "page": _page_int(it.get("page")),
                        "section": it.get("section"), "quote": it.get("quote")},
        ))
    return out


def parse_endpoints(data: dict, study_id: str) -> list[ComponentInstance]:
    items = data.get("endpoints", []) if isinstance(data, dict) else (data or [])
    out = []
    for i, it in enumerate(items, 1):
        out.append(ComponentInstance(
            id=f"end-{i:03d}", type="endpoint", study_id=study_id,
            data={"role": it.get("role"), "purpose": it.get("purpose"),
                  "text": it["text"], "timeframe": it.get("timeframe")},
            provenance={"protocol_id": study_id, "page": _page_int(it.get("page")),
                        "section": it.get("section"), "quote": it.get("quote")},
        ))
    return out


def _prov(it, study_id):
    return {"protocol_id": study_id, "page": _page_int(it.get("page")),
            "section": it.get("section"), "quote": it.get("quote")}


def parse_arms(data: dict, study_id: str) -> list[ComponentInstance]:
    items = data.get("arms", []) if isinstance(data, dict) else (data or [])
    return [ComponentInstance(id=f"arm-{i:03d}", type="arm", study_id=study_id,
            data={"name": it["name"], "type": it.get("type", "other"),
                  "intervention": it.get("intervention"), "description": it.get("description")},
            provenance=_prov(it, study_id)) for i, it in enumerate(items, 1)]


def parse_population(data: dict, study_id: str) -> list[ComponentInstance]:
    items = data.get("population", []) if isinstance(data, dict) else (data or [])
    return [ComponentInstance(id=f"pop-{i:03d}", type="population", study_id=study_id,
            data={"description": it["description"], "condition": it.get("condition"),
                  "planned_enrollment": it.get("planned_enrollment")},
            provenance=_prov(it, study_id)) for i, it in enumerate(items, 1)]


def parse_eligibility(data: dict, study_id: str) -> list[ComponentInstance]:
    items = data.get("eligibility", []) if isinstance(data, dict) else (data or [])
    return [ComponentInstance(id=f"elig-{i:03d}", type="eligibility", study_id=study_id,
            data={"text": it["text"], "kind": it.get("kind", "inclusion"), "number": it.get("number")},
            provenance=_prov(it, study_id)) for i, it in enumerate(items, 1)]


def parse_visits(data: dict, study_id: str) -> list[ComponentInstance]:
    items = data.get("visits", []) if isinstance(data, dict) else (data or [])
    return [ComponentInstance(id=f"vis-{i:03d}", type="visit", study_id=study_id,
            data={"name": it["name"], "study_day": it.get("study_day"),
                  "procedures": it.get("procedures", [])},
            provenance=_prov(it, study_id)) for i, it in enumerate(items, 1)]


# ---- 6. Orchestrator -------------------------------------------------------
def extract(study_id: str,
            pdf_path: Optional[str] = None,
            pages: Optional[list[tuple[int, str]]] = None,
            model: str = EXTRACT_MODEL,
            tool_llm: Callable[[str, str, dict, str], dict] = call_tool) -> ExtractionResult:
    """Onboard one protocol into ComponentInstances. Pass `pdf_path` or `pages`;
    `tool_llm` is injectable for offline tests."""
    load_secrets()
    if pages is None:
        if pdf_path is None:
            raise ValueError("provide either pdf_path or pages")
        pages = load_pages(pdf_path)

    jobs = [
        (OBJ_SYSTEM, ["objective", "estimand"], OBJECTIVES_TOOL, parse_objectives),
        (END_SYSTEM, ["endpoint", "outcome measure", "estimand"], ENDPOINTS_TOOL, parse_endpoints),
        (ARM_SYSTEM, ["arm", "treatment group", "randomi", "intervention group"], ARMS_TOOL, parse_arms),
        (POP_SYSTEM, ["population", "number of participants", "sample size", "enrol"], POPULATION_TOOL, parse_population),
        (ELIG_SYSTEM, ["inclusion criteria", "exclusion criteria", "eligibility"], ELIGIBILITY_TOOL, parse_eligibility),
        (VIS_SYSTEM, ["schedule of activities", "schedule of assessments", "visit", "study day"], VISITS_TOOL, parse_visits),
    ]
    instances = []
    for system, keywords, tool, parser in jobs:
        text = find_relevant_text(pages, keywords)
        instances.extend(parser(tool_llm(system, text, tool, model), study_id))
    return ExtractionResult(study_id=study_id, instances=instances)


# ---- CLI -------------------------------------------------------------------
def _main() -> None:
    import argparse
    from .merge import merge_components, fuzzy_grouper

    ap = argparse.ArgumentParser(description="Onboard a protocol PDF into ComponentInstances.")
    ap.add_argument("pdf_path", help="path to the protocol PDF")
    ap.add_argument("--protocol-id", dest="study_id", required=True, help="study/asset id, e.g. moderna_cove")
    ap.add_argument("--out", help="optional path to write the ExtractionResult JSON")
    ap.add_argument("--model", default=EXTRACT_MODEL)
    ap.add_argument("--no-merge", action="store_true", help="skip the dedup/merge stage")
    ap.add_argument("--local-merge", action="store_true",
                    help="use the offline fuzzy grouper instead of the LLM grouper")
    args = ap.parse_args()

    result = extract(args.study_id, pdf_path=args.pdf_path, model=args.model)
    raw_n = len(result.instances)
    if not args.no_merge:
        grouper = fuzzy_grouper() if args.local_merge else None
        result = ExtractionResult(study_id=result.study_id,
                                  instances=merge_components(result.instances, grouper=grouper))

    if args.no_merge:
        print(f"\n{args.study_id}: {raw_n} instances (merge skipped)")
    else:
        print(f"\n{args.study_id}: {raw_n} extracted -> {len(result.instances)} after merge")
    for c in result.instances:
        print(f"  [{c.id}] {c.type:11} (p.{c.provenance.page}) {component_text(c.data)[:84]}")

    if args.out:
        with open(args.out, "w") as f:
            f.write(result.model_dump_json(indent=2))
        print(f"\nSaved -> {args.out}")


if __name__ == "__main__":
    _main()
