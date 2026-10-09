from types import SimpleNamespace

from future_intelligence.work_orchestration.capabilities import CapabilityRegistry, CapabilityState


def test_qualification_manifest_cannot_cross_capability_binding():
    tool = SimpleNamespace(
        name="docs_tool",
        description="Read documents",
        capability="knowledge.read",
        connector_id="drive",
        prohibited=False,
        risk=0,
        verification_required=False,
        requires_reauth=False,
        allowed_destinations=None,
    )
    registry = SimpleNamespace(all=lambda: [tool])
    capabilities = CapabilityRegistry.from_tool_registry(
        registry,
        qualification_manifest={
            "docs_tool": {
                "capability": "communications.send",
                "state": "qualified",
                "exact_head_sha": "abc123",
                "qualification_suite": "wrong-capability-suite",
                "evidence_refs": ["ci:wrong"],
            }
        },
    )
    record = capabilities.get_tool("docs_tool")
    assert record.state is CapabilityState.AVAILABLE
    assert record.exact_head_sha is None
    assert record.qualification_suite is None
    assert record.qualification_evidence == ()
