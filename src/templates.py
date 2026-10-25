"""
templates.py — documents modelled as a registry of section slots.

This is the "componentize the templates" decision, done cleanly: each document
type (M11 synopsis, E3 CSR study-design) is a list of section slots, and each
slot declares which COMPONENT TYPES render into it. Rendering a component into a
slot creates the (:DocumentSection)-[:RENDERS]->(:Component) edge that powers
change-impact.

Adding a new document type later (SAP, PBRER) = appending another registry here.
No re-architecture — that's the whole point (see the vault note's
"Vision vs. shippable atom").

NOTE: section ids/titles are indicative, not an authoritative reproduction of
the ICH M11 or E3 templates. A shaped subset, named as such.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .models import ComponentType, TransformKind

DocType = Literal["M11", "E3", "SAP", "ICF"]


Derivation = Literal["original", "summary"]


class SectionSlot(BaseModel):
    doc_type: DocType
    section_id: str                 # e.g. "M11-OBJ"
    title: str
    renders: list[ComponentType] = []   # component types this section places directly
    display_order: int = 0          # position in the finished document (what the reader sees)
    derivation: Derivation = "original"  # "summary" = content derived from other sections
    depends_on: list[str] = []      # section_ids this one derives from (summary sections)
    transform: TransformKind = "verbatim"  # how placed instances are transformed for THIS doc


# ICH M11-style protocol synopsis (indicative subset).
# The Synopsis is a DERIVED section: it summarises the rest of the document, so it
# displays FIRST (display_order 0) but must be BUILT LAST (after its depends_on
# sections exist). That split is the whole point of this registry.
M11_SYNOPSIS: list[SectionSlot] = [
    SectionSlot(doc_type="M11", section_id="M11-SYN", title="Protocol Synopsis",
                display_order=0, derivation="summary",
                depends_on=["M11-OBJ", "M11-DESIGN", "M11-POP", "M11-SOA"]),
    SectionSlot(doc_type="M11", section_id="M11-OBJ", title="Objectives and Endpoints",
                renders=["objective", "endpoint"], display_order=1),
    SectionSlot(doc_type="M11", section_id="M11-DESIGN", title="Overall Design",
                renders=["arm"], display_order=2),
    SectionSlot(doc_type="M11", section_id="M11-POP", title="Population and Eligibility",
                renders=["population", "eligibility"], display_order=3),
    SectionSlot(doc_type="M11", section_id="M11-SOA", title="Schedule of Activities",
                renders=["visit"], display_order=4),
]

# ICH E3-style CSR study-design section (indicative subset)
E3_STUDY_DESIGN: list[SectionSlot] = [
    SectionSlot(doc_type="E3", section_id="E3-9.2", title="Study Objectives",
                renders=["objective"], display_order=0),
    SectionSlot(doc_type="E3", section_id="E3-9.3", title="Overall Study Design and Plan",
                renders=["arm"], display_order=1),
    SectionSlot(doc_type="E3", section_id="E3-9.4", title="Selection of Study Population",
                renders=["population", "eligibility"], display_order=2),
    SectionSlot(doc_type="E3", section_id="E3-9.5", title="Efficacy and Safety Variables (Endpoints)",
                renders=["endpoint"], display_order=3),
    SectionSlot(doc_type="E3", section_id="E3-9.5.1", title="Schedule of Assessments",
                renders=["visit"], display_order=4),
]

# SAP (Statistical Analysis Plan) — reuses the SAME objective/endpoint components,
# but endpoints are *elaborated* (the estimand spelled out statistically).
SAP_PLAN: list[SectionSlot] = [
    SectionSlot(doc_type="SAP", section_id="SAP-OBJ", title="Objectives",
                renders=["objective"], display_order=0, transform="verbatim"),
    SectionSlot(doc_type="SAP", section_id="SAP-EP", title="Endpoints and Estimands",
                renders=["endpoint"], display_order=1, transform="elaborate"),
]

# ICF (Informed Consent Form) — reuses the SAME objective components, rendered in
# plain *lay language* for participants. The transformed text must be reviewed.
ICF_FORM: list[SectionSlot] = [
    SectionSlot(doc_type="ICF", section_id="ICF-PURPOSE", title="Why is this study being done?",
                renders=["objective"], display_order=0, transform="lay_language"),
]

REGISTRY: dict[str, list[SectionSlot]] = {
    "M11": M11_SYNOPSIS,
    "E3": E3_STUDY_DESIGN,
    "SAP": SAP_PLAN,
    "ICF": ICF_FORM,
}


def slots_for_component_type(ct: ComponentType) -> list[SectionSlot]:
    """Every section (across all document types) that a given component type feeds.
    This is the static side of change-impact: which slots COULD a component land in."""
    return [s for slots in REGISTRY.values() for s in slots if ct in s.renders]
