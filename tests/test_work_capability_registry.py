from __future__ import annotations

from future_intelligence.work_orchestration.capabilities import CapabilityRegistry, CapabilityState


class _Tool:
    def __init__(self, name, *, capability=None, connector_id=None, prohibited=False, qualification_state=None):
        self.name = name
        self.description = name
        self.capability = capability
        self.connector_id = connector_id
        self.prohibited = prohibited
        self.qualification_state = qualification_state
        self.risk = 2
        self.verification_required = True
        self.requires_reauth = False
        self.allowed_destinations = ("example.com",)


class _Registry:
    def all(self):
        return [
            _Tool("gmail_send", capability="email.send", connector_id="gmail", qualification_state="qualified"),
            _Tool("blocked_admin", capability="admin", prohibited=True),
        ]


def test_capability_registry_projects_tool_metadata_without_authority():
    registry = CapabilityRegistry.from_tool_registry(_Registry())
    assert registry.source_available is True
    assert registry.available_tool_names() == ("gmail_send",)
    gmail = registry.get_tool("gmail_send")
    assert gmail is not None
    assert gmail.state is CapabilityState.QUALIFIED
    assert gmail.matches("email")
    assert gmail.matches("send")
    assert gmail.verification_required is True
    assert registry.get_tool("blocked_admin").state is CapabilityState.DISABLED
    assert registry.status()["execution_authority"] == "existing_tool_registry"


def test_capability_registry_fails_closed_when_source_is_missing():
    registry = CapabilityRegistry.from_tool_registry(None)
    assert registry.source_available is False
    assert registry.available_tool_names() == ()
