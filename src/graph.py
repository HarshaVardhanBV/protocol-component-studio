"""
graph.py — Neo4j is the COMPONENT KNOWLEDGE BASE only. Four node types:

  (Study)  (ComponentDefinition)  (ComponentInstance)  (SourceProtocol)

Edges: INSTANTIATED_AS (definition->instance, the reuse spine), FOR (instance->study),
EXTRACTED_FROM (instance->source, provenance).

A ComponentDefinition is authored config (src/definitions.py). It is mirrored to the
graph as the hub instances attach to, and it is SELF-DESCRIBING via properties — its
regulatory basis (standards), guardrails (conformance_rules) and expected instance
fields (expected_attributes) are LIST PROPERTIES on the node, not satellite nodes.
Full structured detail lives in definitions.json (the config source of truth). Rule:
a node exists only for an entity that is shared AND traversed; metadata that merely
describes one definition is a property, not a node.

Documents are NOT here (YAML config; computed). The source document is provenance only.
"""
from __future__ import annotations

import os

from .models import component_text

NODE_STUDY = "Study"
NODE_DEFINITION = "ComponentDefinition"
NODE_INSTANCE = "ComponentInstance"
NODE_SOURCE = "SourceProtocol"

REL_INSTANTIATED_AS = "INSTANTIATED_AS"
REL_FOR = "FOR"
REL_EXTRACTED_FROM = "EXTRACTED_FROM"

DEFINITION_INSTANCES_QUERY = """
MATCH (def:ComponentDefinition {id: $definition_id})-[:INSTANTIATED_AS]->(i:ComponentInstance)
RETURN i.study_id AS study, i.id AS instance_id, i.text AS text ORDER BY study
"""
DEFINITION_REUSE_QUERY = """
MATCH (def:ComponentDefinition)-[:INSTANTIATED_AS]->(i:ComponentInstance)
RETURN def.id AS definition, count(DISTINCT i.study_id) AS studies, count(i) AS instances
ORDER BY studies DESC, definition
"""


def get_driver():
    from neo4j import GraphDatabase
    return GraphDatabase.driver(os.environ["NEO4J_URI"],
                                auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))


def get_database():
    return os.environ.get("NEO4J_DATABASE") or None


def _run(driver, query, **params):
    with driver.session(database=get_database()) as session:
        return [dict(r) for r in session.run(query, **params)]


def definition_instances(driver, definition_id):
    return _run(driver, DEFINITION_INSTANCES_QUERY, definition_id=definition_id)


def definition_reuse(driver):
    return _run(driver, DEFINITION_REUSE_QUERY)


CONSTRAINTS = [
    f"CREATE CONSTRAINT study_id IF NOT EXISTS FOR (n:{NODE_STUDY}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT def_id IF NOT EXISTS FOR (n:{NODE_DEFINITION}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT inst_uid IF NOT EXISTS FOR (n:{NODE_INSTANCE}) REQUIRE n.uid IS UNIQUE",
    f"CREATE CONSTRAINT src_id IF NOT EXISTS FOR (n:{NODE_SOURCE}) REQUIRE n.id IS UNIQUE",
]

_MERGE_STUDY = f"MERGE (s:{NODE_STUDY} {{id: $id}}) SET s.drug=$drug, s.title=$title"
# The definition is self-describing: regulatory basis / rules / expected fields are
# summary LIST PROPERTIES (full detail in definitions.json).
_MERGE_DEFINITION = f"""
MERGE (d:{NODE_DEFINITION} {{id: $id}})
SET d.type=$type, d.role=$role, d.name=$name, d.label=$label, d.description=$description,
    d.content_form=$content_form, d.allowed_documents=$allowed_documents,
    d.renders_into=$renders_into, d.min_occurs=$min_occurs, d.max_occurs=$max_occurs,
    d.cardinality=$cardinality, d.status=$status, d.version=$version,
    d.effective_date=$effective_date, d.steward=$steward, d.level=$role,
    d.standards=$standards, d.conformance_rules=$conformance_rules,
    d.expected_attributes=$expected_attributes
"""
_MERGE_INSTANCE = f"""
MERGE (i:{NODE_INSTANCE} {{uid: $uid}})
SET i.id=$id, i.study_id=$study_id, i.type=$type, i.role=$role, i.purpose=$purpose,
    i.level=$role, i.text=$text, i.version=$version,
    i.revised_by=$revised_by, i.revised_at=$revised_at, i.change_note=$change_note,
    i.revision_count=$revision_count, i.history=$history
WITH i MATCH (s:{NODE_STUDY} {{id: $study_id}}) MERGE (i)-[:{REL_FOR}]->(s)
"""
_MERGE_EXTRACTED_FROM = f"""
MERGE (src:{NODE_SOURCE} {{id: $protocol_id}})
WITH src MATCH (i:{NODE_INSTANCE} {{uid: $uid}})
MERGE (i)-[r:{REL_EXTRACTED_FROM}]->(src)
SET r.page=$page, r.section=$section, r.quote=$quote
"""
_MERGE_INSTANTIATED_AS = f"MATCH (d:{NODE_DEFINITION} {{id: $def_id}}), (i:{NODE_INSTANCE} {{uid: $uid}}) MERGE (d)-[:{REL_INSTANTIATED_AS}]->(i)"


