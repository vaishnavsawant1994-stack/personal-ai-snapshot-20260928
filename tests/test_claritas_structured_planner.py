import pytest

from agent.planner import InvalidPlan, Planner


class ToolStub:
    def __init__(self, name, prohibited=False):
        self.name = name
        self.prohibited = prohibited


class FakeTools:
    def all(self):
        return [ToolStub("safe_read"), ToolStub("blocked_tool", prohibited=True)]

    def schema_text(self):
        return "- safe_read: read-only"


class FakeModels:
    def json(self, *args, **kwargs):
        raise AssertionError("model call is not expected in validation tests")


def planner():
    return Planner(FakeModels(), FakeTools())


def test_structured_plan_preserves_safe_execution_metadata():
    result = planner().validate({
        "goal": "inspect repository",
        "version": 3,
        "execution_budget": {
            "max_steps": 4,
            "max_replans": 2,
            "max_tool_calls": 8,
            "deadline_seconds": 600,
        },
        "steps": [
            {
                "id": "inspect",
                "tool": "safe_read",
                "description": "inspect",
                "parameters": {"path": "README.md"},
                "depends_on": [],
                "expected_output": "repository facts",
                "success_criteria": ["README was observed"],
                "verification": {"required": True, "method": "tool_contract"},
                "retry_policy": {"max_attempts": 2, "backoff_seconds": 1, "safe_only": True},
                "timeout_seconds": 30,
            },
            {
                "id": "inspect_more",
                "tool": "safe_read",
                "parameters": {"path": "ARCHITECTURE.md"},
                "depends_on": ["inspect"],
            },
        ],
    })
    assert result["version"] == 3
    assert result["execution_budget"]["max_replans"] == 2
    assert result["steps"][0]["verification"] == {"required": True, "method": "tool_contract"}
    assert result["steps"][1]["depends_on"] == ["inspect"]


def test_dependencies_must_refer_only_to_earlier_steps():
    with pytest.raises(InvalidPlan, match="future step ids"):
        planner().validate({
            "steps": [
                {"id": "first", "tool": "safe_read", "depends_on": ["later"]},
                {"id": "later", "tool": "safe_read"},
            ]
        })


def test_duplicate_step_ids_are_rejected():
    with pytest.raises(InvalidPlan, match="duplicates step id"):
        planner().validate({
            "steps": [
                {"id": "same", "tool": "safe_read"},
                {"id": "same", "tool": "safe_read"},
            ]
        })


def test_prohibited_registered_tool_is_not_plannable():
    with pytest.raises(InvalidPlan, match="unavailable tool"):
        planner().validate({"steps": [{"tool": "blocked_tool"}]})


@pytest.mark.parametrize(
    "field,value",
    [
        ("timeout_seconds", 0),
        ("timeout_seconds", Planner.MAX_TIMEOUT_SECONDS + 1),
        ("retry_policy", {"max_attempts": Planner.MAX_ATTEMPTS + 1}),
        ("verification", {"required": "yes"}),
        ("success_criteria", ["x"] * (Planner.MAX_SUCCESS_CRITERIA + 1)),
    ],
)
def test_step_execution_metadata_is_bounded(field, value):
    with pytest.raises(InvalidPlan):
        planner().validate({"steps": [{"tool": "safe_read", field: value}]})


@pytest.mark.parametrize(
    "budget",
    [
        [],
        {"max_steps": 0},
        {"max_replans": Planner.MAX_REPLANS + 1},
        {"max_tool_calls": Planner.MAX_TOOL_CALLS + 1},
        {"deadline_seconds": Planner.MAX_DEADLINE_SECONDS + 1},
    ],
)
def test_execution_budget_is_bounded(budget):
    with pytest.raises(InvalidPlan):
        planner().validate({"execution_budget": budget, "steps": []})


def test_declared_max_steps_is_enforced():
    with pytest.raises(InvalidPlan, match="declared execution budget"):
        planner().validate({
            "execution_budget": {"max_steps": 1},
            "steps": [{"tool": "safe_read"}, {"tool": "safe_read"}],
        })


def test_planning_metadata_cannot_smuggle_approval_or_policy_fields():
    result = planner().validate({
        "steps": [{
            "tool": "safe_read",
            "parameters": {},
            "approval": "bypass",
            "owner_permission": "allow",
            "risk": "READ_ONLY",
        }]
    })
    assert result == {"goal": "", "steps": [{"tool": "safe_read", "description": "", "parameters": {}}]}
