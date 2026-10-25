"""
classify.py — map each instance to a fixed template definition (the runtime binder).

Classification is deterministic and keyed on (component_type, role): a "primary
objective" instance → the OBJ-PRIMARY template, a "secondary endpoint" → EP-SECONDARY.
The template library (src/definitions.py) is fixed and regulatory-grounded, so
onboarding any protocol in any indication mints ZERO new definitions.

Role is read from the instance's `level` (primary/secondary/exploratory). Some
endpoint instances currently carry a non-role value in `level` (e.g. "safety",
which is really an orthogonal *purpose*, not a role) — a known extraction artefact.
Those fall back to `fallback_role` and are reported by `classification_report`; the
proper fix is to re-extract endpoints with role and purpose on separate axes.
"""
from __future__ import annotations

from typing import Callable, Optional

from .models import ComponentInstance, ComponentDefinition, ExtractionResult
from .induce import _collect
from .definitions import library, LIBRARY_BY_ID, template_id, ROLES

Classifier = Callable[[ComponentInstance], str]

_VALID_ROLES = set(ROLES)


def template_library() -> list[ComponentDefinition]:
    """The complete fixed template library."""
    return library()


def _role_of(inst: ComponentInstance, fallback: str) -> str:
    role = getattr(inst.data, "role", None)
    return role if role in _VALID_ROLES else fallback


def type_role_classifier(fallback_role: str = "secondary") -> Classifier:
    """Deterministic classifier: (type, role) -> template id."""
    def classify_one(inst: ComponentInstance) -> str:
        return template_id(inst.type, _role_of(inst, fallback_role))
    return classify_one


# Back-compat alias.
type_classifier = type_role_classifier


def classify(results, classifier: Optional[Classifier] = None):
    """Classify instances into the fixed template library.

    Returns (definitions, instances): the templates actually used (full regulatory
    metadata) and copies of every instance with `definition_ids` set to exactly its
    template. Never invents a definition, regardless of how many protocols load.
    """
    if classifier is None:
        classifier = type_role_classifier()
    instances = _collect(results)
    used_ids: list[str] = []
    final: list[ComponentInstance] = []
    for inst in instances:
        tid = classifier(inst)
        if tid not in LIBRARY_BY_ID:
            raise ValueError(f"classifier returned unknown template id: {tid!r}")
        if tid not in used_ids:
            used_ids.append(tid)
        final.append(inst.model_copy(update={"definition_ids": [tid]}))
    definitions = [LIBRARY_BY_ID[t] for t in used_ids]
    return definitions, final


def classification_report(results) -> dict:
    """Diagnostics: counts per template, and instances whose `level` was not a valid
    role (the safety-in-level artefact) and therefore fell back."""
    instances = _collect(results)
    per_template: dict[str, int] = {}
    fallbacks: list[str] = []
    clf = type_role_classifier()
    for inst in instances:
        tid = clf(inst)
        per_template[tid] = per_template.get(tid, 0) + 1
        if getattr(inst.data, "role", None) not in _VALID_ROLES:
            fallbacks.append(f"{inst.study_id}:{inst.id} (role={getattr(inst.data,'role',None)!r})")
    return {"per_template": per_template, "fallback_count": len(fallbacks), "fallbacks": fallbacks}


def _main():
    import argparse, glob, json, os
    ap = argparse.ArgumentParser(
        description="Classify instances into the fixed template-only definition library.")
    ap.add_argument("inputs", nargs="*")
    ap.add_argument("--store", default="store")
    ap.add_argument("--defs-out", default=None)
    ap.add_argument("--full-library", action="store_true",
                    help="write the whole template library, not just templates used")
    ap.add_argument("--no-write-instances", action="store_true")
    ap.add_argument("--report", action="store_true", help="print a classification report")
    args = ap.parse_args()

    paths = args.inputs or sorted(
        p for p in glob.glob(os.path.join(args.store, "*.json"))
        if os.path.basename(p) != "definitions.json")
    if not paths:
        raise SystemExit("no input study files found")

    results, path_by_study = [], {}
    for p in paths:
        with open(p) as f:
            r = ExtractionResult.model_validate(json.load(f))
        results.append(r)
        path_by_study[r.study_id] = p

    definitions, instances = classify(results)
    if args.full_library:
        definitions = library()

    defs_out = args.defs_out or os.path.join(args.store, "definitions.json")
    with open(defs_out, "w") as f:
        json.dump([d.model_dump(mode="json") for d in definitions], f, indent=2)

    by_study = {}
    for inst in instances:
        by_study.setdefault(inst.study_id, []).append(inst)
    if not args.no_write_instances:
        for study_id, insts in by_study.items():
            updated = ExtractionResult(study_id=study_id, instances=insts)
            with open(path_by_study[study_id], "w") as f:
                json.dump(updated.model_dump(mode="json"), f, indent=2)

    print(f"classified {len(instances)} instances across {len(results)} studies "
          f"into {len(definitions)} template definitions -> {defs_out}")
    if args.report:
        rep = classification_report(results)
        print("per-template:", rep["per_template"])
        if rep["fallback_count"]:
            print(f"fallback (non-role level): {rep['fallback_count']} ->", rep["fallbacks"][:8])


if __name__ == "__main__":
    _main()
