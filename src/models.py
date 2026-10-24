"""
models.py — the component contract, split into DEFINITIONS and INSTANCES.

- ComponentDefinition: content-less, study-agnostic "slot" derived from the
  template/standard (USDM/M11), e.g. "Primary Efficacy Objective". The class.
- ComponentInstance: a definition hydrated with content for ONE study/context
  (drug, study), e.g. Moderna-COVE's primary efficacy objective text. The object.
- Study: the context an instance is hydrated for.

A definition has many instances (one per study); an instance links to one-or-more
definitions. That many-to-many lives on graph edges, not here — on the instance we
keep `definition_ids` (usually one). Provenance is the instance's single source of
origin; reuse across OUTPUT documents is the graph's RENDERS edges.

A USDM-shaped SUBSET on purpose (six element types), named honestly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------
ComponentType = Literal["objective", "endpoint", "arm", "population", "eligibility", "visit"]
ObjectiveLevel = Literal["primary", "secondary", "exploratory"]
EndpointLevel = Literal["primary", "secondary", "exploratory", "safety"]
ArmType = Literal["experimental", "active_comparator", "placebo_comparator", "sham", "other"]
CriterionKind = Literal["inclusion", "exclusion"]


# ---------------------------------------------------------------------------
# Provenance — single source of origin for an instance's content
# ---------------------------------------------------------------------------
class Provenance(BaseModel):
    protocol_id: str
    page: Optional[int] = None
    section: Optional[str] = None
    quote: Optional[str] = None


# ---------------------------------------------------------------------------
# The six USDM-shaped element models (the instance's content payload)
# ---------------------------------------------------------------------------
class Objective(BaseModel):
    level: ObjectiveLevel
    text: str


class Endpoint(BaseModel):
    level: EndpointLevel
    text: str
    objective_ref: Optional[str] = None
    timeframe: Optional[str] = None


class Arm(BaseModel):
    name: str
    type: ArmType
    description: Optional[str] = None


class Population(BaseModel):
    description: str
    planned_enrollment: Optional[int] = None
    condition: Optional[str] = None


class EligibilityCriterion(BaseModel):
    kind: CriterionKind
    text: str
    number: Optional[str] = None


class Visit(BaseModel):
    name: str
    study_day: Optional[str] = None
    procedures: list[str] = Field(default_factory=list)


ElementData = Union[Objective, Endpoint, Arm, Population, EligibilityCriterion, Visit]

ELEMENT_MODELS: dict[str, type[BaseModel]] = {
    "objective": Objective, "endpoint": Endpoint, "arm": Arm,
    "population": Population, "eligibility": EligibilityCriterion, "visit": Visit,
}


# ---------------------------------------------------------------------------
# Study context
# ---------------------------------------------------------------------------
class Study(BaseModel):
    id: str                                 # e.g. "moderna_cove"
    drug: Optional[str] = None
    title: Optional[str] = None


# ---------------------------------------------------------------------------
# Definition — the content-less slot (the class)
# ---------------------------------------------------------------------------
class ComponentDefinition(BaseModel):
    id: str                                 # e.g. "def-primary-efficacy-objective"
    type: ComponentType
    name: str                               # canonical label, e.g. "Primary Efficacy Objective"
    level: Optional[str] = None             # expected level, if the standard fixes one
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Instance — a definition hydrated with content for one study (the object)
# ---------------------------------------------------------------------------
class ComponentInstance(BaseModel):
    id: str                                 # stable id, e.g. "moderna_cove:end-001"
    type: ComponentType
    data: ElementData                       # the content
    provenance: Provenance                  # single source of origin
    study_id: str                           # context (-> Study.id)
    definition_ids: list[str] = Field(default_factory=list)   # m:n link to definitions (usually 1)
    version: int = 1
    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="before")
    @classmethod
    def _coerce_data_by_type(cls, values):
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
# What the extractor returns for one study (a bag of instances).
# ---------------------------------------------------------------------------
class ExtractionResult(BaseModel):
    study_id: str
    instances: list[ComponentInstance] = Field(default_factory=list)

    def by_type(self, t: ComponentType) -> list[ComponentInstance]:
        return [i for i in self.instances if i.type == t]
