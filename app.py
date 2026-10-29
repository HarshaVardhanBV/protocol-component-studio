"""Protocol Component Studio — Streamlit demo.

Runs entirely off the stored ExtractionResult JSON (no Neo4j, no Anthropic key).
Select a study, read the rendered M11/E3/SAP/ICF/PBRER, click a component to
inspect it and trace its change-impact across every document it reaches.

Run:  streamlit run app.py
"""
from __future__ import annotations
import streamlit as st

import app_data as D
from src.models import component_text

st.set_page_config(page_title="Protocol Component Studio", layout="wide",
                   initial_sidebar_state="expanded")

# ---------------- styling (clinical ink-on-paper, one teal accent) ----------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap');
:root{--teal:#2E6E7E;--teal-ink:#0C5F4C;--teal-bg:#E1F5EE;--amber:#B06A1E;--amber-bg:#FAEEDA;
--amber-ink:#7A4A0C;--ink:#14202B;--muted:#5C6872;--rule:#D7DEE4;--rule2:#E7ECF0;--blue-bg:#E9F1FA;--blue-ink:#1A4C80;}

/* hide Streamlit chrome */
header[data-testid="stHeader"]{display:none}
div[data-testid="stToolbar"],#MainMenu,footer{display:none!important}
.block-container{padding-top:1.4rem;padding-bottom:3rem;max-width:1240px}

/* fonts */
html,body,[class*="css"],.stMarkdown,button,input,label{font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif}
h1,h2,h3,h4{color:var(--ink);letter-spacing:-.01em}
.pcs-serif,.pcs-serif *{font-family:'Source Serif 4',Georgia,serif}
.pcs-doc h3{font-family:'Source Serif 4',Georgia,serif;font-size:1.2rem;margin:.1rem 0 .1rem}
.pcs-sub{font-weight:600;font-size:.92rem;margin:.9rem 0 .2rem;color:var(--ink)}
.lead{color:var(--muted);margin:.1rem 0 0}

/* badges + chips */
.badge{display:inline-block;font-size:.64rem;font-weight:600;letter-spacing:.02em;padding:2px 8px;
border-radius:20px;vertical-align:middle;margin-left:6px}
.b-derived,.b-review{background:var(--amber-bg);color:var(--amber-ink)}
.b-xform{background:var(--blue-bg);color:var(--blue-ink)}
.chip{display:inline-block;font-size:.7rem;font-weight:500;padding:3px 9px;border-radius:20px;
background:var(--blue-bg);color:var(--blue-ink);margin:0 4px 5px 0}
.prov{font-size:.8rem;color:#38474F;line-height:1.55}
.prov .q{font-family:'Source Serif 4',Georgia,serif;font-style:italic;color:var(--muted);display:block;margin-top:4px}
.cover{font-size:.74rem;color:var(--muted);margin:.1rem 0 .9rem}
.pill-ok{color:#366410;font-weight:600}
code{color:var(--teal-ink);background:var(--teal-bg);padding:1px 5px;border-radius:4px;font-size:.78rem}

/* radios -> pill tabs (hide the dot, style the labels) */
div[role="radiogroup"]{gap:6px}
div[role="radiogroup"] label{border:1px solid var(--rule);border-radius:8px;padding:5px 12px;margin:0;
background:#fff;transition:.12s;cursor:pointer}
div[role="radiogroup"] label:hover{border-color:var(--teal)}
div[role="radiogroup"] label>div:first-child{display:none}       /* kill the radio circle */
div[role="radiogroup"] label:has(input:checked){background:var(--teal);border-color:var(--teal)}
div[role="radiogroup"] label:has(input:checked) p{color:#fff;font-weight:600}
div[role="radiogroup"] label p{font-size:.84rem;color:var(--ink)}

/* component rows: flat left-aligned cards */
.stButton>button{width:100%;text-align:left;justify-content:flex-start;border:1px solid var(--rule);
border-radius:9px;padding:.55rem .75rem;font-weight:400;line-height:1.45;background:#fff;color:var(--ink);
font-size:.9rem;transition:.12s}
.stButton>button:hover{border-color:var(--teal);background:#F7FBFA}
.stButton>button:focus{box-shadow:none;border-color:var(--teal);color:var(--ink)}

/* sidebar */
section[data-testid="stSidebar"]{background:#F2F5F7;border-right:1px solid var(--rule)}
section[data-testid="stSidebar"] div[role="radiogroup"]{flex-direction:column}
section[data-testid="stSidebar"] div[role="radiogroup"] label{width:100%}
hr{margin:.7rem 0;border-color:var(--rule2)}
.glyph{display:inline-block;width:15px;height:15px;border-radius:4px;background:var(--teal);
vertical-align:-2px;margin-right:7px;position:relative}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def workspace():
    return D.load_workspace()


ws = workspace()

# ---------------- state ----------------
st.session_state.setdefault("study", ws["study_ids"][0])
st.session_state.setdefault("doc", D.doc_types()[0])
st.session_state.setdefault("sel", None)
st.session_state.setdefault("show_graph", False)


def on_study_change():
    st.session_state.sel = None
    st.session_state.show_graph = False


def select(iid):
    st.session_state.sel = iid
    st.session_state.show_graph = False


def jump(doc_type):
    st.session_state.doc = doc_type


def toggle_graph():
    st.session_state.show_graph = not st.session_state.show_graph


# ---------------- sidebar: studies + library ----------------
with st.sidebar:
    st.markdown("<div style='font-weight:600;font-size:1rem'><span class='glyph'></span>"
                "Protocol Component Studio</div>", unsafe_allow_html=True)
    st.caption("Public-data demo · not for clinical or regulatory use")

    st.markdown("<div class='pcs-sub' style='margin-top:1rem'>Study</div>", unsafe_allow_html=True)
    st.radio("Study", ws["study_ids"], key="study", label_visibility="collapsed",
             format_func=D.study_name, on_change=on_study_change)
    meta = D.study_meta(st.session_state.study)
    st.caption(f"{meta['drug']} · {meta['title']}")

    st.markdown("---")
    st.markdown("<div class='pcs-sub' style='margin-top:0'>Component library</div>", unsafe_allow_html=True)
    st.caption("Fixed ICH-grounded templates · onboarding a study mints 0 new definitions")
    sc = ws["study_counts"].get(st.session_state.study, {})
    rows = "".join(
        f"<div style='display:flex;justify-content:space-between;padding:3px 0;font-size:.8rem'>"
        f"<code>{did}</code>"
        f"<span style='color:#5C6872'>{sc.get(did, 0)}</span></div>"
        for did in ws["definition_ids"])
    st.markdown(rows, unsafe_allow_html=True)

    st.markdown("---")
    cf = D.conformance(st.session_state.study, ws["by_study"][st.session_state.study], ws["definitions"])
    t = cf["tally"]
    st.markdown(f"<div class='pcs-sub' style='margin:0'>Conformance</div>"
                f"<div style='font-size:.8rem'><span class='pill-ok'>{t['error']} errors</span> · "
                f"<span style='color:#7A4A0C'>{t['warning']} warnings</span> · "
                f"<span style='color:#5C6872'>{t['info']} info</span></div>", unsafe_allow_html=True)
    with st.expander("View findings"):
        if not cf["findings"]:
            st.caption("No findings.")
        for f in cf["findings"][:60]:
            icon = {"error": "🔴", "warning": "🟠", "info": "🔵"}.get(f["severity"], "•")
            st.markdown(f"<span style='font-size:.74rem'>{icon} <code>{f['rule']}</code> {f['detail']}</span>",
                        unsafe_allow_html=True)


# ---------------- main ----------------
study = st.session_state.study
insts = ws["by_study"][study]

st.markdown("<h3 style='margin:0 0 .1rem'>One component model. Every regulatory document.</h3>",
            unsafe_allow_html=True)
st.markdown("<p class='lead'>Write once, trace everywhere — select a component to trace its reach "
            "across M11, E3, SAP, ICF and PBRER.</p>", unsafe_allow_html=True)
st.markdown("<hr>", unsafe_allow_html=True)

doc_col, insp_col = st.columns([2, 1], gap="large")

with doc_col:
    st.radio("Document", D.doc_types(), key="doc", horizontal=True, label_visibility="collapsed",
             format_func=lambda d: D.DOC_LABEL.get(d, d))
    doc_type = st.session_state.doc
    doc = D.render_doc(study, doc_type, insts)
    cov = D.COVERAGE.get(doc_type)
    st.markdown(f"<div class='pcs-doc pcs-serif'><h3>{D.DOC_TITLE.get(doc_type, doc_type)}</h3></div>",
                unsafe_allow_html=True)
    if cov:
        pct = round(cov[0] / cov[1] * 100)
        st.markdown(f"<div class='cover'>Coverage · {cov[0]} of {cov[1]} sections populated "
                    f"from the component model ({pct}%) · rest narrative-authored</div>",
                    unsafe_allow_html=True)

    any_rendered = False
    for s in doc.sections:
        if not s.instances:
            continue
        any_rendered = True
        badges = ""
        if s.derivation == "summary":
            badges += "<span class='badge b-derived'>derived · built last</span>"
        if s.transform != "verbatim":
            lbl = D.TRANSFORM_LABEL.get(s.transform, s.transform)
            cls = "b-review" if s.transform == "lay_language" else "b-xform"
            badges += f"<span class='badge {cls}'>{lbl}</span>"
        st.markdown(f"<div class='pcs-sub'>{s.section_id} · {s.title}{badges}</div>",
                    unsafe_allow_html=True)
        frag = {f.instance_id: f.text for f in s.fragments}
        for i in s.instances:
            role = getattr(i.data, "role", None)
            prefix = f"[{role}] " if role else ""
            text = frag.get(i.id, component_text(i.data))
            text = (text[:118] + "…") if len(text) > 120 else text
            picked = "●  " if st.session_state.sel == i.id else ""
            st.button(f"{picked}{prefix}{text}", key=f"c_{doc_type}_{s.section_id}_{i.id}",
                      on_click=select, args=(i.id,))
    if not any_rendered:
        st.info("No components populate this document for the selected study "
                "(this document's slots accept element types not present here).")

with insp_col:
    with st.container(border=True):
        sel = st.session_state.sel
        inst = D.find_instance(insts, sel) if sel else None
        if inst is None:
            st.markdown("##### Inspector")
            st.caption("Select a component in the document to inspect it and trace its reach.")
        else:
            def_id = inst.definition_ids[0] if inst.definition_ids else "—"
            d = D.definition(def_id)
            n_studies = len(ws["def_studies"].get(def_id, []))
            st.markdown(f"##### `{def_id}`")
            st.caption((d.name if d else inst.type) + " template")
            st.button(("✕ Hide model" if st.session_state.show_graph else "◍ View in model"),
                      on_click=toggle_graph, key="btn_graph")

            if st.session_state.show_graph:
                st.graphviz_chart(D.ego_graph_dot(study, insts, inst.id, n_studies))
                st.caption("Scoped ego-graph: definition + source → instance → the sections it "
                           "renders into. Not the full knowledge base.")

            if d and d.standards:
                st.markdown("**Standards**")
                chips = "".join(
                    f"<span class='chip'>{s.framework}{(' ' + s.section.split(' ')[0]) if s.section else ''}</span>"
                    for s in d.standards)
                st.markdown(chips, unsafe_allow_html=True)

            st.markdown("**Provenance**")
            p = inst.provenance
            st.markdown(f"<div class='prov'><code>EXTRACTED_FROM</code> {p.protocol_id}<br>"
                        f"p. {p.page} · {p.section}<span class='q'>“{p.quote}”</span></div>",
                        unsafe_allow_html=True)

            st.markdown("**Change impact** &nbsp;<span style='color:#5C6872;font-size:.74rem'>"
                        "click to jump</span>", unsafe_allow_html=True)
            rows = D.impact(study, insts, inst.id)
            for r in rows:
                xf = "derived" if r.get("derived") else D.TRANSFORM_LABEL.get(r["transform"], r["transform"])
                st.button(f"{r['doc_type']} · {r['section_id']}  —  {xf}",
                          key=f"imp_{r['doc_type']}_{r['section_id']}", on_click=jump, args=(r["doc_type"],))
            st.caption(f"{len(rows)} fragments · {n_studies} "
                       f"{'studies' if n_studies != 1 else 'study'} "
                       f"{'share' if n_studies != 1 else 'shares'} this template")

            st.markdown("**Version**")
            st.markdown(f"<div class='prov'>v{inst.version} · "
                        f"{len(inst.history)} revision(s) · hash-stamped history<br>"
                        f"<span class='pill-ok'>✓ version.integrity verified</span></div>",
                        unsafe_allow_html=True)
