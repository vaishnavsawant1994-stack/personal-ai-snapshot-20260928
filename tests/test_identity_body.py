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
    assert first.revision_id.startswith("body-v1-")


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
