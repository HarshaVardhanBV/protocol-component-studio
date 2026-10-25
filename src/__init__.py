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
    StandardRef,
    ExpectedAttribute,
    ComponentRole,
    EndpointPurpose,
)
from .definitions import library as definition_library, LIBRARY_BY_ID, template_id
from .templates import REGISTRY, SectionSlot, slots_for_component_type
from .merge import merge_components
from .induce import induce, llm_inducer, fuzzy_inducer
from .classify import classify, template_library, type_classifier, classification_report
from .render import (render_document, render_study, fragment_text,
                     RenderedDocument, RenderedSection, RenderedFragment)

__all__ = [
    "ComponentDefinition", "ComponentInstance", "Study",
    "ComponentType", "Provenance",
    "Objective", "Endpoint", "Arm", "Population", "EligibilityCriterion", "Visit",
    "ELEMENT_MODELS", "ExtractionResult",
    "REGISTRY", "SectionSlot", "slots_for_component_type",
    "merge_components",
    "induce", "llm_inducer", "fuzzy_inducer",
    "classify", "template_library", "type_classifier", "classification_report",
    "StandardRef", "ExpectedAttribute", "ComponentRole", "EndpointPurpose",
    "definition_library", "LIBRARY_BY_ID", "template_id",
    "render_document", "render_study", "fragment_text",
    "RenderedDocument", "RenderedSection", "RenderedFragment",
]
