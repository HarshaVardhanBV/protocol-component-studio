"""
conformance.py — turn the governance smell into an automated check.

Reads the component instances for each study and checks them against the template
library's expectations (the `min_occurs`/`max_occurs` and `conformance_rules` authored
on each ComponentDefinition), plus a few plausibility heuristics. Surfaces exactly the
kind of thing you'd eyeball-flag — "this study has 7 primary endpoints, review" — as
structured findings with a severity.

Pure computation over components + definitions; no graph, no API.
"""
from __future__ import annotations

from typing import Optional

from .models import ExtractionResult, ComponentDefinition
from .definitions import library

# Soft plausibility thresholds (advisory). A study usually has ONE primary objective
# and a small number of (co-)primary endpoints; well above that is worth a human look.
PRIMARY_OBJECTIVE_SOFT_MAX = 1
PRIMARY_ENDPOINT_SOFT_MAX = 3

Severity = str  # "error" | "warning" | "info"


def _library_by_id(definitions=None) -> dict[str, ComponentDefinition]:
    defs = definitions if definitions is not None else library()
    return {d.id: d for d in defs}


def check_study(study_id: str, instances, definitions=None) -> list[dict]:
    """Return a list of findings for one study. Each finding:
    {rule, severity, detail, count?, expected?}."""
    by_id = _library_by_id(definitions)
    findings: list[dict] = []

    # group instances by the template they classified into
    counts: dict[str, int] = {}
    for inst in instances:
        for def_id in inst.definition_ids:
            counts[def_id] = counts.get(def_id, 0) + 1

    # 1. hard cardinality vs the definition's min/max_occurs
    for def_id, d in by_id.items():
        n = counts.get(def_id, 0)
        if n < d.min_occurs:
            findings.append({"rule": "cardinality.min", "severity": "error",
                             "detail": f"{study_id}: {n} {def_id} (expects >= {d.min_occurs})",
                             "count": n, "expected": d.min_occurs})
        if d.max_occurs is not None and n > d.max_occurs:
            findings.append({"rule": "cardinality.max", "severity": "error",
                             "detail": f"{study_id}: {n} {def_id} (expects <= {d.max_occurs})",
                             "count": n, "expected": d.max_occurs})

    # 2. plausibility (advisory) — implausible multiplicity of primaries
    for def_id, soft in (("OBJ-PRIMARY", PRIMARY_OBJECTIVE_SOFT_MAX),
                         ("EP-PRIMARY", PRIMARY_ENDPOINT_SOFT_MAX)):
        n = counts.get(def_id, 0)
        if n > soft:
            findings.append({"rule": "plausibility.primary_count", "severity": "warning",
                             "detail": f"{study_id}: {n} {def_id} — typically <= {soft}; review for "
                                       f"over-tagging or un-merged restatements",
                             "count": n, "expected": soft})

    # 3. objective/endpoint bleed heuristic — an endpoint phrased like an objective
    for inst in instances:
        if inst.type == "endpoint":
            txt = (inst.data.text or "").strip().lower()
            if txt.startswith("to "):
                findings.append({"rule": "bleed.endpoint_as_objective", "severity": "warning",
                                 "detail": f"{study_id}:{inst.id} endpoint reads like an objective: "
                                           f"\"{inst.data.text[:70]}\""})

    # 4. ref integrity (advisory) — endpoints should reference an objective
    for inst in instances:
        if inst.type == "endpoint" and not getattr(inst.data, "objective_ref", None):
            findings.append({"rule": "ref.endpoint_objective", "severity": "info",
                             "detail": f"{study_id}:{inst.id} endpoint has no objective_ref (EP-REF-1)"})

    # 5. version integrity (governance) — history gaps / tampering / missing provenance
    from .revise import verify_history
    for inst in instances:
        for problem in verify_history(inst):
            findings.append({"rule": "version.integrity", "severity": "error", "detail": problem})

    return findings


def check_corpus(results, definitions=None) -> dict:
    """Run checks across a corpus (list of ExtractionResult). Returns findings +
    a severity tally."""
    all_findings = []
    for r in results:
        all_findings.extend(check_study(r.study_id, r.instances, definitions))
    tally = {"error": 0, "warning": 0, "info": 0}
    for f in all_findings:
        tally[f["severity"]] = tally.get(f["severity"], 0) + 1
    return {"findings": all_findings, "tally": tally}


def _main():
    import argparse, glob, json, os
    ap = argparse.ArgumentParser(description="Conformance / plausibility check over the component store.")
    ap.add_argument("--store", default="store")
    ap.add_argument("--severity", default="info", choices=["error", "warning", "info"],
                    help="minimum severity to print")
    args = ap.parse_args()

    order = {"error": 0, "warning": 1, "info": 2}
    cutoff = order[args.severity]
    paths = sorted(p for p in glob.glob(os.path.join(args.store, "*.json"))
                   if os.path.basename(p) != "definitions.json")
    results = [ExtractionResult.model_validate(json.load(open(p))) for p in paths]

    rep = check_corpus(results)
    print("tally:", rep["tally"])
    for f in rep["findings"]:
        if order[f["severity"]] <= cutoff:
            print(f"  [{f['severity']:7}] {f['rule']:32} {f['detail']}")


if __name__ == "__main__":
    _main()
