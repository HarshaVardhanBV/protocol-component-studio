"""
definitions.py — the governed template library (the ComponentDefinition set).

A small, FIXED, regulatory-grounded set of structural templates. Authored here,
not induced; onboarding a new protocol/indication mints ZERO new templates.

Keyed on (component_type, discriminator):
  - objective / endpoint  -> role  (primary/secondary/exploratory)  [ICH M11 §3]
  - arm                   -> arm type  [CDISC Study Arm Type, NCI C174222]
  - eligibility           -> kind  (inclusion/exclusion)  [CDISC C66797]
  - population / visit     -> none (single template each)

Grounding (verified vs sources, Oct 2026):
  - ICH M11 (CeSHarP) §3 objectives/estimands; Trial Design (arms); Trial Population
    & Eligibility; Schedule of Activities.
  - ICH E9(R1) estimand (5 attributes).  ICH E3 CSR §9.x.
  - CDISC USDM classes: Objective (C188707), Endpoint (C188708), Estimand (C188719),
    StudyArm (type = C174222), EligibilityCriterion (category = C66797),
    StudyDesignPopulation, Encounter (Schedule of Activities).
"""
from __future__ import annotations

from datetime import date

from .models import ComponentDefinition, StandardRef, ExpectedAttribute, ConformanceRule

_M11_URL = "https://database.ich.org/sites/default/files/ICH_Step4_M11_Final_TechnicalSpecification_2025_1119.pdf"
_EFFECTIVE = date(2026, 10, 25)
_STEWARD = "Clinical Standards / Protocol Authoring"

# ---- key / prefix / labels -------------------------------------------------
_PREFIX = {"objective": "OBJ", "endpoint": "EP", "arm": "ARM",
           "eligibility": "ELIG", "population": "POP", "visit": "VISIT"}


def template_id(component_type: str, discriminator: str | None = None) -> str:
    p = _PREFIX.get(component_type, component_type[:3].upper())
    return f"{p}-{discriminator.upper()}" if discriminator else p


_ROLE_LABEL = {"primary": "Primary", "secondary": "Secondary", "exploratory": "Exploratory"}
_ARM_LABEL = {"experimental": "Experimental Arm", "active_comparator": "Active Comparator Arm",
              "placebo_comparator": "Placebo Comparator Arm", "sham_comparator": "Sham Comparator Arm",
              "no_intervention": "No Intervention Arm", "other": "Other Arm"}
_KIND_LABEL = {"inclusion": "Inclusion Criterion", "exclusion": "Exclusion Criterion"}

_M11_OBJ_SECTION = {"primary": "3.1 Primary Objective(s) and Associated Estimand(s)",
                    "secondary": "3.2 Secondary Objective(s) and Associated Estimand(s)",
                    "exploratory": "3.3 Exploratory Objective(s)"}


# ---- shared expected-attribute sets ----------------------------------------
def _estimand_attributes():
    e9 = StandardRef(framework="ICH E9(R1)", section="Addendum: the estimand framework")
    usdm = StandardRef(framework="CDISC USDM", identifier="Estimand (C188719)")
    return [
        ExpectedAttribute(name="treatment", label="Treatment condition", required=True, source=e9),
        ExpectedAttribute(name="population", label="Target population", required=True, source=e9),
        ExpectedAttribute(name="variable", label="Variable (endpoint measure)", required=True, source=e9),
        ExpectedAttribute(name="population_summary", label="Population-level summary", required=True, source=e9),
        ExpectedAttribute(name="intercurrent_events", label="Intercurrent-event strategy", required=True,
                          data_type="coded", cardinality="multiple",
                          controlled_terms=["treatment_policy", "composite", "while_on_treatment",
                                            "hypothetical", "principal_stratum"], source=e9),
        ExpectedAttribute(name="timeframe", label="Timeframe", required=False, source=usdm),
        ExpectedAttribute(name="purpose", label="Endpoint purpose", required=False, data_type="coded",
                          controlled_terms=["efficacy", "safety", "immunogenicity", "pharmacokinetic",
                                            "pharmacodynamic", "other"],
                          source=StandardRef(framework="CDISC USDM", identifier="Endpoint (C188708)")),
    ]


def _objective_attributes():
    m11 = StandardRef(framework="ICH M11", section="Section 3 — Trial Objectives and Associated Estimands", url=_M11_URL)
    return [
        ExpectedAttribute(name="clinical_question", label="Objective / clinical question", required=True, source=m11),
        ExpectedAttribute(name="associated_endpoints", label="Associated endpoint(s)", required=False,
                          data_type="coded", cardinality="multiple",
                          source=StandardRef(framework="ICH E9(R1)", section="Objective → estimand → endpoint linkage")),
    ]


