"""
graph.py — Neo4j schema (three layers) + the change-impact queries.

Layers:
    (Study {id, drug})
    (ComponentDefinition {id, type, name})        # content-less slot (the class)
    (ComponentInstance {id, type, study_id, text}) # hydrated content (the object)
    (Document {id, type, study})                   # an output doc, e.g. M11 for a study
    (DocumentSection {id, doc_type, section_id, title})

Edges:
    (ComponentDefinition)-[:INSTANTIATED_AS]->(ComponentInstance)   # many-to-many
    (ComponentInstance)-[:FOR]->(Study)                            # context
    (DocumentSection)-[:RENDERS]->(ComponentInstance)              # reuse / usage
    (Document)-[:HAS_SECTION]->(DocumentSection)
    (DocumentSection)-[:EXPECTS]->(ComponentDefinition)            # template wiring (which slot)

Change impact comes in two flavours:
  - INSTANCE-level: edit one study's instance -> the document sections that render it.
  - DEFINITION-level (governance): edit a definition -> EVERY study's instance of it,
    and every document those render to. Cross-study propagation.
"""
from __future__ import annotations

import os

# Node labels
NODE_STUDY = "Study"
NODE_DEFINITION = "ComponentDefinition"
NODE_INSTANCE = "ComponentInstance"
NODE_DOCUMENT = "Document"
NODE_SECTION = "DocumentSection"
NODE_SOURCE = "SourceProtocol"            # the source PDF a component was extracted from
NODE_STANDARD = "Standard"                # a regulatory authority a template derives from
NODE_RULE = "ConformanceRule"             # a guardrail the standard imposes
NODE_ATTRIBUTE = "ExpectedAttribute"      # a field the template expects on its instances
NODE_FRAGMENT = "RenderedFragment"        # transformed text of an instance in a section

# Relationship types
REL_INSTANTIATED_AS = "INSTANTIATED_AS"   # (ComponentDefinition)->(ComponentInstance)
REL_FOR = "FOR"                           # (ComponentInstance)->(Study)
REL_RENDERS = "RENDERS"                   # (DocumentSection)->(ComponentInstance)
REL_HAS_SECTION = "HAS_SECTION"           # (Document)->(DocumentSection)
REL_EXPECTS = "EXPECTS"                   # (DocumentSection)->(ComponentDefinition)
REL_GOVERNED_BY = "GOVERNED_BY"           # (ComponentDefinition)->(Standard)
REL_HAS_RULE = "HAS_RULE"                 # (ComponentDefinition)->(ConformanceRule)
REL_EXPECTS_ATTRIBUTE = "EXPECTS_ATTRIBUTE"  # (ComponentDefinition)->(ExpectedAttribute)
REL_DEPENDS_ON = "DEPENDS_ON"             # (DocumentSection)->(DocumentSection); derived-from
REL_HAS_FRAGMENT = "HAS_FRAGMENT"         # (ComponentInstance)->(RenderedFragment); derived output
REL_RENDERED_IN = "RENDERED_IN"           # (RenderedFragment)->(DocumentSection)
REL_EXTRACTED_FROM = "EXTRACTED_FROM"     # (ComponentInstance)->(SourceProtocol); page/section/quote on the edge

# Edit an INSTANCE -> which document sections (across this study's docs) render it.
INSTANCE_IMPACT_QUERY = """
MATCH (i:ComponentInstance {uid: $uid})<-[:RENDERS]-(s:DocumentSection)<-[:HAS_SECTION]-(d:Document)
RETURN d.type AS doc_type, d.study AS study, s.section_id AS section_id, s.title AS title
ORDER BY study, doc_type, section_id
"""

# Edit a DEFINITION -> every study's instance of it + the documents they render to.
DEFINITION_IMPACT_QUERY = """
MATCH (def:ComponentDefinition {id: $definition_id})-[:INSTANTIATED_AS]->(i:ComponentInstance)
OPTIONAL MATCH (i)<-[:RENDERS]-(s:DocumentSection)<-[:HAS_SECTION]-(d:Document)
RETURN i.study_id AS study, i.id AS instance_id,
       d.type AS doc_type, s.section_id AS section_id
ORDER BY study, doc_type, section_id
"""

# A definition's instances across studies — the "same thing everywhere" view.
DEFINITION_INSTANCES_QUERY = """
MATCH (def:ComponentDefinition {id: $definition_id})-[:INSTANTIATED_AS]->(i:ComponentInstance)
RETURN i.study_id AS study, i.id AS instance_id, i.text AS text
ORDER BY study
"""


def get_driver():
    """Create a Neo4j driver from env vars (set via config.load_secrets).
    NOTE: on some Aura instances the username is the instance id, not 'neo4j'."""
    from neo4j import GraphDatabase

    return GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )


