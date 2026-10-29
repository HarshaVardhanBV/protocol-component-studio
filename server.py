"""Protocol Component Studio — full-fidelity web app.

Serves the hand-built HTML frontend (web/index.html) and one JSON model
(/api/model) computed live from the stored components via src/render.py.
Same look as the design prototype; real pipeline data underneath.
Credential-free to *read* (Neo4j/Anthropic only refresh the store).

Run:  uvicorn server:app --reload
"""
from __future__ import annotations
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse

import app_data as D
from src.models import component_text

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "web" / "index.html"


def build_model() -> dict:
    """One JSON blob the single-page frontend renders from."""
    ws = D.load_workspace()
    studies, by_study = [], {}

    for sid in ws["study_ids"]:
        insts = ws["by_study"][sid]
        meta = D.study_meta(sid)
        cf = D.conformance(sid, insts, ws["definitions"])

        docs = {}
        for dt in D.doc_types():
            rd = D.render_doc(sid, dt, insts)
            secs = []
            for s in rd.sections:
                if not s.instances:
                    continue
                frag = {f.instance_id: f.text for f in s.fragments}
                secs.append({
                    "section_id": s.section_id, "title": s.title,
                    "derived": s.derivation == "summary", "transform": s.transform,
                    "components": [{"id": i.id, "role": getattr(i.data, "role", None),
                                    "text": frag.get(i.id, component_text(i.data))}
                                   for i in s.instances],
                })
            docs[dt] = {"sections": secs}

        comps = {}
        for i in insts:
            if i.id in comps:
                continue
            did = i.definition_ids[0] if i.definition_ids else None
            d = D.definition(did) if did else None
            rows = D.impact(sid, insts, i.id)
            comps[i.id] = {
                "def_id": did or "—", "def_name": (d.name if d else i.type), "type": i.type,
                "standards": [{"framework": s.framework, "section": s.section}
                              for s in (d.standards if d else [])],
                "provenance": {"src": i.provenance.protocol_id, "page": i.provenance.page,
                               "section": i.provenance.section, "quote": i.provenance.quote},
                "version": i.version, "revisions": len(i.history),
                "shared": len(ws["def_studies"].get(did, [])) if did else 1,
                "impact": [{"doc": r["doc_type"], "section_id": r["section_id"], "title": r["title"],
                            "transform": r["transform"], "derived": r["derived"],
                            "review": r.get("fragment_status") == "needs_review"} for r in rows],
            }

        by_study[sid] = {"conformance": cf, "docs": docs, "components": comps}
        studies.append({"id": sid, "name": meta["name"], "drug": meta["drug"],
                        "title": meta["title"], "instances": len(insts),
                        "flags": cf["tally"]["error"], "warnings": cf["tally"]["warning"]})

    library = [{"id": did, "name": (D.definition(did).name if D.definition(did) else did),
                "count_by_study": {sid: ws["study_counts"].get(sid, {}).get(did, 0)
                                   for sid in ws["study_ids"]}}
               for did in ws["definition_ids"]]

    return {"studies": studies, "library": library, "docOrder": D.doc_types(),
            "docLabel": D.DOC_LABEL, "docTitle": D.DOC_TITLE, "coverage": D.COVERAGE,
            "byStudy": by_study}


app = FastAPI(title="Protocol Component Studio")
_MODEL_CACHE: dict | None = None
_CACHE_KEY = None


def _store_fingerprint():
    """Cheap staleness check: newest mtime across store/*.json. Lets the cache
    survive across requests but still pick up edits (revise/classify/re-extract)
    made to the store while the server is running."""
    return max((p.stat().st_mtime_ns for p in D.STORE.glob("*.json")), default=0)


def model() -> dict:
    global _MODEL_CACHE, _CACHE_KEY
    key = _store_fingerprint()
    if _MODEL_CACHE is None or key != _CACHE_KEY:
        _MODEL_CACHE = build_model()
        _CACHE_KEY = key
    return _MODEL_CACHE


@app.get("/api/model")
def api_model():
    return JSONResponse(model())


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX.read_text())
