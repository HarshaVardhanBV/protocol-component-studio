"""
definitions.py — the governed template library (the ComponentDefinition set).

A small, FIXED, regulatory-grounded set of structural templates, keyed on
(component_type, role). It is authored here, not induced from data, so onboarding
any protocol in any indication adds zero definitions and causes zero churn.

Grounding (verified against the sources, Oct 2026):
  - ICH M11 (CeSHarP), Section 3 "Trial Objectives and Associated Estimands":
      3.1 Primary Objective(s) and Associated Estimand(s)
      3.2 Secondary Objective(s) and Associated Estimand(s)
      3.3 Exploratory Objective(s)
    https://database.ich.org/sites/default/files/ICH_Step4_M11_Final_TechnicalSpecification_2025_1119.pdf
  - ICH E9(R1) Addendum — an estimand has FIVE attributes: treatment, population,
    variable (endpoint), population-level summary, intercurrent-event strategy;
    with five IE strategies (treatment-policy, composite, while-on-treatment,
    hypothetical, principal-stratum).
  - CDISC USDM — Objective / Endpoint / Estimand classes; DDF controlled
    terminology value sets: Objective Attribute C188707, Endpoint Attribute
    C188708, Estimand Attribute C188719.

Scope note: role is primary/secondary/exploratory (ICH/CDISC vocabulary — no
"tertiary"). Endpoint *purpose* (efficacy/safety/immunogenicity/PK/PD) is an
orthogonal content attribute of the instance, not a separate template.
"""
from __future__ import annotations

from datetime import date

from .models import (
    ComponentDefinition, StandardRef, ExpectedAttribute, ConformanceRule, ComponentRole,
)

_EFFECTIVE = date(2026, 10, 25)
_STEWARD = "Clinical Standards / Protocol Authoring"

# Structured occurrence bounds per (type, role): (min_occurs, max_occurs).
_OCCURS = {
    ("objective", "primary"): (1, None),
    ("objective", "secondary"): (0, None),
    ("objective", "exploratory"): (0, None),
    ("endpoint", "primary"): (1, None),
    ("endpoint", "secondary"): (0, None),
    ("endpoint", "exploratory"): (0, None),
}

_M11_URL = "https://database.ich.org/sites/default/files/ICH_Step4_M11_Final_TechnicalSpecification_2025_1119.pdf"

_M11_SECTION = {
    "objective": {"primary": "3.1 Primary Objective(s) and Associated Estimand(s)",
                  "secondary": "3.2 Secondary Objective(s) and Associated Estimand(s)",
                  "exploratory": "3.3 Exploratory Objective(s)"},
}

_ROLE_LABEL = {"primary": "Primary", "secondary": "Secondary", "exploratory": "Exploratory"}

_CARDINALITY = {
    ("objective", "primary"): "One or more; a trial typically has a single primary objective.",
    ("objective", "secondary"): "Zero or more.",
    ("objective", "exploratory"): "Zero or more.",
    ("endpoint", "primary"): "One or more; aligned to the primary objective's estimand.",
    ("endpoint", "secondary"): "Zero or more.",
    ("endpoint", "exploratory"): "Zero or more.",
}


def template_id(component_type: str, role: str) -> str:
    prefix = {"objective": "OBJ", "endpoint": "EP"}.get(component_type, component_type[:3].upper())
    return f"{prefix}-{role.upper()}"


# ---- the five ICH E9(R1) estimand attributes, reused by every endpoint template ----
def _estimand_attributes() -> list[ExpectedAttribute]:
    e9 = StandardRef(framework="ICH E9(R1)", section="Addendum: the estimand framework")
    usdm = StandardRef(framework="CDISC USDM", identifier="Estimand (C188719)")
    return [
        ExpectedAttribute(name="treatment", label="Treatment condition", required=True,
                          description="The treatment(s) and comparator of interest, incl. regimen detail.",
                          source=e9),
        ExpectedAttribute(name="population", label="Target population", required=True,
                          description="The patients targeted by the clinical question (usually the trial I/E).",
                          source=e9),
        ExpectedAttribute(name="variable", label="Variable (endpoint measure)", required=True,
                          description="The outcome measured per participant, how and at what timepoint.",
                          source=e9),
        ExpectedAttribute(name="population_summary", label="Population-level summary", required=True,
                          description="Measure comparing conditions across the population "
                                      "(e.g. risk difference, hazard ratio, difference in means).",
                          source=e9),
        ExpectedAttribute(name="intercurrent_events", label="Intercurrent-event strategy", required=True,
                          data_type="coded", cardinality="multiple",
                          description="Pre-specified strategy for post-treatment events affecting the variable.",
                          controlled_terms=["treatment_policy", "composite", "while_on_treatment",
                                            "hypothetical", "principal_stratum"],
                          source=e9),
        ExpectedAttribute(name="timeframe", label="Timeframe", required=False,
                          description="Timing/window over which the endpoint is assessed.",
                          source=usdm),
        ExpectedAttribute(name="purpose", label="Endpoint purpose", required=False,
                          data_type="coded",
                          description="Orthogonal category of what the endpoint measures.",
                          controlled_terms=["efficacy", "safety", "immunogenicity",
                                            "pharmacokinetic", "pharmacodynamic", "other"],
                          source=StandardRef(framework="CDISC USDM", identifier="Endpoint (C188708)")),
    ]