def get_database() -> "str | None":
    """Target database (Aura instances often name it the instance id, not 'neo4j')."""
    return os.environ.get("NEO4J_DATABASE") or None


def _run(driver, query: str, **params) -> list[dict]:
    with driver.session(database=get_database()) as session:
        return [dict(r) for r in session.run(query, **params)]


def instance_impact(driver, uid: str) -> list[dict]:
    """Document sections affected by changing one instance (uid = 'study_id:id')."""
    return _run(driver, INSTANCE_IMPACT_QUERY, uid=uid)


def definition_impact(driver, definition_id: str) -> list[dict]:
    """Instances (all studies) + documents affected by changing a definition."""
    return _run(driver, DEFINITION_IMPACT_QUERY, definition_id=definition_id)


def definition_instances(driver, definition_id: str) -> list[dict]:
    """All instances of a definition, across studies (consistency view)."""
    return _run(driver, DEFINITION_INSTANCES_QUERY, definition_id=definition_id)


# ----------------------------------------------------------------------------
# Loader: write studies / definitions / instances into Neo4j. All MERGE-based,
# so re-running is idempotent. Instance ids repeat across studies, so the node
# key is a composite uid = f"{study_id}:{id}".
# ----------------------------------------------------------------------------

CONSTRAINTS = [
    f"CREATE CONSTRAINT study_id IF NOT EXISTS FOR (n:{NODE_STUDY}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT def_id IF NOT EXISTS FOR (n:{NODE_DEFINITION}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT inst_uid IF NOT EXISTS FOR (n:{NODE_INSTANCE}) REQUIRE n.uid IS UNIQUE",
    f"CREATE CONSTRAINT src_id IF NOT EXISTS FOR (n:{NODE_SOURCE}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (n:{NODE_DOCUMENT}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT section_uid IF NOT EXISTS FOR (n:{NODE_SECTION}) REQUIRE n.uid IS UNIQUE",
    f"CREATE CONSTRAINT standard_key IF NOT EXISTS FOR (n:{NODE_STANDARD}) REQUIRE n.key IS UNIQUE",
    f"CREATE CONSTRAINT rule_id IF NOT EXISTS FOR (n:{NODE_RULE}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT attr_name IF NOT EXISTS FOR (n:{NODE_ATTRIBUTE}) REQUIRE n.name IS UNIQUE",
    f"CREATE CONSTRAINT fragment_uid IF NOT EXISTS FOR (n:{NODE_FRAGMENT}) REQUIRE n.uid IS UNIQUE",
]

_MERGE_STUDY = f"""
MERGE (s:{NODE_STUDY} {{id: $id}})
SET s.drug = $drug, s.title = $title
"""

_MERGE_DEFINITION = f"""
MERGE (d:{NODE_DEFINITION} {{id: $id}})
SET d.type = $type, d.role = $role, d.name = $name, d.label = $label,
    d.description = $description, d.content_form = $content_form,
    d.allowed_documents = $allowed_documents, d.renders_into = $renders_into,
    d.min_occurs = $min_occurs, d.max_occurs = $max_occurs, d.cardinality = $cardinality,
    d.status = $status, d.version = $version, d.effective_date = $effective_date,
    d.steward = $steward, d.level = $role
"""

# Standards / rules / expected-attributes are shared nodes, so the same ICH E9(R1)
# node (or the EP-REF-1 rule) links to every template it governs — a talkable hub.
_MERGE_STANDARD = f"""
MERGE (s:{NODE_STANDARD} {{key: $key}})
SET s.framework = $framework, s.section = $section, s.identifier = $identifier, s.url = $url
WITH s MATCH (d:{NODE_DEFINITION} {{id: $def_id}})
MERGE (d)-[:{REL_GOVERNED_BY}]->(s)
"""
_MERGE_RULE = f"""
MERGE (r:{NODE_RULE} {{id: $id}})
SET r.text = $text, r.severity = $severity, r.scope = $scope
WITH r MATCH (d:{NODE_DEFINITION} {{id: $def_id}})
MERGE (d)-[:{REL_HAS_RULE}]->(r)
"""
_MERGE_ATTRIBUTE = f"""
MERGE (a:{NODE_ATTRIBUTE} {{name: $name}})
SET a.label = $label, a.data_type = $data_type, a.cardinality = $cardinality,
    a.controlled_terms = $controlled_terms
WITH a MATCH (d:{NODE_DEFINITION} {{id: $def_id}})
MERGE (d)-[rel:{REL_EXPECTS_ATTRIBUTE}]->(a)
SET rel.required = $required
"""

# Provenance lives on the EXTRACTED_FROM edge, not as instance-node properties.
_MERGE_INSTANCE = f"""
MERGE (i:{NODE_INSTANCE} {{uid: $uid}})
SET i.id = $id, i.study_id = $study_id, i.type = $type,
    i.role = $role, i.purpose = $purpose, i.level = $role,
    i.text = $text, i.version = $version
WITH i
MATCH (s:{NODE_STUDY} {{id: $study_id}})
MERGE (i)-[:{REL_FOR}]->(s)
"""