# ---- builders --------------------------------------------------------------
def _objective(role):
    rules = [ConformanceRule(id="OBJ-EP-1", text="Each objective should have at least one associated endpoint.",
                             severity="warning", scope="associated_endpoints")]
    if role == "primary":
        rules.insert(0, ConformanceRule(id="OBJ-PRIMARY-1", text="A trial must define at least one primary objective.",
                                        severity="error", scope="cardinality"))
    return ComponentDefinition(
        id=template_id("objective", role), type="objective", role=role,
        name=f"{_ROLE_LABEL[role]} Objective", label=f"{_ROLE_LABEL[role]} Objective",
        description=f"A {role} trial objective (ICH M11 §3).",
        standards=[StandardRef(framework="ICH M11", section=_M11_OBJ_SECTION[role], url=_M11_URL),
                   StandardRef(framework="CDISC USDM", identifier="Objective (C188707)"),
                   StandardRef(framework="ICH E8(R1)", section="General considerations — trial objectives")],
        content_form="prose", expected_attributes=_objective_attributes(),
        renders_into=["M11-OBJ", "E3-9.2"], allowed_documents=["M11", "E3", "SAP"],
        min_occurs=(1 if role == "primary" else 0), max_occurs=None,
        conformance_rules=rules, status="approved", version=1, effective_date=_EFFECTIVE, steward=_STEWARD)


def _endpoint(role):
    rules = [ConformanceRule(id="EP-REF-1", text="Each endpoint must reference the objective it supports.",
                             severity="error", scope="objective_ref")]
    if role == "primary":
        rules.append(ConformanceRule(id="EP-EST-1", text="A primary endpoint must specify its estimand attributes.",
                                     severity="warning", scope="estimand"))
    return ComponentDefinition(
        id=template_id("endpoint", role), type="endpoint", role=role,
        name=f"{_ROLE_LABEL[role]} Endpoint", label=f"{_ROLE_LABEL[role]} Endpoint",
        description=f"A {role} endpoint (ICH E9(R1); ICH M11 §3).",
        standards=[StandardRef(framework="ICH M11", section="Section 3 — Associated Estimand(s)", url=_M11_URL),
                   StandardRef(framework="ICH E9(R1)", section="Addendum: the estimand framework"),
                   StandardRef(framework="CDISC USDM", identifier="Endpoint (C188708)")],
        content_form="prose", expected_attributes=_estimand_attributes(),
        renders_into=["M11-OBJ", "E3-9.5"], allowed_documents=["M11", "E3", "SAP"],
        min_occurs=(1 if role == "primary" else 0), max_occurs=None,
        conformance_rules=rules, status="approved", version=1, effective_date=_EFFECTIVE, steward=_STEWARD)


def _arm(arm_type):
    attrs = [
        ExpectedAttribute(name="name", label="Arm name", required=True,
                          source=StandardRef(framework="CDISC USDM", identifier="StudyArm")),
        ExpectedAttribute(name="type", label="Arm type", required=True, data_type="coded",
                          controlled_terms=list(_ARM_LABEL.keys()),
                          source=StandardRef(framework="CDISC USDM", identifier="Study Arm Type (C174222)")),
        ExpectedAttribute(name="intervention", label="Intervention / treatment", required=False,
                          source=StandardRef(framework="CDISC USDM", identifier="StudyIntervention")),
        ExpectedAttribute(name="description", label="Description", required=False),
    ]
    rules = []
    if arm_type == "experimental":
        rules.append(ConformanceRule(id="ARM-EXP-1", text="A trial must define at least one experimental arm.",
                                     severity="error", scope="cardinality"))
    return ComponentDefinition(
        id=template_id("arm", arm_type), type="arm", role=None,
        name=_ARM_LABEL[arm_type], label=_ARM_LABEL[arm_type],
        description=f"A study arm of type '{arm_type}' (CDISC Study Arm Type, C174222; ICH M11 Trial Design).",
        standards=[StandardRef(framework="ICH M11", section="Trial Design — Arms", url=_M11_URL),
                   StandardRef(framework="CDISC USDM", identifier="StudyArm; type = Study Arm Type (C174222)"),
                   StandardRef(framework="ICH E3", section="9.3 Overall Study Design and Plan")],
        content_form="prose", expected_attributes=attrs,
        renders_into=["M11-DESIGN", "E3-9.3"], allowed_documents=["M11", "E3"],
        min_occurs=(1 if arm_type == "experimental" else 0), max_occurs=None,
        conformance_rules=rules, status="approved", version=1, effective_date=_EFFECTIVE, steward=_STEWARD)


