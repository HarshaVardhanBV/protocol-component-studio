"""
classify.py — bind each instance to its template, keyed on (type, discriminator).

The discriminator depends on the component type:
  - objective / endpoint -> role (primary/secondary/exploratory)
  - arm                  -> arm type (CDISC C174222)
  - eligibility          -> kind (inclusion/exclusion)
  - population / visit   -> none (single template)

Deterministic, zero-cost, idempotent. The template library (definitions.py) is fixed,
so onboarding any protocol/indication mints ZERO new definitions.
"""
from __future__ import annotations

from typing import Callable, Optional

from .models import ComponentInstance, ComponentDefinition, ExtractionResult
from .definitions import library, LIBRARY_BY_ID, template_id, ROLES

Classifier = Callable[[ComponentInstance], str]
_VALID_ROLES = set(ROLES)


def template_library() -> list[ComponentDefinition]:
    return library()


def _discriminator(inst: ComponentInstance, role_fallback: str = "secondary") -> Optional[str]:
    t = inst.type
    if t in ("objective", "endpoint"):
        role = getattr(inst.data, "role", None)
        return role if role in _VALID_ROLES else role_fallback
    if t == "arm":
        return getattr(inst.data, "type", None) or "other"
    if t == "eligibility":
        return getattr(inst.data, "kind", None) or "inclusion"
    return None  # population, visit → single template


def type_classifier(role_fallback: str = "secondary") -> Classifier:
    def classify_one(inst: ComponentInstance) -> str:
        return template_id(inst.type, _discriminator(inst, role_fallback))
    return classify_one


def classify(results, classifier: Optional[Classifier] = None):
    if classifier is None:
        classifier = type_classifier()
    instances = _collect(results)
    used_ids, final = [], []
    for inst in instances:
        tid = classifier(inst)
        if tid not in LIBRARY_BY_ID:
            raise ValueError(f"classifier returned unknown template id: {tid!r}")
        if tid not in used_ids:
            used_ids.append(tid)
        final.append(inst.model_copy(update={"definition_ids": [tid]}))
    definitions = [LIBRARY_BY_ID[t] for t in used_ids]
    return definitions, final


def classification_report(results):
    instances = _collect(results)
    per_template, fallbacks = {}, []
    clf = type_classifier()
    for inst in instances:
        tid = clf(inst)
        per_template[tid] = per_template.get(tid, 0) + 1
        # a "fallback" only applies to role-typed components with an invalid role
        if inst.type in ("objective", "endpoint") and getattr(inst.data, "role", None) not in _VALID_ROLES:
            fallbacks.append(f"{inst.study_id}:{inst.id} (role={getattr(inst.data,'role',None)!r})")
    return {"per_template": per_template, "fallback_count": len(fallbacks), "fallbacks": fallbacks}


def _collect(results):
    out = []
    items = results if isinstance(results, list) else [results]
    for it in items:
        if isinstance(it, ExtractionResult):
            out.extend(it.instances)
        elif isinstance(it, ComponentInstance):
            out.append(it)
        else:
            raise TypeError(f"unexpected input: {type(it).__name__}")
    return out


def _main():
    import argparse, glob, json, os
    ap = argparse.ArgumentParser(description="Classify stored instances onto the fixed template library "
                                             "(writes definition_ids back into each store file + regenerates definitions.json).")
    ap.add_argument("--store", default="store")
    ap.add_argument("--report", action="store_true", help="print per-template counts and role fallbacks")
    args = ap.parse_args()

    study_paths = sorted(p for p in glob.glob(os.path.join(args.store, "*.json"))
                         if os.path.basename(p) != "definitions.json")
    used = {}
    for p in study_paths:
        result = ExtractionResult.model_validate(json.load(open(p)))
        defs, classified = classify(result)
        for d in defs:
            used[d.id] = d
        out = ExtractionResult(study_id=result.study_id, instances=classified)
        with open(p, "w") as f:
            f.write(out.model_dump_json(indent=2))
        print(f"{result.study_id}: classified {len(classified)} instances -> {len(defs)} templates")
        if args.report:
            rep = classification_report(result)
            for tid, n in sorted(rep["per_template"].items()):
                print(f"    {tid:24} {n}")
            if rep["fallback_count"]:
                print(f"    role fallbacks: {rep['fallback_count']}")

    defs_path = os.path.join(args.store, "definitions.json")
    with open(defs_path, "w") as f:
        json.dump([d.model_dump(mode="json") for d in used.values()], f, indent=2)
    print(f"wrote {defs_path} ({len(used)} definitions)")


if __name__ == "__main__":
    _main()