def uid_of(instance):
    return f"{instance.study_id}:{instance.id}"


def _standard_label(sr):
    return f"{sr.framework} {sr.section or sr.identifier or ''}".strip()


def ensure_constraints(driver):
    with driver.session(database=get_database()) as session:
        for stmt in CONSTRAINTS:
            session.run(stmt)


def _merge_definition(session, d):
    eff = d.effective_date.isoformat() if getattr(d, "effective_date", None) else None
    session.run(
        _MERGE_DEFINITION, id=d.id, type=d.type, role=d.role, name=d.name, label=d.label,
        description=d.description, content_form=d.content_form,
        allowed_documents=list(d.allowed_documents), renders_into=list(d.renders_into),
        min_occurs=d.min_occurs, max_occurs=d.max_occurs, cardinality=d.cardinality,
        status=d.status, version=d.version, effective_date=eff, steward=d.steward,
        standards=[_standard_label(s) for s in d.standards],
        conformance_rules=[f"{r.id}: {r.text} ({r.severity})" for r in d.conformance_rules],
        expected_attributes=[a.name for a in d.expected_attributes],
    )


def load(driver, studies, definitions, instances):
    """Load the component knowledge base. Idempotent."""
    ensure_constraints(driver)
    edges = 0
    with driver.session(database=get_database()) as session:
        for s in studies:
            session.run(_MERGE_STUDY, id=s.id, drug=getattr(s, "drug", None), title=getattr(s, "title", None))
        for d in definitions:
            _merge_definition(session, d)
        for i in instances:
            session.run(_MERGE_INSTANCE, uid=uid_of(i), id=i.id, study_id=i.study_id,
                        type=i.type, role=getattr(i.data, "role", None),
                        purpose=getattr(i.data, "purpose", None), text=component_text(i.data), version=i.version,
                        revised_by=i.revised_by,
                        revised_at=(i.revised_at.isoformat() if i.revised_at else None),
                        change_note=i.change_note, revision_count=len(i.history),
                        history=__import__("json").dumps([r.model_dump(mode="json") for r in i.history]))
            session.run(_MERGE_EXTRACTED_FROM, uid=uid_of(i), protocol_id=i.provenance.protocol_id,
                        page=i.provenance.page, section=i.provenance.section, quote=i.provenance.quote)
            for def_id in i.definition_ids:
                session.run(_MERGE_INSTANTIATED_AS, def_id=def_id, uid=uid_of(i))
                edges += 1
    return {"studies": len(studies), "definitions": len(definitions),
            "instances": len(instances), "instantiated_as": edges}


def _main():
    import argparse, glob, json, os
    from .models import ExtractionResult, ComponentDefinition, Study
    from .config import load_secrets

    ap = argparse.ArgumentParser(description="Load the component knowledge base into Neo4j.")
    ap.add_argument("--store", default="store")
    ap.add_argument("--defs", default=None)
    ap.add_argument("--wipe", action="store_true", help="DELETE all nodes first (destructive)")
    args = ap.parse_args()

    load_secrets()
    defs_path = args.defs or os.path.join(args.store, "definitions.json")
    study_paths = sorted(p for p in glob.glob(os.path.join(args.store, "*.json"))
                         if os.path.basename(p) != "definitions.json")
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
    finally:
        driver.close()
    print("loaded:", counts)


if __name__ == "__main__":
    _main()
