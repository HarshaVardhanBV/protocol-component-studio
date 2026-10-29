"""
render.py — render components into document fragments.

A "document" is the slot registry in templates.py made concrete for one study:
each SectionSlot becomes a DocumentSection, and every instance of the study whose
type the slot accepts is placed into it. The same instance can land in more than
one document (an objective appears in both M11 and E3) — recorded as RENDERS edges.

Two orderings matter and are kept separate:
  - display_order: where a section sits in the finished document (what the reader sees).
  - build order:   the dependency order in which sections are generated. A DERIVED
                   section (a Synopsis summarising the rest) displays FIRST but must be
                   BUILT LAST, after its depends_on sections exist. The renderer
                   topologically sorts on depends_on, fills in that order, then returns
                   sections in display_order.
"""
from __future__ import annotations

from typing import Callable, Optional
from pydantic import BaseModel

from .models import ComponentInstance, component_text
from .templates import REGISTRY, SectionSlot


def doc_id(study_id: str, doc_type: str) -> str:
    return f"{study_id}:{doc_type}"


def section_uid(study_id: str, doc_type: str, section_id: str) -> str:
    return f"{study_id}:{doc_type}:{section_id}"


# A transform turns one instance's source text into the text a document needs.
# The real transform is an LLM (summarise, lay-language, elaborate); the default
# below is a deterministic stub so the pipeline is provable offline.
Transformer = Callable[[str, str], str]


def _default_transform(text: str, kind: str) -> str:
    if kind == "verbatim":
        return text
    if kind == "summarize":
        return text.split(". ")[0].rstrip(".") + "."
    if kind == "lay_language":
        return f"In simple terms: {text}"
    if kind == "elaborate":
        return f"{text} [estimand to be specified: treatment, population, variable, summary, intercurrent events]"
    if kind == "tabulate":
        return text
    if kind == "translate":
        return text
    return text


def _status_for(kind: str) -> str:
    # Lay-language participant-facing text must be reviewed before use.
    return "needs_review" if kind == "lay_language" else "draft"


class RenderedFragment(BaseModel):
    """The transformed text produced for one instance in one section — the
    artifact of a non-verbatim reuse (SAP elaboration, ICF lay language). Carries
    its own review status, because transformed participant-facing text needs QC."""
    fragment_uid: str
    doc_type: str
    section_uid: str
    instance_id: str
    instance_uid: str
    transform: str
    status: str = "draft"
    order: int = 0
    text: str


class RenderedSection(BaseModel):
    doc_type: str
    section_id: str
    section_uid: str
    title: str
    display_order: int = 0
    build_index: int = 0                 # position in the dependency (build) order
    derivation: str = "original"
    depends_on: list[str] = []
    transform: str = "verbatim"
    instances: list[ComponentInstance] = []
    fragments: list[RenderedFragment] = []   # non-verbatim transformed outputs


class RenderedDocument(BaseModel):
    study_id: str
    doc_type: str
    doc_id: str
    sections: list[RenderedSection] = []  # in display order

    def all_instances(self) -> list[ComponentInstance]:
        return [i for s in self.sections for i in s.instances]


def _order(insts: list[ComponentInstance]) -> list[ComponentInstance]:
    rank = {"primary": 0, "secondary": 1, "exploratory": 2}
    return sorted(insts, key=lambda i: (rank.get(getattr(i.data, "role", None), 9), i.id))


def build_order(slots: list[SectionSlot]) -> list[str]:
    """Topological sort of section ids on depends_on (Kahn). Ties broken by
    display_order so the result is deterministic. Falls back gracefully if a
    cycle is present (shouldn't happen for well-formed registries)."""
    by_id = {s.section_id: s for s in slots}
    indeg = {s.section_id: 0 for s in slots}
    for s in slots:
        for dep in s.depends_on:
            if dep in by_id:
                indeg[s.section_id] += 1
    ready = sorted([sid for sid, d in indeg.items() if d == 0],
                   key=lambda sid: by_id[sid].display_order)
    out = []
    while ready:
        sid = ready.pop(0)
        out.append(sid)
        for s in slots:
            if sid in s.depends_on and s.section_id not in out:
                indeg[s.section_id] -= 1
                if indeg[s.section_id] == 0:
                    ready.append(s.section_id)
        ready.sort(key=lambda x: by_id[x].display_order)
    # any leftover (cycle) appended by display_order
    for s in sorted(slots, key=lambda s: s.display_order):
        if s.section_id not in out:
            out.append(s.section_id)
    return out


def _summarize(slot: SectionSlot, built: dict[str, list[ComponentInstance]]) -> list[ComponentInstance]:
    """Deterministic summary: the PRIMARY-role items from each depended-on section
    (a synopsis leads with the primary objective + primary endpoint); if a source
    has no primary-role item, take its first. Deduplicated by instance id."""
    out, seen = [], set()
    for dep in slot.depends_on:
        src = built.get(dep, [])
        primaries = [i for i in src if getattr(i.data, "role", None) == "primary"]
        picked = primaries or (src[:1])
        for i in picked:
            if i.id not in seen:
                seen.add(i.id)
                out.append(i)
    return out


