import pytest

from identity import SelfAuthorityViolation, SelfProfile


def test_self_profile_accepts_relationship_and_behavioral_context():
    profile = SelfProfile(
        owner_relationship={"display_name": "Owner"},
        communication_style={"verbosity": "adaptive"},
        preferences={"timezone": "Europe/Berlin"},
    )

    assert profile.to_dict()["communication_style"]["verbosity"] == "adaptive"
    assert len(profile.payload_hash) == 64


@pytest.mark.parametrize(
    "payload",
    [
        {"private_context": {"permissions": {"email.send": True}}},
        {"preferences": {"bypass-approval": True}},
        {"metadata": {"security policy": "disabled"}},
        {"personality": {"nested": {"auto_merge": True}}},
    ],
)
def test_self_profile_rejects_authority_directives(payload):
    with pytest.raises(SelfAuthorityViolation):
        SelfProfile.from_dict(payload)


def test_self_profile_rejects_unknown_top_level_fields():
    with pytest.raises(ValueError, match="unknown Self fields"):
        SelfProfile.from_dict({"schema_version": 1, "tool_policy": {"allow": "*"}})
