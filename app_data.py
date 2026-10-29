"""Pure data layer for the Streamlit demo — no Streamlit, no Neo4j, no API.

Everything the UI shows is computed from the stored ExtractionResult JSON in
``store/`` plus the fixed template library and the YAML document templates.
The renderer is the single source of truth, so change-impact can't drift from
what actually renders. Credential-free by design: the live graph (Neo4j Aura)
and extraction (Anthropic) are only needed to *refresh* the store, not to read it.
"""
from __future__ import annotations
import glob
import json
from pathlib import Path

from src.models import ExtractionResult, component_text
from src.classify import classify
from src.render import render_document, instance_impact
from src.templates import REGISTRY
from src.conformance import check_study
from src.definitions import LIBRARY_BY_ID

ROOT = Path(__file__).resolve().parent
STORE = ROOT / "store"

# Display order for the document tabs (only those present in REGISTRY are shown).
DOC_ORDER = ["M11", "E3", "SAP", "ICF", "PBRER"]
DOC_LABEL = {"M11": "ICH M11", "E3": "ICH E3", "SAP": "SAP", "ICF": "ICF", "PBRER": "PBRER"}
DOC_TITLE = {
    "M11": "Clinical trial protocol", "E3": "Clinical study report",
    "SAP": "Statistical analysis plan", "ICF": "Informed consent form",
    "PBRER": "Periodic benefit-risk evaluation report",
}

# Study metadata (the store JSON holds only study_id + instances).
STUDY_META = {
    "moderna_cove": {"name": "Moderna COVE", "drug": "mRNA-1273",
                     "title": "Phase 3, SARS-CoV-2 prevention"},
    "pfizer_c4591001": {"name": "Pfizer C4591001", "drug": "BNT162b2",
                        "title": "Phase 1/2/3, SARS-CoV-2 prevention"},
}

# Honest, illustrative per-document coverage: how many sections of the *real*
# ICH document are populated from the component model vs. narrative-authored.
# (The template library models a USDM-shaped subset — named honestly.)
COVERAGE = {"M11": (5, 42), "E3": (3, 31), "SAP": (2, 18), "ICF": (3, 14), "PBRER": (3, 20)}

TRANSFORM_LABEL = {
    "verbatim": "verbatim", "summarize": "summary", "summary": "summary",
    "lay_language": "lay · needs review", "elaborate": "elaborated",
}


def study_name(study_id: str) -> str:
    return STUDY_META.get(study_id, {}).get("name", study_id)


def study_meta(study_id: str) -> dict:
    return STUDY_META.get(study_id, {"name": study_id, "drug": "—", "title": ""})


def doc_types() -> list[str]:
    present = [d for d in DOC_ORDER if d in REGISTRY]
    # include any registry doc types not in our known order, at the end
    return present + [d for d in REGISTRY if d not in present]


def load_workspace() -> dict:
    """Load every stored study, classify instances onto the fixed template
    library, and group by study. Returns a dict the UI can render from."""
    paths = sorted(glob.glob(str(STORE / "*.json")))
    results = []
    for p in paths:
        raw = json.load(open(p))
        # store/ also holds definitions.json (the template library, a list) —
        # load only per-study ExtractionResult files.
        if isinstance(raw, dict) and "study_id" in raw and "instances" in raw:
            results.append(ExtractionResult.model_validate(raw))
    definitions, classified = classify(results)

    by_study: dict[str, list] = {}
    for inst in classified:
        by_study.setdefault(inst.study_id, []).append(inst)

    # per-study template counts (definition id -> count) and corpus counts
    corpus_counts: dict[str, int] = {}
    study_counts: dict[str, dict[str, int]] = {}
    for sid, insts in by_study.items():
        sc: dict[str, int] = {}
        for i in insts:
            for d in i.definition_ids:
                sc[d] = sc.get(d, 0) + 1
                corpus_counts[d] = corpus_counts.get(d, 0) + 1
        study_counts[sid] = sc

    # how many studies instantiate each definition (for the reuse count)
    def_studies: dict[str, set] = {}
    for sid, insts in by_study.items():
        for i in insts:
            for d in i.definition_ids:
                def_studies.setdefault(d, set()).add(sid)

    return {
        "study_ids": list(by_study.keys()),
        "by_study": by_study,
        "definitions": definitions,
        "definition_ids": [d.id for d in definitions],
        "corpus_counts": corpus_counts,
        "study_counts": study_counts,
        "def_studies": {k: sorted(v) for k, v in def_studies.items()},
    }


