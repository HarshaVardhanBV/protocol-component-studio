"""
graph.py — Neo4j schema + the change-impact query (connection scaffold).

Phase 0 fixes the schema (node labels, relationship types) and the ONE query
that is the whole demo. Phase 1 wires the extractor's Components into it.

Graph shape:
    (:SourceProtocol {id, title})
    (:Component {id, type, version, ...})
    (:DocumentSection {doc_type, section_id, title})

    (:Component)-[:EXTRACTED_FROM {page, section}]->(:SourceProtocol)   # provenance
    (:DocumentSection)-[:RENDERS]->(:Component)                         # the impact edge
    (:Component)-[:SUPPORTS]->(:Component)                              # e.g. endpoint -> objective

Change-impact = "which sections render this component?" — one traversal.
"""
from __future__ import annotations

import os

# Node labels
NODE_PROTOCOL = "SourceProtocol"
NODE_COMPONENT = "Component"
NODE_SECTION = "DocumentSection"

# Relationship types
REL_EXTRACTED_FROM = "EXTRACTED_FROM"
REL_RENDERS = "RENDERS"
REL_SUPPORTS = "SUPPORTS"

# The query that is the whole point of the project: given a component that
# changed, return every document section that renders it (direct), plus sections
# rendering components that SUPPORT-chain to it (transitive, 1 hop).
IMPACT_QUERY = """
MATCH (c:Component {id: $component_id})
OPTIONAL MATCH (c)<-[:RENDERS]-(direct:DocumentSection)
OPTIONAL MATCH (c)<-[:SUPPORTS]-(dep:Component)<-[:RENDERS]-(indirect:DocumentSection)
WITH collect(DISTINCT direct) + collect(DISTINCT indirect) AS sections
UNWIND sections AS s
RETURN DISTINCT s.doc_type AS doc_type, s.section_id AS section_id, s.title AS title
ORDER BY doc_type, section_id
"""


def get_driver():
    """Create a Neo4j driver from env vars (set these from .streamlit/secrets.toml).
    Imported lazily so the models/templates don't require the neo4j package.

    NOTE: on some Aura instances the username is the instance id (e.g. '117bc917'),
    not 'neo4j' — so we read NEO4J_USER from the environment rather than assume."""
    from neo4j import GraphDatabase

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    return GraphDatabase.driver(uri, auth=(user, password))


def get_database() -> str | None:
    """Target database name. On some Aura instances this is the instance id, not
    'neo4j', so always read it from the environment. Returns None if unset, which
    makes the driver use the connection's default database."""
    return os.environ.get("NEO4J_DATABASE") or None


def affected_sections(driver, component_id: str) -> list[dict]:
    """Run the change-impact query. Returns [{doc_type, section_id, title}, ...]."""
    with driver.session(database=get_database()) as session:
        result = session.run(IMPACT_QUERY, component_id=component_id)
        return [dict(record) for record in result]
