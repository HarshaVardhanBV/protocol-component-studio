"""Protocol Component Studio — source package."""
from .models import (
    ComponentDefinition,
    ComponentInstance,
    Study,
    ComponentType,
    Provenance,
    Objective,
    Endpoint,
    Arm,
    Population,
    EligibilityCriterion,
    Visit,
    ELEMENT_MODELS,
    ExtractionResult,
)
from .templates import REGISTRY, SectionSlot, slots_for_component_type
from .merge import merge_components

__all__ = [
    "ComponentDefinition", "ComponentInstance", "Study",
    "ComponentType", "Provenance",
    "Objective", "Endpoint", "Arm", "Population", "EligibilityCriterion", "Visit",
    "ELEMENT_MODELS", "ExtractionResult",
    "REGISTRY", "SectionSlot", "slots_for_component_type",
    "merge_components",
]
