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

from .models import ComponentType

DocType = Literal["M11", "E3"]


class SectionSlot(BaseModel):
    doc_type: DocType
    section_id: str                 # e.g. "M11-OBJ"
    title: str
    renders: list[ComponentType]    # which component types feed this section


# ICH M11-style protocol synopsis (indicative subset)
M11_SYNOPSIS: list[SectionSlot] = [
    SectionSlot(doc_type="M11", section_id="M11-OBJ", title="Objectives and Endpoints",
                renders=["objective", "endpoint"]),
    SectionSlot(doc_type="M11", section_id="M11-DESIGN", title="Overall Design",
                renders=["arm"]),
    SectionSlot(doc_type="M11", section_id="M11-POP", title="Population and Eligibility",
                renders=["population", "eligibility"]),
    SectionSlot(doc_type="M11", section_id="M11-SOA", title="Schedule of Activities",
                renders=["visit"]),
]

# ICH E3-style CSR study-design section (indicative subset)
E3_STUDY_DESIGN: list[SectionSlot] = [
    SectionSlot(doc_type="E3", section_id="E3-9.2", title="Study Objectives",
                renders=["objective"]),
    SectionSlot(doc_type="E3", section_id="E3-9.3", title="Overall Study Design and Plan",
                renders=["arm"]),
    SectionSlot(doc_type="E3", section_id="E3-9.4", title="Selection of Study Population",
                renders=["population", "eligibility"]),
    SectionSlot(doc_type="E3", section_id="E3-9.5", title="Efficacy and Safety Variables (Endpoints)",
                renders=["endpoint"]),
    SectionSlot(doc_type="E3", section_id="E3-9.5.1", title="Schedule of Assessments",
                renders=["visit"]),
]

REGISTRY: dict[str, list[SectionSlot]] = {
    "M11": M11_SYNOPSIS,
    "E3": E3_STUDY_DESIGN,
}


def slots_for_component_type(ct: ComponentType) -> list[SectionSlot]:
    """Every section (across all document types) that a given component type feeds.
    This is the static side of change-impact: which slots COULD a component land in."""
    return [s for slots in REGISTRY.values() for s in slots if ct in s.renders]