def _objective_attributes() -> list[ExpectedAttribute]:
    m11 = StandardRef(framework="ICH M11", section="Section 3 — Trial Objectives and Associated Estimands",
                      url=_M11_URL)
    usdm = StandardRef(framework="CDISC USDM", identifier="Objective (C188707)")
    return [
        ExpectedAttribute(name="clinical_question", label="Objective / clinical question", required=True,
                          description="The objective stated as a precise question of interest.",
                          source=m11),
        ExpectedAttribute(name="associated_endpoints", label="Associated endpoint(s)", required=False,
                          data_type="coded", cardinality="multiple",
                          description="Endpoint(s) (via estimand) that operationalise this objective.",
                          source=StandardRef(framework="ICH E9(R1)",
                                             section="Objective → estimand → endpoint linkage")),
    ]


def _objective(role: ComponentRole) -> ComponentDefinition:
    mn, mx = _OCCURS[("objective", role)]
    rules = []
    if role == "primary":
        rules.append(ConformanceRule(
            id="OBJ-PRIMARY-1", text="A trial must define at least one primary objective.",
            severity="error", scope="cardinality"))
    rules.append(ConformanceRule(
        id="OBJ-EP-1", text="Each objective should have at least one associated endpoint.",
        severity="warning", scope="associated_endpoints"))
    return ComponentDefinition(
        id=template_id("objective", role), type="objective", role=role,
        name=f"{_ROLE_LABEL[role]} Objective", label=f"{_ROLE_LABEL[role]} Objective",
        description=f"A {role} trial objective: a precise question of interest the trial is "
                    f"designed to answer, paired with an associated estimand (ICH M11 §3).",
        standards=[
            StandardRef(framework="ICH M11", section=_M11_SECTION["objective"][role], url=_M11_URL),
            StandardRef(framework="CDISC USDM", identifier="Objective (C188707)"),
            StandardRef(framework="ICH E8(R1)", section="General considerations — trial objectives"),
        ],
        content_form="prose",
        expected_attributes=_objective_attributes(),
        renders_into=["M11-OBJ", "E3-9.2"],
        allowed_documents=["M11", "E3", "SAP"],
        min_occurs=mn, max_occurs=mx, cardinality=_CARDINALITY[("objective", role)],
        conformance_rules=rules,
        status="approved", version=1, effective_date=_EFFECTIVE, steward=_STEWARD,
    )


def _endpoint(role: ComponentRole) -> ComponentDefinition:
    mn, mx = _OCCURS[("endpoint", role)]
    rules = [
        ConformanceRule(id="EP-REF-1",
                        text="Each endpoint must reference the objective it supports.",
                        severity="error", scope="objective_ref"),
    ]
    if role == "primary":
        rules.append(ConformanceRule(
            id="EP-EST-1",
            text="A primary endpoint must specify its estimand attributes (treatment, "
                 "population, variable, population-level summary, intercurrent events).",
            severity="warning", scope="estimand"))
    return ComponentDefinition(
        id=template_id("endpoint", role), type="endpoint", role=role,
        name=f"{_ROLE_LABEL[role]} Endpoint", label=f"{_ROLE_LABEL[role]} Endpoint",
        description=f"A {role} endpoint: the variable within the associated estimand that "
                    f"operationalises a {role} objective (ICH E9(R1); ICH M11 §3).",
        standards=[
            StandardRef(framework="ICH M11", section="Section 3 — Associated Estimand(s)", url=_M11_URL),
            StandardRef(framework="ICH E9(R1)", section="Addendum: the estimand framework"),
            StandardRef(framework="CDISC USDM", identifier="Endpoint (C188708)"),
        ],
        content_form="prose",
        expected_attributes=_estimand_attributes(),
        renders_into=["M11-OBJ", "E3-9.5"],
        allowed_documents=["M11", "E3", "SAP"],
        min_occurs=mn, max_occurs=mx, cardinality=_CARDINALITY[("endpoint", role)],
        conformance_rules=rules,
        status="approved", version=1, effective_date=_EFFECTIVE, steward=_STEWARD,
    )


ROLES: list[ComponentRole] = ["primary", "secondary", "exploratory"]

LIBRARY: list[ComponentDefinition] = (
    [_objective(r) for r in ROLES] + [_endpoint(r) for r in ROLES]
)

LIBRARY_BY_ID: dict[str, ComponentDefinition] = {d.id: d for d in LIBRARY}


def library() -> list[ComponentDefinition]:
    """The complete fixed template library (fresh copies)."""
    return [d.model_copy(deep=True) for d in LIBRARY]
