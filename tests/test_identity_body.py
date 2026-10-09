from pathlib import Path

import pytest

from identity import BodyManifest


def test_repository_body_manifest_loads_and_hash_is_stable():
    path = Path(__file__).resolve().parents[1] / "config" / "vishnu-body.yaml"
    first = BodyManifest.load(path)
    second = BodyManifest.load(path)

    assert first.identity["name"] == "Vishnu"
    assert first.identity["role"] == "personal_ai"
    assert first.contracts["evidence"] == 2
    assert first.manifest_hash == second.manifest_hash
    assert first.manifest_id.startswith("body-v1-")
    assert first.revision_id_for("commit-a") != first.revision_id_for("commit-b")


def test_body_manifest_rejects_invalid_contract_versions():
    with pytest.raises(ValueError, match="positive integer"):
        BodyManifest.from_dict(
            {
                "body_version": 1,
                "identity": {"name": "Vishnu", "role": "personal_ai"},
                "contracts": {"work": 0},
                "mission": ["help"],
            }
        )


def test_body_revision_id_requires_governed_revision():
    manifest = BodyManifest.from_dict(
        {
            "body_version": 1,
            "identity": {"name": "Vishnu", "role": "personal_ai"},
            "contracts": {"work": 1},
            "mission": ["help"],
        }
    )
    with pytest.raises(ValueError, match="git_revision"):
        manifest.revision_id_for("")
