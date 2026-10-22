"""Stable generation shape; semantic grounding still belongs to the reviewer."""
from app.models.response_models import FeedbackCategory, FeedbackType, FindingKind, FindingSeverity


def assessment_response_format(dimensions: dict[str, float]) -> dict:
    def obj(properties):
        return {"type": "object", "properties": properties,
                "required": list(properties), "additionalProperties": False}

    def array(items):
        return {"type": "array", "items": items}

    def enum(values):
        return {"type": "string", "enum": list(values)}

    def text():
        return {"type": "string"}

    def strings():
        return array(text())

    # Evidence first, then grades. No expected answers, score floors, or
    # request-specific IDs in this cached schema; grounding is checked separately.
    properties = {
        "requirement_coverage": array(obj({
            "requirement_id": text(),
            "status": enum(["supported", "partial", "missing", "needs_clarification"]),
            "explanation": text(), "evidence_ids": strings(),
        })),
        "findings": array(obj({
            "title": text(), "explanation": text(),
            "recommendation": {"type": ["string", "null"]},
            "severity": enum(item.value for item in FindingSeverity),
            "kind": enum(item.value for item in FindingKind),
            "evidence_ids": strings(), "requirement_ids": strings(),
            "scored_gap": {"type": "boolean"},
            "criterion": {"type": ["string", "null"], "enum": [*dimensions, None]},
        })),
        "scores": obj({key: {"type": "integer", "minimum": 0, "maximum": 100}
                       for key in dimensions}),
        "verdict": enum(["strong_alignment", "needs_revision", "more_context_needed"]),
        "summary": text(),
        "feedback": array(obj({
            "type": enum(item.value for item in FeedbackType), "message": text(),
            "category": enum(item.value for item in FeedbackCategory),
            "priority": {"type": "integer", "minimum": 1, "maximum": 5},
        })),
        "detailed_analysis": obj({key: text() for key in (
            "scalability", "reliability", "security", "maintainability", "performance",
            "cost_efficiency", "observability", "deliverability",
        )}),
        **{key: strings() for key in ("strengths", "improvements", "missing_components",
            "missing_descriptions", "unclear_connections", "suggestions", "interview_questions")},
    }
    return {"type": "json_schema", "json_schema": {
        "name": "architecture_review_v2", "strict": True, "schema": obj(properties),
    }}