def _eligibility(kind):
    attrs = [
        ExpectedAttribute(name="text", label="Criterion", required=True,
                          source=StandardRef(framework="CDISC USDM", identifier="EligibilityCriterion")),
        ExpectedAttribute(name="kind", label="Inclusion/Exclusion", required=True, data_type="coded",
                          controlled_terms=["inclusion", "exclusion"],
                          source=StandardRef(framework="CDISC USDM", identifier="I/E category (C66797)")),
        ExpectedAttribute(name="number", label="Criterion number", required=False),
    ]
    rules = []
    if kind == "inclusion":
        rules.append(ConformanceRule(id="ELIG-INC-1", text="A trial must define at least one inclusion criterion.",
                                     severity="error", scope="cardinality"))
    return ComponentDefinition(
        id=template_id("eligibility", kind), type="eligibility", role=None,
        name=_KIND_LABEL[kind], label=_KIND_LABEL[kind],
        description=f"An {kind} eligibility criterion (CDISC EligibilityCriterion; category C66797; ICH M11 Trial Population).",
        standards=[StandardRef(framework="ICH M11", section="Trial Population — Eligibility Criteria", url=_M11_URL),
                   StandardRef(framework="CDISC USDM", identifier="EligibilityCriterion; category (C66797)"),
                   StandardRef(framework="ICH E3", section="9.4 Selection of Study Population")],
        content_form="list", expected_attributes=attrs,
        renders_into=["M11-POP", "E3-9.4"], allowed_documents=["M11", "E3", "ICF"],
        min_occurs=(1 if kind == "inclusion" else 0), max_occurs=None,
        conformance_rules=rules, status="approved", version=1, effective_date=_EFFECTIVE, steward=_STEWARD)


def _population():
    attrs = [
        ExpectedAttribute(name="description", label="Population description", required=True,
                          source=StandardRef(framework="CDISC USDM", identifier="StudyDesignPopulation")),
        ExpectedAttribute(name="condition", label="Condition / indication", required=False),
        ExpectedAttribute(name="planned_enrollment", label="Planned enrollment", required=False, data_type="integer"),
    ]
    return ComponentDefinition(
        id=template_id("population"), type="population", role=None,
        name="Study Population", label="Study Population",
        description="The trial's target population (CDISC StudyDesignPopulation; ICH M11 Trial Population).",
        standards=[StandardRef(framework="ICH M11", section="Trial Population", url=_M11_URL),
                   StandardRef(framework="CDISC USDM", identifier="StudyDesignPopulation"),
                   StandardRef(framework="ICH E3", section="9.4 Selection of Study Population")],
        content_form="prose", expected_attributes=attrs,
        renders_into=["M11-POP", "E3-9.4"], allowed_documents=["M11", "E3", "ICF"],
        min_occurs=1, max_occurs=1, cardinality="Exactly one study population per design.",
        conformance_rules=[ConformanceRule(id="POP-1", text="A study design has exactly one study population.",
                                           severity="warning", scope="cardinality")],
        status="approved", version=1, effective_date=_EFFECTIVE, steward=_STEWARD)


def _visit():
    attrs = [
        ExpectedAttribute(name="name", label="Visit / encounter name", required=True,
                          source=StandardRef(framework="CDISC USDM", identifier="Encounter")),
        ExpectedAttribute(name="study_day", label="Timing (study day/window)", required=False),
        ExpectedAttribute(name="procedures", label="Procedures / activities", required=False,
                          cardinality="multiple",
                          source=StandardRef(framework="CDISC USDM", identifier="Activity / Procedure")),
    ]
    return ComponentDefinition(
        id=template_id("visit"), type="visit", role=None,
        name="Visit (Encounter)", label="Visit (Encounter)",
        description="A scheduled visit/encounter in the Schedule of Activities (CDISC Encounter; ICH M11 SoA).",
        standards=[StandardRef(framework="ICH M11", section="Schedule of Activities", url=_M11_URL),
                   StandardRef(framework="CDISC USDM", identifier="Encounter / ScheduleOfActivities"),
                   StandardRef(framework="ICH E3", section="9.5.1 Schedule of Assessments")],
        content_form="table", expected_attributes=attrs,
        renders_into=["M11-SOA", "E3-9.5.1"], allowed_documents=["M11", "E3"],
        min_occurs=0, max_occurs=None,
        status="approved", version=1, effective_date=_EFFECTIVE, steward=_STEWARD)


ROLES = ["primary", "secondary", "exploratory"]
ARM_TYPES = list(_ARM_LABEL.keys())
KINDS = ["inclusion", "exclusion"]

LIBRARY = (
    [_objective(r) for r in ROLES]
    + [_endpoint(r) for r in ROLES]
    + [_arm(a) for a in ARM_TYPES]
    + [_eligibility(k) for k in KINDS]
    + [_population(), _visit()]
)
LIBRARY_BY_ID = {d.id: d for d in LIBRARY}


def library():
    return [d.model_copy(deep=True) for d in LIBRARY]
