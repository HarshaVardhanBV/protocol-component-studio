"""
extract.py — protocol PDF -> validated Components (objectives + endpoints) with provenance.

Uses Anthropic TOOL MODE for extraction: the model is given a tool with a strict JSON
input schema and is *forced* to call it (tool_choice). We read the tool call's `input`
as a dict directly — no parsing of free text, so the "model wrapped JSON in prose /
fences / truncated it into invalid JSON" failure class is gone.

Pipeline: load_pages -> find_relevant_text -> call_tool (forced) -> parse_* -> extract()
`fitz`/`anthropic` are imported lazily, and the page loader + tool call are injectable,
so the logic stays unit-testable with no PDF or API key.

CLI:
    python -m src.extract "<protocol.pdf>" --protocol-id pfizer_c4591001 --out out.json
"""
from __future__ import annotations

from typing import Callable, Optional

from .models import Component, ExtractionResult
from .config import load_secrets

EXTRACT_MODEL = "claude-opus-4-8"
MAX_CHARS = 45_000          # cap on protocol text sent per element call
MAX_TOKENS = 8192           # cap on model output (tool input)


# ---------------------------------------------------------------------------
# 1. PDF -> pages (lazy fitz import)
# ---------------------------------------------------------------------------
def load_pages(pdf_path: str) -> list[tuple[int, str]]:
    """Return [(page_number, text), ...] with 1-based page numbers (for provenance)."""
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    try:
        return [(i + 1, page.get_text()) for i, page in enumerate(doc)]
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# 2. Keep only the pages that matter, tagged with page markers
# ---------------------------------------------------------------------------
def find_relevant_text(pages: list[tuple[int, str]], keywords: list[str],
                       max_chars: int = MAX_CHARS) -> str:
    """Concatenate pages whose text mentions any keyword, each prefixed with a
    '===== PAGE n =====' marker so the model can cite the page. Falls back to the
    first 10 pages (the synopsis) if nothing matches."""
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


# ---------------------------------------------------------------------------
# 3. Tool schemas — force structured output
# ---------------------------------------------------------------------------
_PROV_PROPS = {
    "page": {"type": "integer", "description": "PAGE number (from the '===== PAGE n =====' markers) where this appears"},
    "section": {"type": "string", "description": "nearest heading, e.g. '3.1 Primary Objective'"},
    "quote": {"type": "string", "description": "exact source sentence it was taken from, under 200 characters"},
}

OBJECTIVES_TOOL = {
    "name": "record_objectives",
    "description": "Record every study objective found in the protocol text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "objectives": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "string", "enum": ["primary", "secondary", "exploratory"]},
                        "text": {"type": "string", "description": "the objective, verbatim or lightly cleaned"},
                        **_PROV_PROPS,
                    },
                    "required": ["level", "text", "page"],
                },
            }
        },
        "required": ["objectives"],
    },
}

ENDPOINTS_TOOL = {
    "name": "record_endpoints",
    "description": "Record every study endpoint (outcome measure) found in the protocol text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "endpoints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "string", "enum": ["primary", "secondary", "exploratory", "safety"]},
                        "text": {"type": "string", "description": "the endpoint, verbatim or lightly cleaned"},
                        "timeframe": {"type": ["string", "null"], "description": "assessment timeframe if stated, else null"},
                        **_PROV_PROPS,
                    },
                    "required": ["level", "text", "page"],
                },
            }
        },
        "required": ["endpoints"],
    },
}

OBJ_SYSTEM = ("You extract STUDY OBJECTIVES from a clinical trial protocol. Call the "
              "record_objectives tool with every objective actually present in the text — "
              "do not invent any. Ground each in the page it appears on and a short exact "
              "quote. If none are present, pass an empty list.")
END_SYSTEM = ("You extract STUDY ENDPOINTS (outcome measures) from a clinical trial protocol. "
              "Call the record_endpoints tool with every endpoint actually present in the text — "
              "do not invent any. Ground each in the page it appears on and a short exact quote. "
              "If none are present, pass an empty list.")


