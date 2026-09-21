from app.models.reasoning_models import ReasoningContext
from app.services.dynamodb_service import convert_floats_to_decimal


def test_convert_floats_to_decimal_serializes_pydantic_models():
    context = ReasoningContext(requirements="MCP-created architecture")

    assert convert_floats_to_decimal(context) == {
        "requirements": "MCP-created architecture",
        "scaleAssumptions": None,
        "expectedTraffic": None,
        "readWriteRatio": None,
        "latencyGoals": None,
        "availabilityTarget": None,
        "consistencyRequirements": None,
        "technologyChoices": None,
        "tradeoffs": None,
        "unresolvedRisks": None,
    }