_MERGE_EXTRACTED_FROM = f"""
MERGE (src:{NODE_SOURCE} {{id: $protocol_id}})
WITH src
MATCH (i:{NODE_INSTANCE} {{uid: $uid}})
MERGE (i)-[r:{REL_EXTRACTED_FROM}]->(src)
SET r.page = $page, r.section = $section, r.quote = $quote
"""

_MERGE_INSTANTIATED_AS = f"""
MATCH (d:{NODE_DEFINITION} {{id: $def_id}}), (i:{NODE_INSTANCE} {{uid: $uid}})
MERGE (d)-[:{REL_INSTANTIATED_AS}]->(i)
"""

_MERGE_DOCUMENT = f"""
MERGE (d:{NODE_DOCUMENT} {{id: $doc_id}})
SET d.type = $doc_type, d.study = $study_id
"""

_MERGE_SECTION = f"""
MATCH (d:{NODE_DOCUMENT} {{id: $doc_id}})
MERGE (sec:{NODE_SECTION} {{uid: $section_uid}})
SET sec.doc_type = $doc_type, sec.section_id = $section_id, sec.title = $title,
    sec.display_order = $display_order, sec.build_index = $build_index,
    sec.derivation = $derivation
MERGE (d)-[:{REL_HAS_SECTION}]->(sec)
"""

_MERGE_SECTION_DEP = f"""
MATCH (a:{NODE_SECTION} {{uid: $section_uid}}), (b:{NODE_SECTION} {{uid: $dep_uid}})
MERGE (a)-[:{REL_DEPENDS_ON}]->(b)
"""

_MERGE_RENDERS = f"""
MATCH (sec:{NODE_SECTION} {{uid: $section_uid}}), (i:{NODE_INSTANCE} {{uid: $uid}})
MERGE (sec)-[r:{REL_RENDERS}]->(i)
SET r.transform = $transform, r.order = $order
"""

_MERGE_FRAGMENT = f"""
MATCH (i:{NODE_INSTANCE} {{uid: $instance_uid}}), (sec:{NODE_SECTION} {{uid: $section_uid}})
MERGE (f:{NODE_FRAGMENT} {{uid: $fragment_uid}})
SET f.transform = $transform, f.status = $status, f.order = $order, f.text = $text,
    f.doc_type = $doc_type
MERGE (i)-[:{REL_HAS_FRAGMENT}]->(f)
MERGE (f)-[:{REL_RENDERED_IN}]->(sec)
"""


def uid_of(instance) -> str:
    return f"{instance.study_id}:{instance.id}"


def ensure_constraints(driver) -> None:
    with driver.session(database=get_database()) as session:
        for stmt in CONSTRAINTS:
            session.run(stmt)


def _standard_key(sr) -> str:
    return f"{sr.framework}|{sr.section or sr.identifier or ''}"


def _merge_definition(session, d) -> None:
    """MERGE a ComponentDefinition node with its full metadata, plus its Standard,
    ConformanceRule and ExpectedAttribute nodes (shared hubs) and the edges."""
    eff = d.effective_date.isoformat() if getattr(d, "effective_date", None) else None
    session.run(_MERGE_DEFINITION, id=d.id, type=d.type, role=d.role, name=d.name,
                label=d.label, description=d.description, content_form=d.content_form,
                allowed_documents=list(d.allowed_documents), renders_into=list(d.renders_into),
                min_occurs=d.min_occurs, max_occurs=d.max_occurs, cardinality=d.cardinality,
                status=d.status, version=d.version, effective_date=eff, steward=d.steward)
    for sr in d.standards:
        session.run(_MERGE_STANDARD, def_id=d.id, key=_standard_key(sr), framework=sr.framework,
                    section=sr.section, identifier=sr.identifier, url=sr.url)
    for r in d.conformance_rules:
        session.run(_MERGE_RULE, def_id=d.id, id=r.id, text=r.text,
                    severity=r.severity, scope=r.scope)
    for a in d.expected_attributes:
        session.run(_MERGE_ATTRIBUTE, def_id=d.id, name=a.name, label=a.label,
                    data_type=a.data_type, cardinality=a.cardinality,
                    controlled_terms=list(a.controlled_terms), required=a.required)


