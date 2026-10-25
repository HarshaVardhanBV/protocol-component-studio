# Protocol Component Studio

**Write once, reuse everywhere — for clinical-trial documents.**

Extract study-design elements from a public trial protocol into one validated,
versioned, provenance-tagged component model; render the *same* components into
multiple regulatory documents; and when a component changes, show every document
section it affects.

> 🚧 **Status: Phase 1 complete (thin vertical thread).** Extract → store →
> render M11 + E3 → change-impact runs end-to-end for objectives + endpoints,
> verified offline. Two protocols are onboarded and cross-study component
> *definitions* are induced on top. The only step not yet exercised live is the
> write into Neo4j Aura (needs credentials). Streamlit UI and evals come next —
> see the roadmap.

## Why
This is the core idea behind modern structured authoring (and CDISC USDM): the
document is a *view* of structured knowledge, not the source of truth. Model the
knowledge once and you can render it many ways and trace any change across every
document — the governance problem that single-source authoring exists to solve.

## How it works
1. **Extract** (`src/extract.py`) — a protocol PDF → the study design as validated
   JSON (objectives, endpoints, …), each with page/section provenance. Per-element
   targeted prompts in Anthropic tool mode, not one giant prompt.
2. **Dedup** (`src/merge.py`) — collapse near-duplicate statements *within* a study.
   LLM semantic grouping by default; conservative fuzzy matching as an offline fallback.
3. **Classify into templates** (`src/classify.py`) — every instance is bound to a
   fixed, regulatory-grounded **`ComponentDefinition` template** keyed on
   *(type, role)* — `OBJ-PRIMARY`, `EP-SECONDARY`, etc. The library (`src/definitions.py`)
   is **fixed and authored, not induced**: onboarding any protocol in any indication
   mints zero new definitions and causes zero churn. This is the scalability decision —
   definitions are structural (disease-agnostic), and all drug/indication specificity
   lives on the instance.
4. **Store as a graph** (`src/graph.py`, Neo4j):
   - a **`ComponentInstance`** — a hydrated element for one study (the object), with
     provenance on an `EXTRACTED_FROM` edge to the source protocol;
   - a **`ComponentDefinition`** — the fixed template (the class), linked to instances
     by `INSTANTIATED_AS`, and itself connected to its regulatory basis: `GOVERNED_BY`
     → `Standard` (ICH M11 / E9(R1) / CDISC USDM), `HAS_RULE` → `ConformanceRule`,
     `EXPECTS_ATTRIBUTE` → `ExpectedAttribute` (the five ICH E9(R1) estimand attributes);
   - a **`Study`** context, tied to instances by `FOR`.
5. **Render** (`src/render.py`) — instances render into **M11**, **E3**, **SAP** and
   **ICF** documents, writing a `RENDERS` edge (with its `transform`) per placement. Each
   document is a registry of ordered section slots. Two mechanisms make the reuse real:
   - a derived **Synopsis** section *displays first but builds last* (topological build on
     `DEPENDS_ON`), summarising the primary objective/endpoint from its dependencies;
   - **reuse-with-transform** — the *same* instance renders verbatim into M11/E3, is
     *elaborated* into the SAP, and rewritten in *lay language* for the ICF. Non-verbatim
     outputs become `RenderedFragment` nodes carrying the transformed text and a review
     `status` (ICF lay text is `needs_review`), linked to the source instance by
     `HAS_FRAGMENT`. One component, four documents, four forms.
6. **Change impact** (`graph.instance_impact` / `definition_impact`) — edit one
   component and list every document section affected; at the *definition* level the
   impact spans every study that instantiates the template. *(The governance story.)*
7. **Evaluate** — hand-label 3–5 protocols and report field-level extraction accuracy.

