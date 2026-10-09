"""Tool contract regression tests: preserve legacy behavior, fail closed on invalid inputs."""
import pytest

from tools.registry import Risk, Tool, ToolRegistry


def make_tool(**kwargs):
    return Tool(name="inspect", description="inspect data", handler=lambda params: {"ok": True}, **kwargs)


def test_legacy_tool_has_optional_contracts():
    tool = make_tool()
    assert ToolRegistry.validate_input(tool, {"path": "readme"}) == {"path": "readme"}
    assert ToolRegistry.validate_output(tool, {"ok": True}) == {"ok": True}


def test_input_validator_rejects_false():
    tool = make_tool(input_validator=lambda params: params.get("path") == "allowed")
    with pytest.raises(ValueError, match="input contract"):
        ToolRegistry.validate_input(tool, {"path": "denied"})


def test_input_validator_can_raise_specific_validation_error():
    def reject(params):
        raise ValueError("missing required path")
    tool = make_tool(input_validator=reject)
    with pytest.raises(ValueError, match="missing required path"):
        ToolRegistry.validate_input(tool, {})


def test_input_contract_rejects_non_object():
    with pytest.raises(ValueError, match="object"):
        ToolRegistry.validate_input(make_tool(), ["not", "an", "object"])


def test_output_contract_rejects_false_before_verification():
    tool = make_tool(risk=Risk.REVERSIBLE, output_validator=lambda result: result.get("ok") is True)
    with pytest.raises(ValueError, match="output contract"):
        ToolRegistry.verify_result(None, tool, {}, {"ok": False})


def test_valid_output_retains_existing_verification_semantics():
    tool = make_tool(risk=Risk.READ_ONLY, output_validator=lambda result: isinstance(result, dict))
    result = ToolRegistry.verify_result(None, tool, {}, {"ok": True})
    assert result.verified is True


def test_invalid_input_is_rejected_before_permission_evaluation():
    tool = make_tool(input_validator=lambda params: False)
    registry = object.__new__(ToolRegistry)
    registry.emergency_stop = False
    with pytest.raises(ValueError, match="input contract"):
        registry.authorize(tool, parameters={"path": "denied"})