def load(driver, studies, definitions, instances) -> dict:
    """Load studies, definitions and instances plus FOR, INSTANTIATED_AS and
    EXTRACTED_FROM (provenance) edges. Idempotent."""
    ensure_constraints(driver)
    edges = 0
    with driver.session(database=get_database()) as session:
        for s in studies:
            session.run(_MERGE_STUDY, id=s.id,
                        drug=getattr(s, "drug", None), title=getattr(s, "title", None))
        for d in definitions:
            _merge_definition(session, d)
        for i in instances:
            session.run(_MERGE_INSTANCE, uid=uid_of(i), id=i.id, study_id=i.study_id,
                        type=i.type, role=getattr(i.data, "role", None),
                        purpose=getattr(i.data, "purpose", None),
                        text=i.data.text, version=i.version)
            session.run(_MERGE_EXTRACTED_FROM, uid=uid_of(i),
                        protocol_id=i.provenance.protocol_id, page=i.provenance.page,
                        section=i.provenance.section, quote=i.provenance.quote)
            for def_id in i.definition_ids:
                session.run(_MERGE_INSTANTIATED_AS, def_id=def_id, uid=uid_of(i))
                edges += 1
    standards = {_standard_key(sr) for d in definitions for sr in d.standards}
    rules = {r.id for d in definitions for r in d.conformance_rules}
    attrs = {a.name for d in definitions for a in d.expected_attributes}
    return {"studies": len(studies), "definitions": len(definitions),
            "instances": len(instances), "instantiated_as": edges,
            "standards": len(standards), "rules": len(rules), "attributes": len(attrs)}


def load_documents(driver, rendered_docs) -> dict:
    """Write Document / DocumentSection nodes (HAS_SECTION) and the RENDERS edges
    from already-rendered documents (see render.render_study). Idempotent."""
    docs = sections = renders = deps = fragments = 0
    with driver.session(database=get_database()) as session:
        for doc in rendered_docs:
            session.run(_MERGE_DOCUMENT, doc_id=doc.doc_id,
                        doc_type=doc.doc_type, study_id=doc.study_id)
            docs += 1
            for sec in doc.sections:
                session.run(_MERGE_SECTION, doc_id=doc.doc_id, section_uid=sec.section_uid,
                            doc_type=sec.doc_type, section_id=sec.section_id, title=sec.title,
                            display_order=sec.display_order, build_index=sec.build_index,
                            derivation=sec.derivation)
                sections += 1
                for pos, inst in enumerate(sec.instances):
                    session.run(_MERGE_RENDERS, section_uid=sec.section_uid, uid=uid_of(inst),
                                transform=sec.transform, order=pos)
                    renders += 1
                for fr in sec.fragments:
                    session.run(_MERGE_FRAGMENT, fragment_uid=fr.fragment_uid,
                                instance_uid=fr.instance_uid, section_uid=fr.section_uid,
                                transform=fr.transform, status=fr.status, order=fr.order,
                                text=fr.text, doc_type=fr.doc_type)
                    fragments += 1
            for sec in doc.sections:
                for dep_id in sec.depends_on:
                    dep_uid = f"{doc.study_id}:{doc.doc_type}:{dep_id}"
                    session.run(_MERGE_SECTION_DEP, section_uid=sec.section_uid, dep_uid=dep_uid)
                    deps += 1
    return {"documents": docs, "sections": sections, "renders": renders,
            "depends_on": deps, "fragments": fragments}


def _main():
    import argparse, glob, json, os
    from .models import ExtractionResult, ComponentDefinition, Study
    from .config import load_secrets

    ap = argparse.ArgumentParser(description="Load studies/definitions/instances into Neo4j.")
    ap.add_argument("--store", default="store")
    ap.add_argument("--defs", default=None, help="definitions file (default: <store>/definitions.json)")
    ap.add_argument("--wipe", action="store_true", help="DELETE all nodes first (destructive)")
    ap.add_argument("--no-render", action="store_true", help="skip rendering documents + RENDERS edges")
    args = ap.parse_args()

    load_secrets()
    defs_path = args.defs or os.path.join(args.store, "definitions.json")
    study_paths = sorted(p for p in glob.glob(os.path.join(args.store, "*.json"))
                         if os.path.basename(p) != "definitions.json")

    from .render import render_study

    results = [ExtractionResult.model_validate(json.load(open(p))) for p in study_paths]
    instances = [i for r in results for i in r.instances]
    studies = [Study(id=r.study_id) for r in results]
    definitions = ([ComponentDefinition.model_validate(d) for d in json.load(open(defs_path))]
                   if os.path.exists(defs_path) else [])

    driver = get_driver()
    try:
        if args.wipe:
            _run(driver, "MATCH (n) DETACH DELETE n")
        counts = load(driver, studies, definitions, instances)
        doc_counts = {"documents": 0, "sections": 0, "renders": 0}
        if not args.no_render:
            rendered = [d for r in results for d in render_study(r.study_id, r.instances)]
            doc_counts = load_documents(driver, rendered)
    finally:
        driver.close()
    print("loaded:", counts)
    print("rendered:", doc_counts)


if __name__ == "__main__":
    _main()