> **Definitions are templates, not concepts.** An earlier design induced shared
> *clinical concepts* ("prevent COVID-19") across studies; it bound two drugs together
> but didn't scale — disease-specific, and re-clustered on every load. The shipped model
> makes definitions a fixed structural library (ICH role templates) classified into, so
> it scales to any indication. `src/induce.py` is retained as an offline *discovery* lens,
> not the runtime binder.

A document is modelled as a **registry of section slots** (`src/templates.py`), each
declaring which component types render into it and its display/derivation order — so a
shared component is what links two documents. Adding SAP/ICF/PBRER later is just another
registry, not a rewrite.

## Scope (named honestly)
A **USDM-shaped subset** — six element types — not the full CDISC USDM. The section
templates are indicative subsets of ICH M11 / E3, not authoritative reproductions.

## Layout
```
src/
  models.py      Pydantic contract — element models + the rich ComponentDefinition schema
  definitions.py the fixed, ICH-grounded template library (the governed definitions)
  extract.py     protocol PDF → objectives + endpoints (tool mode, provenance)
  merge.py       within-study dedup (LLM grouping; fuzzy fallback)
  classify.py    bind each instance to its (type, role) template — the runtime binder
  induce.py      cross-study concept induction — retained as an offline discovery lens
  render.py      place components into M11/E3/SAP/ICF slots → RENDERS (+transform), fragments, Synopsis
  templates.py   documents as registries of ordered section slots (M11, E3, SAP, ICF)
  graph.py       Neo4j schema + loader (definitions, standards, rules, attrs, docs) + impact queries
store/           per-study ExtractionResult JSON + definitions.json (template library)
data/            public protocol PDFs (see data/README.md)
.streamlit/      secrets.toml.example (Anthropic + Neo4j Aura)
```

## Run the pipeline
```bash
python -m src.extract --protocol-id moderna_cove "data/moderna_cove/<protocol>.pdf" --out store/moderna_cove.json
python -m src.classify --report   # bind instances to (type, role) templates → store/definitions.json
python -m src.graph --wipe        # load studies/definitions/instances + render M11/E3 into Aura
```
`extract` calls Anthropic; `classify` is deterministic (no API); `graph` writes to
Neo4j (needs `.streamlit/secrets.toml`). `--report` on `classify` shows per-template
counts; `--no-render` on `graph` loads components without documents.

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then fill in real values
```
Neo4j Aura (free): create an instance at https://neo4j.com/cloud/aura-free/ and paste the
URI / user / password into `.streamlit/secrets.toml`.

## Roadmap
- **Phase 0 ✅** — component contract, template registry, graph schema (scaffold).
- **Phase 1 ✅** — thin vertical slice: objectives + endpoints, extract → store →
  render M11 + E3 → change-impact, proven end-to-end (verified offline; loaded to Aura).
- **Phase 2 (in progress)** — multi-study + a governed template library:
  - ✅ second protocol onboarded; within-study dedup.
  - ✅ **template-only definitions** — fixed, ICH/E9(R1)/USDM-grounded `ComponentDefinition`
    schema (content form, estimand attributes, conformance rules, occurrence bounds,
    governance) classified into, projected to the graph as `Standard` / `ConformanceRule`
    / `ExpectedAttribute` hubs.
  - ✅ **derived Synopsis** — display-vs-build order, topological build on `DEPENDS_ON`.
  - ✅ **reuse-with-transform** — same instance → M11/E3 verbatim, SAP elaborated,
    ICF lay-language; `RENDERS.transform` + `RenderedFragment` nodes with review status.
  - remaining: split endpoint role vs purpose at extraction; the other four element
    types; component versioning.
- **Phase 3** — Streamlit UI (side-by-side docs + impact panel, demo mode).
- **Phase 4** — field-level extraction evals on a labelled set.
- **Phase 5** — deploy + write-up.

---
_Uses only public data. A demonstration, not a validated system; not for clinical or regulatory use._

Built by **Harsha Vardhan B V** · [LinkedIn](https://www.linkedin.com/in/harsha-vardhan-b-v)