def render_doc(study_id: str, doc_type: str, instances: list):
    return render_document(study_id, doc_type, instances)


def impact(study_id: str, instances: list, instance_id: str) -> list[dict]:
    return instance_impact(study_id, instances, instance_id)


def conformance(study_id: str, instances: list, definitions: list) -> dict:
    findings = check_study(study_id, instances, definitions)
    tally = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        tally[f["severity"]] = tally.get(f["severity"], 0) + 1
    return {"findings": findings, "tally": tally}


def definition(def_id: str):
    return LIBRARY_BY_ID.get(def_id)


def find_instance(instances: list, instance_id: str):
    return next((i for i in instances if i.id == instance_id), None)


def _dot_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def ego_graph_dot(study_id: str, instances: list, instance_id: str, n_studies: int) -> str:
    """Graphviz DOT for the scoped ego-graph of one component:
    definition + source protocol -> instance -> the sections it renders into.
    Mirrors the four node types and three edge kinds of the real Neo4j model."""
    inst = find_instance(instances, instance_id)
    if inst is None:
        return "digraph G {}"
    def_id = inst.definition_ids[0] if inst.definition_ids else "?"
    src = inst.provenance.protocol_id
    rows = impact(study_id, instances, instance_id)

    def node(nid, label, fill, stroke, font="#14202B"):
        return (f'"{nid}" [label="{_dot_escape(label)}", shape=box, style="rounded,filled", '
                f'fillcolor="{fill}", color="{stroke}", fontcolor="{font}", '
                f'fontname="Helvetica", fontsize=11, margin="0.12,0.07"];')

    lines = [
        "digraph G {", "rankdir=LR; bgcolor=transparent;",
        'node [penwidth=1.3]; edge [fontname="Helvetica", fontsize=9, color="#9AA6AE", fontcolor="#5C6872"];',
        node("def", def_id + "\\n(definition)", "#E1F5EE", "#2E6E7E", "#0C5F4C"),
        node("src", src + "\\n(source protocol)", "#F1F3F5", "#B4BDC4", "#45505A"),
        node("inst", study_name(study_id) + "\\ninstance · " + inst.id, "#EAF7F1", "#5DCAA5", "#0C5F4C"),
    ]
    lines.append('"def" -> "inst" [label="INSTANTIATED_AS", color="#2E6E7E", fontcolor="#2E6E7E"];')
    lines.append('"src" -> "inst" [label="EXTRACTED_FROM"];')
    for k, r in enumerate(rows):
        review = r.get("fragment_status") == "needs_review"
        fill = "#FAEEDA" if review else "#EAF2FB"
        stroke = "#E3B36A" if review else "#B9D7F0"
        font = "#7A4A0C" if review else "#1A4C80"
        lbl = f'{r["doc_type"]} · {r["section_id"]}'
        lines.append(node(f"sec{k}", lbl, fill, stroke, font))
        xf = TRANSFORM_LABEL.get(r["transform"], r["transform"])
        if r.get("derived"):
            xf = "derived"
        ecol = "#B06A1E" if review else "#2E8E70"
        style = ', style=dashed' if review else ''
        lines.append(f'"inst" -> "sec{k}" [label="{xf}", color="{ecol}", fontcolor="{ecol}"{style}];')
    if n_studies > 1:
        lines.append(node("more", f"+{n_studies-1} other\\nstud{'ies' if n_studies-1>1 else 'y'}", "#F7F8FA", "#D7DEE4", "#5C6872"))
        lines.append('"def" -> "more" [label="INSTANTIATED_AS", style=dotted, color="#B4BDC4", fontcolor="#9AA6AE"];')
    lines.append("}")
    return "\n".join(lines)


if __name__ == "__main__":
    ws = load_workspace()
    print("studies:", ws["study_ids"])
    print("definitions used:", ws["definition_ids"])
    sid = ws["study_ids"][0]
    insts = ws["by_study"][sid]
    obj = next(i for i in insts if i.type == "objective")
    print("impact rows:", len(impact(sid, insts, obj.id)))
    print("conformance:", conformance(sid, insts, ws["definitions"])["tally"])
    print("dot lines:", ego_graph_dot(sid, insts, obj.id, len(ws["def_studies"].get(obj.definition_ids[0], []))).count("\n"))
