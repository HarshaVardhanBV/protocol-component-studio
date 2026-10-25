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

from datetime import datetime, timezone, date
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------
ComponentType = Literal["objective", "endpoint", "arm", "population", "eligibility", "visit"]
ObjectiveLevel = Literal["primary", "secondary", "exploratory"]
EndpointLevel = Literal["primary", "secondary", "exploratory", "safety"]
# Arm type — CDISC "Study Arm Type" value set (NCI C174222), machine form.
ArmType = Literal["experimental", "active_comparator", "placebo_comparator",
                  "sham_comparator", "no_intervention", "other"]
# Eligibility criterion kind — CDISC Inclusion/Exclusion category (NCI C66797).
CriterionKind = Literal["inclusion", "exclusion"]

# Role = the ICH M11 §3 / CDISC objective-&-endpoint "level" classification. This is
# the structural axis the template library is keyed on (primary/secondary/exploratory)
# — disease-agnostic, so adding a role-typed template never ties the library to an
# indication. ICH/CDISC use "exploratory"; sponsors who say "tertiary" map there.
ComponentRole = Literal["primary", "secondary", "exploratory"]

# Purpose = an ORTHOGONAL axis describing what an endpoint measures. It is a content
# attribute of the instance, NOT part of the template identity (a "Primary Endpoint"
# template covers efficacy and safety alike). Kept separate on purpose: role answers
# "how important", purpose answers "what kind".
EndpointPurpose = Literal["efficacy", "safety", "immunogenicity",
                          "pharmacokinetic", "pharmacodynamic", "other"]

# ICH E9(R1) intercurrent-event handling strategies (for the estimand attribute).
IntercurrentStrategy = Literal["treatment_policy", "composite", "while_on_treatment",
                               "hypothetical", "principal_stratum"]

# How a component renders — its content modality. On a definition this is the
# EXPECTED form; a render may override it. (Objective = prose; schedule = table.)
ContentForm = Literal["prose", "list", "table", "figure", "structured"]

# Value type of an expected attribute, so guardrails are machine-checkable.
AttributeDataType = Literal["string", "integer", "number", "boolean", "coded", "date"]
AttributeCardinality = Literal["single", "multiple"]

# Governance lifecycle of a template (it is a managed asset, not a byproduct).
DefinitionStatus = Literal["draft", "approved", "retired"]

# Severity of a conformance rule (CDISC CORE-style).
RuleSeverity = Literal["error", "warning", "info"]

# Document types a component may be scoped to / render into.
DocumentType = Literal["M11", "E3", "SAP", "ICF", "PBRER"]

# How a component instance is transformed when rendered into a section. "verbatim"
# places it unchanged; the rest derive new text from the same source instance, so
# the SAME component reused across M11 / SAP / ICF differs only by its transform.
TransformKind = Literal["verbatim", "summarize", "lay_language",
                        "elaborate", "tabulate", "translate"]

# Review state of a transformed fragment (lay-language ICF text must be reviewed).
FragmentStatus = Literal["draft", "needs_review", "reviewed", "approved"]


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
    role: ComponentRole                     # primary/secondary/exploratory (was `level`)
    text: str

    @model_validator(mode="before")
    @classmethod
    def _compat_level(cls, v):
        # Back-compat: legacy records used `level`; map it to `role`.
        if isinstance(v, dict) and v.get("role") is None and v.get("level") is not None:
            v = {**v, "role": v["level"]}
            v.pop("level", None)
        return v


class Endpoint(BaseModel):
    # Role (importance) and purpose (what it measures) are ORTHOGONAL axes. Legacy
    # records folded both into `level` (incl. "safety"); the validator below splits them.
    role: Optional[ComponentRole] = None
    purpose: Optional[EndpointPurpose] = None
    text: str
    objective_ref: Optional[str] = None
    timeframe: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _compat_level(cls, v):
        if isinstance(v, dict) and v.get("role") is None and v.get("level") is not None:
            v = {**v}
            lvl = v.pop("level")
            if lvl in ("primary", "secondary", "exploratory"):
                v["role"] = lvl
            elif lvl == "safety":                 # a purpose leaked into level
                v.setdefault("purpose", "safety")  # role unknown until re-extraction
        return v


class Arm(BaseModel):
    name: str
    type: ArmType
    description: Optional[str] = None
    intervention: Optional[str] = None


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


def component_text(data) -> str:
    """The comparable/display text of any element payload. Not all have `.text`:
    arms/visits use `name`, population uses `description`."""
    for attr in ("text", "name", "description"):
        v = getattr(data, attr, None)
        if v:
            return v
    return ""


# ---------------------------------------------------------------------------
# Study context
# ---------------------------------------------------------------------------
class Study(BaseModel):
    id: str                                 # e.g. "moderna_cove"
    drug: Optional[str] = None
    title: Optional[str] = None


