# Protocol Component Studio

**Write once, reuse everywhere — for clinical-trial documents.**

Extract study-design elements from a public trial protocol into one validated,
versioned, provenance-tagged component model; render the *same* components into
multiple regulatory documents; and when a component changes, show every document
section it affects.

> 🚧 **Status: Phase 0 (scaffold).** The component contract, document registry,
> and graph schema are in place. Extraction, rendering, change-impact UI, and
> evaluation come next — see the roadmap below.

## Why
This is the core idea behind modern structured authoring (and CDISC USDM): the
document is a *view* of structured knowledge, not the source of truth. Model the
knowledge once and you can render it many ways and trace any change across every
document — the governance problem that single-source authoring exists to solve.

## How it works
1. **Extract** — a protocol PDF → the study design as validated JSON (objectives,
   endpoints, arms, population, eligibility, visits), each with page/section provenance.
2. **Store as components** — each element is a versioned `Component` with an ID and
   provenance, held in a graph (Neo4j).
3. **Render** — the same components render into an **M11-style synopsis** and an
   **E3-style CSR study-design** section. One knowledge base, two documents.
4. **Change impact** — edit one component (say a secondary endpoint) and the app
   lists every document section affected. *(The governance story.)*
5. **Evaluate** — hand-label 3–5 protocols and report field-level extraction accuracy.

A document is modelled as a **registry of section slots** (`src/templates.py`), each
declaring which component types render into it — so a shared component is what links
two documents. Adding SAP/PBRER later is just another registry, not a rewrite.

## Scope (named honestly)
A **USDM-shaped subset** — six element types — not the full CDISC USDM. The section
templates are indicative subsets of ICH M11 / E3, not authoritative reproductions.

## Layout
```
src/
  models.py      USDM-subset Pydantic models — the component contract (the core)
  templates.py   documents as registries of section slots (M11, E3)
  graph.py       Neo4j schema + the change-impact query
data/            public protocol PDFs (see data/README.md)
.streamlit/      secrets.toml.example (Anthropic + Neo4j Aura)
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
- **Phase 0 ✅** — component contract, template registry, graph schema (this scaffold).
- **Phase 1** — thin vertical slice: 1 protocol, objectives + endpoints, extract → store → render M11 + E3 → change-impact.
- **Phase 2** — all six element types, 3–5 protocols, versioning.
- **Phase 3** — Streamlit UI (side-by-side docs + impact panel, demo mode).
- **Phase 4** — field-level extraction evals on a labelled set.
- **Phase 5** — deploy + write-up.

---
_Uses only public data. A demonstration, not a validated system; not for clinical or regulatory use._

Built by **Harsha Vardhan B V** · [LinkedIn](https://www.linkedin.com/in/harsha-vardhan-b-v)