def render_document(study_id: str, doc_type: str,
                    instances: list[ComponentInstance],
                    transformer: Transformer = _default_transform) -> RenderedDocument:
    """Place a study's instances into one document type's slots, honouring
    dependency (build) order for derived sections, then return in display order.
    Non-verbatim slots (SAP elaborate, ICF lay language) also emit RenderedFragments
    carrying the transformed text — the same source instance, a different form."""
    slots: list[SectionSlot] = REGISTRY[doc_type]
    by_id = {s.section_id: s for s in slots}
    mine = [i for i in instances if i.study_id == study_id]

    order = build_order(slots)
    built: dict[str, list[ComponentInstance]] = {}
    for sid in order:
        slot = by_id[sid]
        if slot.derivation == "summary":
            built[sid] = _summarize(slot, built)
        else:
            built[sid] = _order([i for i in mine if i.type in slot.renders
                                 and (not slot.roles or getattr(i.data, "role", None) in slot.roles)])

    build_index = {sid: k for k, sid in enumerate(order)}
    sections = []
    for s in slots:
        suid = section_uid(study_id, doc_type, s.section_id)
        members = built[s.section_id]
        fragments = []
        if s.transform != "verbatim":
            for pos, inst in enumerate(members):
                iuid = f"{study_id}:{inst.id}"
                fragments.append(RenderedFragment(
                    fragment_uid=f"{suid}:{inst.id}", doc_type=doc_type, section_uid=suid,
                    instance_id=inst.id, instance_uid=iuid, transform=s.transform,
                    status=_status_for(s.transform), order=pos,
                    text=transformer(component_text(inst.data), s.transform)))
        sections.append(RenderedSection(
            doc_type=doc_type, section_id=s.section_id, section_uid=suid,
            title=s.title, display_order=s.display_order,
            build_index=build_index[s.section_id], derivation=s.derivation,
            depends_on=list(s.depends_on), transform=s.transform,
            instances=members, fragments=fragments))
    sections.sort(key=lambda s: s.display_order)
    return RenderedDocument(study_id=study_id, doc_type=doc_type,
                            doc_id=doc_id(study_id, doc_type), sections=sections)


def render_study(study_id: str, instances: list[ComponentInstance],
                 doc_types: Optional[list[str]] = None) -> list[RenderedDocument]:
    return [render_document(study_id, dt, instances)
            for dt in (doc_types or list(REGISTRY.keys()))]


# --- computed change-impact (no graph needed; the renderer IS the source of truth) ---
def instance_impact(study_id: str, instances: list[ComponentInstance], target_id: str) -> list[dict]:
    """Every document section the target instance lands in, computed by rendering the
    study across all document types and finding the sections that contain it (directly
    or via a derived Synopsis / transformed fragment). Returns dicts, not graph rows."""
    out = []
    for doc in render_study(study_id, instances):
        for s in doc.sections:
            if any(i.id == target_id for i in s.instances):
                fr = next((f for f in s.fragments if f.instance_id == target_id), None)
                out.append({"study": study_id, "doc_type": doc.doc_type,
                            "section_id": s.section_id, "title": s.title,
                            "transform": s.transform, "derived": s.derivation == "summary",
                            "fragment_status": fr.status if fr else None})
    out.sort(key=lambda r: (r["doc_type"], r["section_id"]))
    return out


def definition_impact(definition_id: str, results) -> list[dict]:
    """Every (study, document, section) affected by a definition — the union of its
    instances' impacts across the corpus. `results` is a list of ExtractionResult."""
    rows = []
    for r in results:
        insts = list(r.instances)
        for inst in insts:
            if definition_id in inst.definition_ids:
                rows.extend(instance_impact(r.study_id, insts, inst.id))
    return rows


def fragment_text(doc: RenderedDocument, skip_empty: bool = True) -> str:
    """Human-readable fragment — sections in display order; derived sections tagged."""
    lines = [f"# {doc.doc_type} — {doc.study_id}", ""]
    for s in doc.sections:
        if skip_empty and not s.instances:
            continue
        tag = "  (derived summary)" if s.derivation == "summary" else ""
        if s.transform != "verbatim":
            tag += f"  (transform: {s.transform})"
        lines.append(f"## {s.section_id}  {s.title}{tag}")
        frag = {f.instance_id: f.text for f in s.fragments}
        for i in s.instances:
            role = getattr(i.data, "role", None)
            lvl = f"[{role}] " if role else ""
            lines.append(f"- {lvl}{frag.get(i.id, component_text(i.data))}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
