"""
models.py — the USDM-*shaped* component contract.

This is the single source of truth for the whole app: every element extracted
from a protocol becomes a validated, versioned `Component` with provenance.
A USDM-shaped SUBSET on purpose (six element types), not the full CDISC USDM —
named honestly, the same way the PV toolkit called its measure IC, not EBGM.

Reuses the Pydantic-everywhere pattern from the AE Triage tool.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Controlled vocabularies (Literal = the same discipline as the triage schema)
# ---------------------------------------------------------------------------
ComponentType = Literal["objective", "endpoint", "arm", "population", "eligibility", "visit"]
ObjectiveLevel = Literal["primary", "secondary", "exploratory"]
EndpointLevel = Literal["primary", "secondary", "exploratory", "safety"]
ArmType = Literal["experimental", "active_comparator", "placebo_comparator", "sham", "other"]
CriterionKind = Literal["inclusion", "exclusion"]


# ---------------------------------------------------------------------------
# Provenance — where in the source protocol this element came from.
# `quote` is the exact source sentence, kept for the audit/traceability story.
# ---------------------------------------------------------------------------
class Provenance(BaseModel):
    protocol_id: str
    page: Optional[int] = None
    section: Optional[str] = None          # e.g. "6.1 Primary Objective"
    quote: Optional[str] = None            # exact source text, for audit


# ---------------------------------------------------------------------------
# The six USDM-shaped element models (the `data` payload of a Component)
# ---------------------------------------------------------------------------
class Objective(BaseModel):
    level: ObjectiveLevel
    text: str


class Endpoint(BaseModel):
    level: EndpointLevel
    text: str
    objective_ref: Optional[str] = None    # id of the Objective component it supports
    timeframe: Optional[str] = None         # e.g. "at Week 24"


class Arm(BaseModel):
    name: str
    type: ArmType
    description: Optional[str] = None


class Population(BaseModel):
    description: str
    planned_enrollment: Optional[int] = None
    condition: Optional[str] = None         # indication / disease


class EligibilityCriterion(BaseModel):
    kind: CriterionKind
    text: str
    number: Optional[str] = None            # e.g. "I3", "E7"


class Visit(BaseModel):
    name: str
    study_day: Optional[str] = None         # e.g. "Day 1", "Week 4 (±3 days)"
    procedures: list[str] = Field(default_factory=list)


ElementData = Union[Objective, Endpoint, Arm, Population, EligibilityCriterion, Visit]

# type string -> model. Used to coerce `data` to the right model by `type`,
# which avoids Pydantic picking the wrong union member (Objective vs Endpoint
# overlap on level+text).
ELEMENT_MODELS: dict[str, type[BaseModel]] = {
    "objective": Objective,
    "endpoint": Endpoint,
    "arm": Arm,
    "population": Population,
    "eligibility": EligibilityCriterion,
    "visit": Visit,
}


# ---------------------------------------------------------------------------
# The Component envelope — the versioned, provenance-tagged source of truth.
# One of these per extracted element; this is what becomes a graph node.
# ---------------------------------------------------------------------------
class Component(BaseModel):
    id: str                                 # stable id, e.g. "end-001"
    type: ComponentType
    version: int = 1
    data: ElementData
    provenance: Provenance
    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    supersedes: Optional[str] = None        # node key of the previous version, for the version chain

    @model_validator(mode="before")
    @classmethod
    def _coerce_data_by_type(cls, values):
        """Parse `data` into the model named by `type` BEFORE field validation,
        so a plain dict can't be mis-matched to the wrong element model."""
        if isinstance(values, dict):
            t, d = values.get("type"), values.get("data")
            model = ELEMENT_MODELS.get(t)
            if model is not None and isinstance(d, dict):
                values = {**values, "data": model(**d)}
        return values

    @model_validator(mode="after")
    def _type_matches_data(self):
        expected = ELEMENT_MODELS.get(self.type)
        if expected is not None and not isinstance(self.data, expected):
            raise ValueError(f"type '{self.type}' does not match data {type(self.data).__name__}")
        return self


# ---------------------------------------------------------------------------
# What the extractor returns for one protocol (Phase 1 will populate this).
# ---------------------------------------------------------------------------
class ExtractionResult(BaseModel):
    protocol_id: str
    components: list[Component] = Field(default_factory=list)

    def by_type(self, t: ComponentType) -> list[Component]:
        return [c for c in self.components if c.type == t]
