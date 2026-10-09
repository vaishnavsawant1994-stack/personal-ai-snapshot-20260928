from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from continuity import (
    ContinuityBundleError,
    ContinuityCheckpoint,
    PortableContinuityBundleCodec,
    TransferGrant,
)


def _checkpoint() -> ContinuityCheckpoint:
    return ContinuityCheckpoint(
        id="ccp-bundle",
        source_host_id="source-host",
        authority_epoch=4,
        backup_filename="source.paibackup",
        backup_sha256="a" * 64,
        backup_size=555,
        payload_sha256="b" * 64,
        data_manifest_hash="c" * 64,
        active_body_revision_id="body-1",
        active_body_git_revision="0123456789abcdef",
        schema_versions={"identity": (1,), "work": (3,)},
    )


def _grant(checkpoint: ContinuityCheckpoint) -> TransferGrant:
    now = datetime.now(timezone.utc)
    return TransferGrant(
        id="ctg-bundle",
        checkpoint_id=checkpoint.id,
        source_host_id=checkpoint.source_host_id,
        target_host_id="target-host",
        source_epoch=checkpoint.authority_epoch,
        token="transfer-token-" + "z" * 64,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=15)).isoformat(),
    )


def test_portable_bundle_roundtrip_authenticates_header_and_payload(tmp_path):
    codec = PortableContinuityBundleCodec()
    payload = tmp_path / "payload.zip"
    payload.write_bytes((b"private-state\0" * 1000) + b"evidence")
    checkpoint = _checkpoint()
    grant = _grant(checkpoint)
    bundle = tmp_path / "handoff.vcontinuity"

    codec.encrypt_payload(payload, bundle, checkpoint=checkpoint, grant=grant)
    raw = bundle.read_bytes()
    assert grant.token.encode() not in raw
    assert b"transfer-token" not in raw

    restored, header = codec.decrypt_payload(bundle, token=grant.token)
    try:
        assert restored.read_bytes() == payload.read_bytes()
        assert header["grant"]["id"] == grant.id
        assert header["grant"]["target_host_id"] == "target-host"
        assert "token" not in header["grant"]
        assert header["checkpoint"]["checkpoint_hash"] == checkpoint.checkpoint_hash
    finally:
        restored.unlink(missing_ok=True)


def test_wrong_transfer_token_cannot_decrypt_bundle(tmp_path):
    codec = PortableContinuityBundleCodec()
    payload = tmp_path / "payload.zip"
    payload.write_bytes(b"payload")
    checkpoint = _checkpoint()
    grant = _grant(checkpoint)
    bundle = tmp_path / "handoff.vcontinuity"
    codec.encrypt_payload(payload, bundle, checkpoint=checkpoint, grant=grant)

    with pytest.raises(ContinuityBundleError, match="authentication failed"):
        codec.decrypt_payload(bundle, token="wrong-token-" + "q" * 64)


def test_bundle_tampering_is_rejected(tmp_path):
    codec = PortableContinuityBundleCodec()
    payload = tmp_path / "payload.zip"
    payload.write_bytes(b"payload" * 100)
    checkpoint = _checkpoint()
    grant = _grant(checkpoint)
    bundle = tmp_path / "handoff.vcontinuity"
    codec.encrypt_payload(payload, bundle, checkpoint=checkpoint, grant=grant)

    raw = bytearray(bundle.read_bytes())
    raw[-20] ^= 0x01
    bundle.write_bytes(raw)
    with pytest.raises(ContinuityBundleError, match="authentication failed"):
        codec.decrypt_payload(bundle, token=grant.token)
