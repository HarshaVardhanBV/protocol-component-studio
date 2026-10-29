from __future__ import annotations
from collections import Counter
from typing import Callable, Optional
from .models import ComponentInstance, ComponentDefinition, ExtractionResult, component_text
from .merge import _norm, _similar, _ID_PREFIX
from .config import load_secrets

INDUCE_MODEL = "claude-opus-4-8"

# An inducer takes the per-instance records for ONE component type and returns
# concept groups. Each record is {"study_id", "text", "level"}; each returned
# group is {"name", "level", "description", "members": [int indices]}.
Inducer = Callable[[list[dict], str], list[dict]]


def _mode_level(levels):
    levels = [l for l in levels if l]
    return Counter(levels).most_common(1)[0][0] if levels else None


def fuzzy_inducer(threshold: float = 0.90) -> Inducer:
    """Offline fallback: cluster normalized text across studies, name from the
    shortest member (usually the cleanest canonical statement)."""
    def induce(records, kind):
        clusters = []  # (norm_rep, [idx])
        for i, r in enumerate(records):
            n = _norm(r["text"])
            for rep, idxs in clusters:
                if _similar(n, rep) >= threshold:
                    idxs.append(i)
                    break
            else:
                clusters.append((n, [i]))
        groups = []
        for _, idxs in clusters:
            members = [records[i] for i in idxs]
            name = min((m["text"] for m in members), key=len).strip().rstrip(".")
            groups.append({"name": name, "level": _mode_level(m["level"] for m in members),
                           "description": None, "members": idxs})
        return groups
    return induce


_INDUCE_TOOL = {
    "name": "record_definitions",
    "input_schema": {
        "type": "object",
        "properties": {
            "definitions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string",
                                 "description": "Short canonical, content-free concept name, e.g. 'Efficacy to prevent COVID-19'"},
                        "level": {"type": "string",
                                  "description": "Typical role across studies: primary/secondary/exploratory/safety, or omit if it varies"},
                        "description": {"type": "string",
                                        "description": "One sentence describing the reusable concept, no study- or drug-specific detail"},
                        "members": {"type": "array", "items": {"type": "integer"},
                                    "description": "Indices of every instance that instantiates this concept"},
                    },
                    "required": ["name", "members"],
                },
            }
        },
        "required": ["definitions"],
    },
}

_INDUCE_SYSTEM = (
    "You induce reusable component DEFINITIONS from component INSTANCES drawn from "
    "multiple clinical studies. A definition is the content-free concept that two or "
    "more instances share (e.g. 'Efficacy to prevent COVID-19'), stripped of any drug, "
    "dose, or study-specific wording. Group every instance that expresses the same "
    "underlying concept, even across different studies and different drugs. Keep "
    "clinically distinct concepts separate (preventing COVID-19 is NOT preventing "
    "SEVERE COVID-19; a primary-series immune response is NOT a booster-dose response). "
    "Every index must appear in exactly one group; a concept seen in only one instance "
    "is still a valid single-member definition."
)


def llm_inducer(model: str = INDUCE_MODEL) -> Inducer:
    def induce(records, kind):
        import anthropic
        load_secrets()
        numbered = "\n".join(
            f"[{i}] ({r['study_id']} / {r['level'] or '?'}) {r['text']}"
            for i, r in enumerate(records)
        )
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model, max_tokens=4096, system=_INDUCE_SYSTEM,
            tools=[_INDUCE_TOOL], tool_choice={"type": "tool", "name": "record_definitions"},
            messages=[{"role": "user", "content": f"Component type: {kind}\n\n{numbered}"}],
        )
        for b in msg.content:
            if getattr(b, "type", None) == "tool_use":
                return [g for g in dict(b.input).get("definitions", []) if g.get("members")]
        raise ValueError("no definitions")
    return induce


def _collect(results):
    """Accept a list of ExtractionResult, a single ExtractionResult, or a flat
    list of ComponentInstance; return a flat list of instances."""
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


def induce(results, inducer: Optional[Inducer] = None):
    """Cross-study definition induction.

    Returns (definitions, instances): freshly minted ComponentDefinitions and
    copies of every input instance with definition_ids populated. Instances keep
    their original ids and studies; only definition_ids changes.
    """
    if inducer is None:
        inducer = llm_inducer()
    instances = _collect(results)
    # Instance ids are only unique within a study (both studies reuse obj-001),
    # so track definition assignments by position, not by id.
    pos = {id(inst): k for k, inst in enumerate(instances)}
    assigned = [set() for _ in instances]

    by_type = {}
    for inst in instances:
        by_type.setdefault(inst.type, []).append(inst)

    definitions = []
    counters = {}
    for t, insts in by_type.items():
        records = [{"study_id": i.study_id, "text": component_text(i.data),
                    "level": getattr(i.data, "role", None)} for i in insts]
        groups = inducer(records, t)
        covered = {m for g in groups for m in g["members"]}
        groups = groups + [{"name": component_text(insts[j].data).strip().rstrip("."),
                            "level": getattr(insts[j].data, "role", None),
                            "description": None, "members": [j]}
                           for j in range(len(insts)) if j not in covered]
        for g in groups:
            counters[t] = counters.get(t, 0) + 1
            def_id = f"def-{_ID_PREFIX.get(t, t[:3])}-{counters[t]:03d}"
            _lvl = g.get("level")
            _role = _lvl if _lvl in ("primary", "secondary", "exploratory") else None
            definitions.append(ComponentDefinition(
                id=def_id, type=t, name=g["name"],
                role=_role, description=g.get("description")))
            for m in g["members"]:
                assigned[pos[id(insts[m])]].add(def_id)

    final = [inst.model_copy(update={
                "definition_ids": sorted(set(inst.definition_ids) | assigned[k])})
             if assigned[k] else inst
             for k, inst in enumerate(instances)]
    return definitions, final


def _main():
    import argparse, glob, json, os
    ap = argparse.ArgumentParser(description="Induce shared ComponentDefinitions across studies.")
    ap.add_argument("inputs", nargs="*", help="ExtractionResult JSON files (default: store/*.json)")
    ap.add_argument("--store", default="store", help="store dir (used when no inputs given)")
    ap.add_argument("--defs-out", default=None, help="definitions output (default: <store>/definitions.json)")
    ap.add_argument("--local", action="store_true", help="use offline fuzzy inducer (no API)")
    ap.add_argument("--no-write-instances", action="store_true",
                    help="do not rewrite study files with populated definition_ids")
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

    inducer = fuzzy_inducer() if args.local else llm_inducer()
    definitions, instances = induce(results, inducer=inducer)

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

    def_studies = {d.id: set() for d in definitions}
    for inst in instances:
        for did in inst.definition_ids:
            def_studies.setdefault(did, set()).add(inst.study_id)
    spanning = sum(1 for d in definitions if len(def_studies[d.id]) > 1)
    print(f"induced {len(definitions)} definitions across {len(results)} studies "
          f"({spanning} span >1 study) -> {defs_out}")


if __name__ == "__main__":
    _main()