# ---------------------------------------------------------------------------
# Definition — the content-less template (the class).
#
# A ComponentDefinition is a STRUCTURAL template drawn from the regulatory
# standard, not a clinical concept. It is content-free, disease-agnostic and
# fixed: the library is a small bounded set keyed on (type, role), so onboarding
# any protocol in any indication mints zero new definitions.
#
# Each definition carries three kinds of structured metadata captured from the
# sources:
#   - standards[]          — the authority that defines this template
#                            (ICH M11 section, ICH E9(R1), CDISC USDM class + CT).
#   - expected_attributes[] — the fields an INSTANCE of this template is expected
#                            to carry (for endpoints, the five ICH E9(R1) estimand
#                            attributes; for objectives, the clinical question).
#   - renders_into[]       — the document section slots (M11/E3) it feeds.
# ---------------------------------------------------------------------------
class StandardRef(BaseModel):
    """A citation to the regulatory/standards authority a template derives from."""
    framework: str                          # "ICH M11", "ICH E9(R1)", "CDISC USDM", "ICH E8(R1)"
    section: Optional[str] = None           # e.g. "3.1 Primary Objective(s) and Associated Estimand(s)"
    identifier: Optional[str] = None        # USDM class ("Objective") or NCI CT code ("C188707")
    version: Optional[str] = None
    url: Optional[str] = None


class ExpectedAttribute(BaseModel):
    """A field an instance of this template is expected to carry — the structured
    shape the standard mandates (e.g. the estimand attributes for an endpoint)."""
    name: str                               # machine name, e.g. "intercurrent_events"
    label: str                              # display, e.g. "Intercurrent-event strategy"
    required: bool = False
    data_type: AttributeDataType = "string"
    cardinality: AttributeCardinality = "single"
    description: Optional[str] = None
    controlled_terms: list[str] = Field(default_factory=list)  # allowed values, if any
    codelist: Optional[str] = None          # CT codelist ref (e.g. NCI C-code) if coded
    source: Optional[StandardRef] = None    # which standard mandates this attribute


class ConformanceRule(BaseModel):
    """A CDISC CORE-style business rule the standard imposes on instances of this
    template — a checkable guardrail, not just prose."""
    id: str                                 # e.g. "EP-REF-1"
    text: str                               # human statement of the rule
    severity: RuleSeverity = "error"
    scope: Optional[str] = None             # what it constrains, e.g. "objective_ref"


class ComponentDefinition(BaseModel):
    # --- identity & classification ---
    id: str                                 # stable template id, e.g. "OBJ-PRIMARY"
    type: ComponentType                     # structural kind (objective/endpoint/...)
    role: Optional[ComponentRole] = None    # primary/secondary/exploratory (None if role-less)
    name: str                               # canonical label, e.g. "Primary Objective"
    label: Optional[str] = None             # short display label
    description: Optional[str] = None       # the regulatory definition of this template

    # --- regulatory basis (the definition's own provenance) ---
    standards: list[StandardRef] = Field(default_factory=list)

    # --- content shape ---
    content_form: ContentForm = "prose"     # expected rendering modality
    expected_attributes: list[ExpectedAttribute] = Field(default_factory=list)

    # --- document placement & scope ---
    renders_into: list[str] = Field(default_factory=list)      # section slot ids (templates.py)
    allowed_documents: list[DocumentType] = Field(default_factory=list)  # where it MAY appear

    # --- guardrails / conformance ---
    min_occurs: int = 0                     # structured cardinality bounds per document
    max_occurs: Optional[int] = None        # None = unbounded
    cardinality: Optional[str] = None       # human-readable guidance (optional)
    conformance_rules: list[ConformanceRule] = Field(default_factory=list)

    # --- governance / lifecycle ---
    status: DefinitionStatus = "approved"
    version: int = 1
    effective_date: Optional[date] = None
    retired_date: Optional[date] = None
    steward: Optional[str] = None           # owning function/role
    change_note: Optional[str] = None
    notes: Optional[str] = None

    # Back-compat: older code and the graph loader read `.level`; it mirrors `role`.
    @property
    def level(self) -> Optional[str]:
        return self.role


# ---------------------------------------------------------------------------
# Revision — an immutable, hash-stamped snapshot of a SUPERSEDED instance state.
# History lives as a property list on the instance (not as graph nodes): a revision
# describes one instance's own past, it is neither shared nor traversed.
# ---------------------------------------------------------------------------
class Revision(BaseModel):
    version: int                            # the version number this snapshot represents (the prior state)
    data: dict                              # frozen copy of the superseded element payload
    superseded_at: datetime                 # when this state was replaced
    superseded_by: str                      # who made the edit that replaced it (governance: never empty)
    change_note: str                        # why (governance: never empty)
    hash: str                               # sha256 of the canonical prior payload — tamper evidence


# ---------------------------------------------------------------------------
# Instance — a definition hydrated with content for one study (the object)
# ---------------------------------------------------------------------------
class ComponentInstance(BaseModel):
    id: str                                 # stable id, e.g. "moderna_cove:end-001"
    type: ComponentType
    data: ElementData                       # the content (current version)
    provenance: Provenance                  # single source of ORIGIN (extraction) — preserved across edits
    study_id: str                           # context (-> Study.id)
    definition_ids: list[str] = Field(default_factory=list)   # m:n link to definitions (usually 1)
    version: int = 1                        # current version; v1 = as-extracted
    # --- revision provenance (the LATEST edit); distinct from extraction provenance ---
    revised_at: Optional[datetime] = None
    revised_by: Optional[str] = None
    change_note: Optional[str] = None
    history: list[Revision] = Field(default_factory=list)      # append-only; len == version - 1
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
