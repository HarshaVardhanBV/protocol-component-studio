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

from .models import ComponentInstance, ExtractionResult
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
    kw = [k.lower() for k in keywords]
    picked = [(n, t) for (n, t) in pages if any(k in t.lower() for k in kw)]
    if not picked:
        picked = pages[:10]
    out, total = [], 0
    for n, t in picked:
        block = f"\n\n===== PAGE {n} =====\n{t}"
        if total + len(block) > max_chars:
            break
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
            "level": {"type": "string", "enum": ["primary", "secondary", "exploratory"]},
            "text": {"type": "string", "description": "the objective, verbatim or lightly cleaned"},
            **_PROV_PROPS},
        "required": ["level", "text", "page"]}}}, "required": ["objectives"]},
}
ENDPOINTS_TOOL = {
    "name": "record_endpoints",
    "description": "Record every study endpoint (outcome measure) found in the protocol text.",
    "input_schema": {"type": "object", "properties": {"endpoints": {"type": "array", "items": {
        "type": "object", "properties": {
            "level": {"type": "string", "enum": ["primary", "secondary", "exploratory", "safety"]},
            "text": {"type": "string", "description": "the endpoint, verbatim or lightly cleaned"},
            "timeframe": {"type": ["string", "null"], "description": "assessment timeframe if stated, else null"},
            **_PROV_PROPS},
        "required": ["level", "text", "page"]}}}, "required": ["endpoints"]},
}
OBJ_SYSTEM = ("You extract STUDY OBJECTIVES from a clinical trial protocol. Call record_objectives "
              "with every objective actually present in the text — do not invent any. Ground each in "
              "its page and a short exact quote. If none are present, pass an empty list.")
END_SYSTEM = ("You extract STUDY ENDPOINTS (outcome measures) from a clinical trial protocol. Call "
              "record_endpoints with every endpoint actually present — do not invent any, and do NOT "
              "include objectives. Ground each in its page and a short exact quote. If none, pass an empty list.")


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
            data={"level": it.get("level", "secondary"), "text": it["text"]},
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
            data={"level": it.get("level", "secondary"), "text": it["text"],
                  "timeframe": it.get("timeframe")},
            provenance={"protocol_id": study_id, "page": _page_int(it.get("page")),
                        "section": it.get("section"), "quote": it.get("quote")},
        ))
    return out


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

    obj_text = find_relevant_text(pages, ["objective", "estimand"])
    end_text = find_relevant_text(pages, ["endpoint", "outcome measure", "estimand"])

    objectives = parse_objectives(tool_llm(OBJ_SYSTEM, obj_text, OBJECTIVES_TOOL, model), study_id)
    endpoints = parse_endpoints(tool_llm(END_SYSTEM, end_text, ENDPOINTS_TOOL, model), study_id)
    return ExtractionResult(study_id=study_id, instances=objectives + endpoints)


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
        print(f"  [{c.id}] {c.type:9} (p.{c.provenance.page}) {c.data.text[:88]}")

    if args.out:
        with open(args.out, "w") as f:
            f.write(result.model_dump_json(indent=2))
        print(f"\nSaved -> {args.out}")


if __name__ == "__main__":
    _main()
