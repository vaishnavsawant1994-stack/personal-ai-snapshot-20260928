from __future__ import annotations

import base64
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from updates.release_sign import build_manifest
from updates.release_verify import verify
from updates.signed_updater import SignedUpdater, UpdateVerificationError

SOURCE_COMMIT = "a" * 40


def _key_pair():
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private, base64.b64encode(public_raw).decode()


def _signed_release(tmp_path: Path, *, version: str = "v2.0.0", channel: str = "stable"):
    private, public_b64 = _key_pair()
    artifact = tmp_path / f"Vishnu-{version}-linux-x64.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("app/version.txt", version)
    manifest = build_manifest(
        version=version,
        source_commit=SOURCE_COMMIT,
        channel=channel,
        artifacts=[artifact],
    )
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest_path = tmp_path / "manifest.json"
    signature_path = tmp_path / "manifest.json.sig"
    manifest_path.write_bytes(raw)
    signature_path.write_text(base64.b64encode(private.sign(raw)).decode(), encoding="utf-8")
    return private, public_b64, artifact, manifest, raw, manifest_path, signature_path


def test_schema_v2_binds_source_channel_platform_architecture_and_hash(tmp_path: Path):
    _, public_b64, artifact, manifest, _, manifest_path, signature_path = _signed_release(tmp_path)
    verified = verify(
        manifest_path,
        signature_path,
        public_b64,
        tmp_path,
        expected_version="v2.0.0",
        expected_source_commit=SOURCE_COMMIT,
        expected_channel="stable",
        expected_platform="linux",
        expected_architecture="x86_64",
    )
    assert verified["schema"] == 2
    assert verified["source_commit"] == SOURCE_COMMIT
    assert verified["artifacts"][0]["platform"] == "linux"
    assert verified["artifacts"][0]["architecture"] == "x86_64"

    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="(size|sha256) mismatch"):
        verify(manifest_path, signature_path, public_b64, tmp_path)


def test_verifier_rejects_tampered_signature_and_schema_v1(tmp_path: Path):
    private, public_b64, _, manifest, raw, manifest_path, signature_path = _signed_release(tmp_path)
    signature_path.write_text(base64.b64encode(b"x" * 64).decode(), encoding="utf-8")
    with pytest.raises(ValueError, match="signature invalid"):
        verify(manifest_path, signature_path, public_b64, tmp_path)

    weak = {"schema": 1, "version": manifest["version"], "artifacts": manifest["artifacts"]}
    weak_raw = json.dumps(weak, sort_keys=True, separators=(",", ":")).encode()
    manifest_path.write_bytes(weak_raw)
    signature_path.write_text(base64.b64encode(private.sign(weak_raw)).decode(), encoding="utf-8")
    with pytest.raises(ValueError, match="schema 2"):
        verify(manifest_path, signature_path, public_b64, tmp_path)

    # Restore proves the original signed bytes are still valid after the negative cases.
    manifest_path.write_bytes(raw)
    signature_path.write_text(base64.b64encode(private.sign(raw)).decode(), encoding="utf-8")
    assert verify(manifest_path, signature_path, public_b64, tmp_path)["schema"] == 2


def test_updater_rejects_wrong_channel_platform_architecture_and_downgrade(tmp_path: Path):
    _, public_b64, _, _, raw, _, signature_path = _signed_release(tmp_path, version="v2.0.0")
    signature_b64 = signature_path.read_text(encoding="utf-8")

    updater = SignedUpdater(
        public_b64,
        tmp_path / "install",
        current_version="v1.9.9",
        platform_name="linux",
        architecture="x64",
        channel="stable",
    )
    manifest = updater.verify_manifest(raw, signature_b64)
    assert updater.choose_artifact(manifest, package_type="zip")["platform"] == "linux"

    wrong_platform = SignedUpdater(
        public_b64,
        tmp_path / "install-windows",
        current_version="v1.0.0",
        platform_name="windows",
        architecture="x64",
    )
    with pytest.raises(UpdateVerificationError, match="found 0"):
        wrong_platform.choose_artifact(wrong_platform.verify_manifest(raw, signature_b64), package_type="zip")

    wrong_channel = SignedUpdater(
        public_b64,
        tmp_path / "install-beta",
        current_version="v1.0.0",
        platform_name="linux",
        architecture="x64",
        channel="beta",
    )
    with pytest.raises(UpdateVerificationError, match="channel"):
        wrong_channel.verify_manifest(raw, signature_b64)

    downgrade = SignedUpdater(
        public_b64,
        tmp_path / "install-newer",
        current_version="v3.0.0",
        platform_name="linux",
        architecture="x64",
    )
    with pytest.raises(UpdateVerificationError, match="not newer"):
        downgrade.verify_manifest(raw, signature_b64)


def test_failed_post_update_health_check_restores_previous_install(tmp_path: Path):
    _, public_b64 = _key_pair()
    install = tmp_path / "install"
    install.mkdir()
    (install / "state.txt").write_text("old", encoding="utf-8")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "state.txt").write_text("new", encoding="utf-8")
    (stage / "new-file.txt").write_text("new", encoding="utf-8")
    updater = SignedUpdater(public_b64, install, platform_name="linux", architecture="x64")

    with pytest.raises(RuntimeError, match="health check failed"):
        updater.install_staged(stage, health_check=lambda _: False)

    assert (install / "state.txt").read_text(encoding="utf-8") == "old"
    assert not (install / "new-file.txt").exists()


def test_update_zip_rejects_path_traversal(tmp_path: Path):
    _, public_b64 = _key_pair()
    malicious = tmp_path / "Vishnu-v2.0.0-linux-x64.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("../escape.txt", "no")
    import hashlib

    digest = hashlib.sha256(malicious.read_bytes()).hexdigest()
    updater = SignedUpdater(public_b64, tmp_path / "install", platform_name="linux", architecture="x64")
    with pytest.raises(UpdateVerificationError, match="unsafe zip path"):
        updater.stage_zip(malicious, digest, malicious.stat().st_size)
    assert not (tmp_path / "escape.txt").exists()
