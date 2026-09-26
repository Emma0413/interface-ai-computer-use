import json

import pytest

from cuauto.discovery import OpenAICompatibleModel, strict_provider_schema, validate_model_action
from cuauto.models import ModelAction


def test_provider_schema_requires_every_property_and_uses_supported_subset():
    schema = strict_provider_schema(ModelAction.model_json_schema())

    def inspect(value):
        if isinstance(value, list):
            for item in value:
                inspect(item)
        elif isinstance(value, dict):
            assert not (
                {"default", "title", "minLength", "maxLength", "minItems", "maxItems"}
                & value.keys()
            )
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value.get("properties", {}))
            for item in value.values():
                inspect(item)

    inspect(schema)


def test_irrelevant_strict_schema_placeholders_are_discarded():
    action = validate_model_action(
        json.dumps(
            {
                "action": "fill",
                "rationale": "Enter the invocation parameter.",
                "locators": [
                    {
                        "strategy": "label",
                        "value": "Member number",
                        "role": None,
                        "scope": None,
                        "attribute": None,
                        "fragile": False,
                    }
                ],
                "value": {"param": "member_id"},
                "destination": "",
                "success_checkpoint": {"kind": "text_present", "value": "", "locators": []},
                "output": {"output": "", "value_type": "string", "pattern": None},
            }
        )
    )
    assert action.action.value == "fill"
    assert (
        action.destination is None and action.success_checkpoint is None and action.output is None
    )


def test_fill_literal_is_replaced_by_parameter_reference(monkeypatch):
    class Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            content = {
                "action": "fill",
                "rationale": "Fill the member field.",
                "locators": [
                    {
                        "strategy": "label",
                        "value": "Member number",
                        "role": None,
                        "scope": None,
                        "attribute": None,
                        "fragile": False,
                    }
                ],
                "value": {"literal": "M1001"},
                "destination": None,
                "success_checkpoint": None,
                "output": None,
            }
            return {"choices": [{"message": {"content": json.dumps(content)}}]}

    monkeypatch.setattr("cuauto.discovery.httpx.post", lambda *args, **kwargs: Response())
    action = OpenAICompatibleModel("https://example.test/v1", "model", "key").decide(
        goal="lookup", observation={}, policy={}
    )
    assert action.value is not None
    assert action.value.model_dump() == {"param": "member_id"}


def test_missing_role_is_inferred_from_observed_exact_control():
    content = json.dumps(
        {
            "action": "click",
            "rationale": "Open the matching member.",
            "locators": [
                {
                    "strategy": "role",
                    "value": "Open member",
                    "role": None,
                    "scope": None,
                    "attribute": None,
                    "fragile": False,
                }
            ],
            "value": None,
            "destination": None,
            "success_checkpoint": None,
            "output": None,
        }
    )
    action = validate_model_action(
        content, [{"tag": "a", "role": "", "name": "Open member", "type": ""}]
    )
    assert action.locators[0].role == "link"


def test_provider_canonicalizes_extraction_to_capability_contract(monkeypatch):
    class Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            content = {
                "action": "extract",
                "rationale": "Read balance.",
                "locators": [
                    {
                        "strategy": "text",
                        "value": "$1,245.67",
                        "role": None,
                        "scope": None,
                        "attribute": None,
                        "fragile": False,
                    }
                ],
                "value": None,
                "destination": None,
                "success_checkpoint": None,
                "output": {"output": "balance", "value_type": "string", "pattern": None},
            }
            return {"choices": [{"message": {"content": json.dumps(content)}}]}

    monkeypatch.setattr("cuauto.discovery.httpx.post", lambda *args, **kwargs: Response())
    action = OpenAICompatibleModel("https://example.test/v1", "model", "key").decide(
        goal="lookup", observation={"controls": []}, policy={}
    )
    assert action.output is not None
    assert action.output.output == "savings_balance"
    assert action.output.value_type.value == "decimal"


@pytest.mark.parametrize("combined", ["Savings balance\t$1,245.67", "Savings balance $1,245.67"])
def test_combined_table_text_becomes_stable_row_value_locator(combined):
    content = json.dumps(
        {
            "action": "extract",
            "rationale": "Read the savings balance.",
            "locators": [
                {
                    "strategy": "text",
                    "value": combined,
                    "role": None,
                    "scope": None,
                    "attribute": None,
                    "fragile": False,
                }
            ],
            "value": None,
            "destination": None,
            "success_checkpoint": None,
            "output": {"output": "savings_balance", "value_type": "decimal", "pattern": "[$,]"},
        }
    )
    action = validate_model_action(content)
    assert action.locators[0].strategy == "row_value"
    assert action.locators[0].value == "Savings balance"
