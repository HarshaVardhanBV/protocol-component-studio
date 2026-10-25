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
   *(type, discriminator)*: role for objectives/endpoints (`OBJ-PRIMARY`, `EP-SECONDARY`),
   arm type for arms (`ARM-EXPERIMENTAL`, CDISC C174222), inclusion/exclusion for
   eligibility, and a single template for population/visit. The library (`src/definitions.py`)
   is **fixed and authored, not induced**: onboarding any protocol in any indication
   mints zero new definitions and causes zero churn. This is the scalability decision —
   definitions are structural (disease-agnostic), and all drug/indication specificity
   lives on the instance.
4. **Store as a graph** (`src/graph.py`, Neo4j) — the component knowledge base, kept
   deliberately small: **four node types** (`Study`, `ComponentDefinition`,
   `ComponentInstance`, `SourceProtocol`) and **three edges** (`INSTANTIATED_AS`
   definition→instance — the cross-study reuse spine; `FOR` instance→study;
   `EXTRACTED_FROM` instance→source — provenance). A `ComponentDefinition` is
   *self-describing*: its regulatory basis, conformance rules, and expected estimand
   attributes are **list properties on the node** (full detail in `definitions.json`),
   not satellite nodes — a thing that only describes one definition is a property, not
   a node.
5. **Assemble + render** (`src/document_templates/*.yaml`, `src/templates.py`, `src/render.py`) —
   assembly instructions are **declarative YAML, one file per document type** (M11/E3/SAP/ICF):
   ordered sections, which component types each accepts, display order, derivation, transform.
   This is *configuration, not graph data* — the graph holds only components. Documents and
   change-impact are **computed** from components + these templates. Adding a document type =
   adding a YAML file. Two mechanisms make reuse real:
   - a derived **Synopsis** section *displays first but builds last* (topological build on its
     `depends_on`), summarising the primary objective/endpoint from its dependencies;
   - **reuse-with-transform** — the *same* instance is rendered verbatim into M11/E3,
     *elaborated* into the SAP, and *lay-language* into the ICF (review status `needs_review`
     on participant-facing text). One component, four documents, four forms.
6. **Change impact** (`render.instance_impact` / `render.definition_impact`) — computed from
   components + templates (the renderer is the single source of truth, so impact can't drift
   from what actually renders). Edit one component → every `(study, document, section)` it
   reaches; at the definition level, across every study that instantiates the template.
   *(The governance story.)*
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
  render.py      compute rendered view + computed change-impact (instance_impact / definition_impact)
  templates.py   load assembly instructions from YAML into section slots
  document_templates/  one YAML per document type (m11, e3, sap, icf) — assembly config
  graph.py       Neo4j = component knowledge base only (4 node types, 3 edges)
  conformance.py governance check: cardinality + plausibility + bleed + version integrity
  revise.py      component versioning: guarded edits + append-only hashed history
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
- **Phase 2 (in progress)** — multi-study + all six element types + a governed library:
  - ✅ **WS-A: all six element types** — objectives, endpoints, arms (per CDISC Arm Type
    C174222), eligibility (inclusion/exclusion), population, visits; classifier generalized
    to (type, discriminator); extraction prompts for each; renders into the existing M11/E3
    slots. A new **document type is onboarded by dropping a YAML** (`document_templates/`),
    no code change — proven.
  - ✅ second protocol onboarded; within-study dedup.
  - ✅ **template-only definitions** — fixed, ICH/E9(R1)/USDM-grounded `ComponentDefinition`
    schema (content form, estimand attributes, conformance rules, occurrence bounds,
    governance) classified into, projected to the graph as `Standard` / `ConformanceRule`
    / `ExpectedAttribute` hubs.
  - ✅ **derived Synopsis** — display-vs-build order, topological build on `DEPENDS_ON`.
  - ✅ **reuse-with-transform** — same instance → M11/E3 verbatim, SAP elaborated,
    ICF lay-language; `RENDERS.transform` + `RenderedFragment` nodes with review status.
  - ✅ **WS-C: component versioning** — `revise()` mints version N+1, freezing the prior
    state into an append-only, hash-stamped `history` (a *property*, not graph nodes).
    Governance guardrails: attribution + justification required, no-op rejected, payload
    re-validated, monotonic version, extraction provenance preserved; `verify_history()`
    + a conformance `version.integrity` check make tampering detectable.
  - remaining: none in Phase 2 scope.
- **Phase 3** — Streamlit UI (side-by-side docs + impact panel, demo mode).
- **Phase 4** — field-level extraction evals on a labelled set.
- **Phase 5** — deploy + write-up.

---
_Uses only public data. A demonstration, not a validated system; not for clinical or regulatory use._

Built by **Harsha Vardhan B V** · [LinkedIn](https://www.linkedin.com/in/harsha-vardhan-b-v)
