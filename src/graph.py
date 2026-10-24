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

# Relationship types
REL_INSTANTIATED_AS = "INSTANTIATED_AS"   # (ComponentDefinition)->(ComponentInstance)
REL_FOR = "FOR"                           # (ComponentInstance)->(Study)
REL_RENDERS = "RENDERS"                   # (DocumentSection)->(ComponentInstance)
REL_HAS_SECTION = "HAS_SECTION"           # (Document)->(DocumentSection)
REL_EXPECTS = "EXPECTS"                   # (DocumentSection)->(ComponentDefinition)

# Edit an INSTANCE -> which document sections (across this study's docs) render it.
INSTANCE_IMPACT_QUERY = """
MATCH (i:ComponentInstance {id: $instance_id})<-[:RENDERS]-(s:DocumentSection)<-[:HAS_SECTION]-(d:Document)
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


def instance_impact(driver, instance_id: str) -> list[dict]:
    """Document sections affected by changing one instance."""
    return _run(driver, INSTANCE_IMPACT_QUERY, instance_id=instance_id)


def definition_impact(driver, definition_id: str) -> list[dict]:
    """Instances (all studies) + documents affected by changing a definition."""
    return _run(driver, DEFINITION_IMPACT_QUERY, definition_id=definition_id)


def definition_instances(driver, definition_id: str) -> list[dict]:
    """All instances of a definition, across studies (consistency view)."""
    return _run(driver, DEFINITION_INSTANCES_QUERY, definition_id=definition_id)
