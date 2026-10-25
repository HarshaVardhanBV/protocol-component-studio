"""
templates.py — assembly instructions, loaded from declarative YAML (one file per
document type in src/document_templates/). These are CONFIGURATION, not graph data:
they say how to assemble components into a document type. The graph holds only the
component knowledge base; documents (and change-impact) are computed from these
templates + the components. Adding a document type = adding a YAML file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .models import ComponentType, TransformKind

Derivation = Literal["original", "summary"]
_TEMPLATE_DIR = Path(__file__).parent / "document_templates"


class SectionSlot(BaseModel):
    doc_type: str
    section_id: str
    title: str
    renders: list[ComponentType] = []
    display_order: int = 0
    derivation: Derivation = "original"
    depends_on: list[str] = []
    transform: TransformKind = "verbatim"


def load_registry(template_dir: Path = _TEMPLATE_DIR) -> dict[str, list[SectionSlot]]:
    """Read every document-type YAML into an ordered list of SectionSlots."""
    import yaml

    registry: dict[str, list[SectionSlot]] = {}
    for path in sorted(Path(template_dir).glob("*.yaml")):
        spec = yaml.safe_load(path.read_text())
        doc_type = spec["doc_type"]
        slots = [SectionSlot(doc_type=doc_type, **s) for s in spec.get("sections", [])]
        registry[doc_type] = slots
    return registry


REGISTRY: dict[str, list[SectionSlot]] = load_registry()


def slots_for_component_type(ct: ComponentType) -> list[SectionSlot]:
    return [s for slots in REGISTRY.values() for s in slots if ct in s.renders]


def slot_key(doc_type: str, section_id: str) -> str:
    return f"{doc_type}:{section_id}"
