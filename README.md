# Protocol Component Studio

**Write once, reuse everywhere — for clinical-trial documents.**

Extract study-design elements from a public trial protocol into one validated,
versioned, provenance-tagged component model; render the *same* components into
multiple regulatory documents; and when a component changes, show every document
section it affects.

> **Status: end-to-end and interactive on real data.** Two public protocols are
> extracted into the component model (all six element types) and render into M11,
> E3, SAP, ICF and PBRER; selecting a component traces its change-impact across
> every document, with a scoped knowledge-graph view, provenance, conformance
> findings and version integrity. Ships as a **web app** (FastAPI + hand-built UI)
> that reads the stored components — no database or API key needed to *run* it.
> An **offline eval harness** (`evals/`) measures extraction accuracy against a
> hand-labeled gold set. Honest open items: finish one study's eligibility/visits
> re-extract (model recall gap on a dense table), label a gold set for a published
> accuracy number, and deploy. See the roadmap.

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
7. **Serve** (`server.py`, `web/index.html`, `app_data.py`) — a FastAPI app turns the
   rendered components into one JSON model (`/api/model`) that a self-contained HTML
   frontend reads: workspace → document (M11/E3/SAP/ICF/PBRER) → select a component →
   inspect provenance + trace change-impact (click to jump) + a scoped ego-graph view.
   Credential-free to run (reads `store/`); a Streamlit build (`app.py`) is kept as a
   fallback.
8. **Evaluate** (`evals/`) — field-level precision / recall / F1 per element type +
   role accuracy, scoring the stored predictions against a hand-labeled gold set.
   Fully offline (scoring costs nothing; only extraction spends API). `make_gold.py`
   bootstraps an editable gold template; a `verified` flag gates it so an unedited
   template can't masquerade as a real gold set.

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
templates are indicative subsets of ICH M11 / E3 / SAP / ICF / PBRER, not authoritative
reproductions — though M11 Section 3 does follow the authoritative role-based structure
(3.1 Primary / 3.2 Secondary / 3.3 Exploratory, each grouping objective + endpoint +
estimand). Each document shows an honest coverage line (how many sections are populated
from the component model vs. narrative-authored).

## Data & storage (what lives where)
- **Components (the data)** → `store/*.json` — the extracted, classified
  `ComponentInstance`s per study, plus `definitions.json` (the template library actually used).
- **Document templates (config)** → `src/document_templates/*.yaml` — assembly instructions, not data.
- **Neo4j** → optional. `graph.py` loads the same components into Aura for the cross-study
  graph story, but the app reads the JSON directly — the renderer is the single source of
  truth, so no database is required to run or demo.

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
app_data.py      pure data layer (load store → classify → render/impact/conformance); no Streamlit
server.py        FastAPI app: serves web/index.html + /api/model (live model from components)
web/index.html   self-contained frontend (workspace → doc → select → trace impact → graph view)
app.py           Streamlit build (fallback UI over the same data layer)
evals/           offline extraction eval — score.py (P/R/F1 + role accuracy), make_gold.py, gold/
store/           per-study ExtractionResult JSON + definitions.json (the data)
data/            public protocol PDFs (gitignored — fetch from ClinicalTrials.gov)
.streamlit/      secrets.toml.example + config.toml (Anthropic + Neo4j Aura)
```

## Run the app (no API key, no database)
```bash
uvicorn server:app --reload          # open http://127.0.0.1:8000
# or the Streamlit fallback:
streamlit run app.py
```
Both read the committed `store/*.json`, so the demo runs with zero credentials.

## Refresh the data (needs an Anthropic key; Neo4j optional)
```bash
export ANTHROPIC_API_KEY="sk-ant-..."        # extract reads this from the env
python -m src.extract "data/moderna_cove/<protocol>.pdf" --protocol-id moderna_cove --out store/moderna_cove.json
python -m src.classify --report              # bind instances to templates; writes definition_ids + store/definitions.json
python -m src.graph --wipe                   # optional: load components into Neo4j Aura
```
`extract` takes `pdf_path` as a positional arg and calls Anthropic (merge uses the LLM
grouper by default; `--local-merge` for offline fuzzy, `--no-merge` to skip). `classify`
is deterministic (no API). `graph` needs `NEO4J_*` in `.streamlit/secrets.toml`.

## Score extraction (offline, no API)
```bash
python -m evals.make_gold --study moderna_cove   # draft evals/gold/moderna_cove.template.json
# review against the protocol, set verified=true, save as evals/gold/moderna_cove.json
python -m evals.score --study moderna_cove --md  # P / R / F1 per element type + role accuracy
```

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
- **Phase 3 ✅** — interactive UI: FastAPI + self-contained HTML frontend (workspace →
  document → select component → change-impact with click-to-jump → scoped graph view →
  conformance + version panels). Streamlit build retained as a fallback.
- **Phase 4 (in progress)** — offline eval harness built (`evals/`: field-level P/R/F1 +
  role accuracy, gold bootstrap, verified-gate). Remaining: label a gold set and publish a
  scorecard (incl. KEYNOTE-189 for oncology recall — closes the WS-B accuracy caveat).
- **Phase 5** — deploy (`uvicorn` on any container host; no DB needed to read) + write-up.

### Known gaps (named honestly)
- One study's eligibility/visits came back empty from a dense table/SoA grid — a model
  recall miss (page-selection fix staged; needs one re-extract to confirm). The eval
  harness is designed to quantify exactly this.
- Store currently reflects pre-/partial-clean extraction, so the conformance panel shows
  real over-tagging — surfaced, not hidden.

---
_Uses only public data. A demonstration, not a validated system; not for clinical or regulatory use._

Built by **Harsha Vardhan B V** · [LinkedIn](https://www.linkedin.com/in/harsha-vardhan-b-v)