# ---------------------------------------------------------------------------
# 4. The forced tool call (lazy anthropic import) -> dict
# ---------------------------------------------------------------------------
def call_tool(system: str, user: str, tool: dict, model: str = EXTRACT_MODEL) -> dict:
    """Force the model to answer by calling `tool`; return the tool call's input dict."""
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env (see config.load_secrets)
    msg = client.messages.create(
        model=model, max_tokens=MAX_TOKENS, system=system,
        tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": user}],
    )
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input)
    raise ValueError(f"Model did not call {tool['name']} (stop_reason={msg.stop_reason}).")


# ---------------------------------------------------------------------------
# 5. Tool-input dict -> validated Components
# ---------------------------------------------------------------------------
def _page_int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_objectives(data: dict, protocol_id: str) -> list[Component]:
    items = data.get("objectives", []) if isinstance(data, dict) else (data or [])
    out = []
    for i, it in enumerate(items, 1):
        out.append(Component(
            id=f"obj-{i:03d}", type="objective",
            data={"level": it.get("level", "secondary"), "text": it["text"]},
            provenance={"protocol_id": protocol_id, "page": _page_int(it.get("page")),
                        "section": it.get("section"), "quote": it.get("quote")},
        ))
    return out


def parse_endpoints(data: dict, protocol_id: str) -> list[Component]:
    items = data.get("endpoints", []) if isinstance(data, dict) else (data or [])
    out = []
    for i, it in enumerate(items, 1):
        out.append(Component(
            id=f"end-{i:03d}", type="endpoint",
            data={"level": it.get("level", "secondary"), "text": it["text"],
                  "timeframe": it.get("timeframe")},
            provenance={"protocol_id": protocol_id, "page": _page_int(it.get("page")),
                        "section": it.get("section"), "quote": it.get("quote")},
        ))
    return out


# ---------------------------------------------------------------------------
# 6. Orchestrator
# ---------------------------------------------------------------------------
def extract(protocol_id: str,
            pdf_path: Optional[str] = None,
            pages: Optional[list[tuple[int, str]]] = None,
            model: str = EXTRACT_MODEL,
            tool_llm: Callable[[str, str, dict, str], dict] = call_tool) -> ExtractionResult:
    """Extract objectives + endpoints from one protocol into validated Components.

    Pass `pdf_path` to read a file, or `pages` directly (tests). `tool_llm` is injectable
    so the pipeline can run with a stub (no API key)."""
    load_secrets()
    if pages is None:
        if pdf_path is None:
            raise ValueError("provide either pdf_path or pages")
        pages = load_pages(pdf_path)

    obj_text = find_relevant_text(pages, ["objective", "estimand"])
    end_text = find_relevant_text(pages, ["endpoint", "outcome measure", "estimand"])

    objectives = parse_objectives(tool_llm(OBJ_SYSTEM, obj_text, OBJECTIVES_TOOL, model), protocol_id)
    endpoints = parse_endpoints(tool_llm(END_SYSTEM, end_text, ENDPOINTS_TOOL, model), protocol_id)
    return ExtractionResult(protocol_id=protocol_id, components=objectives + endpoints)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Extract objectives + endpoints from a protocol PDF.")
    ap.add_argument("pdf_path", help="path to the protocol PDF")
    ap.add_argument("--protocol-id", required=True, help="asset/protocol id, e.g. pfizer_c4591001")
    ap.add_argument("--out", help="optional path to write the ExtractionResult JSON")
    ap.add_argument("--model", default=EXTRACT_MODEL)
    args = ap.parse_args()

    result = extract(args.protocol_id, pdf_path=args.pdf_path, model=args.model)

    print(f"\nExtracted {len(result.components)} components from {args.protocol_id}:")
    for c in result.components:
        print(f"  [{c.id}] {c.type:9} (p.{c.provenance.page}) {c.data.text[:90]}")

    if args.out:
        with open(args.out, "w") as f:
            f.write(result.model_dump_json(indent=2))
        print(f"\nSaved -> {args.out}")


if __name__ == "__main__":
    _main()
