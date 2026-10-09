from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from continuity import (
    ContinuityAuthorityError,
    ContinuityCheckpoint,
    ContinuityStore,
    HostContinuationAuthority,
    TransferGrant,
)


class FixedKeyStore:
    def __init__(self, key: bytes):
        self.key = key

    def get_or_create(self):
        return self.key


def _checkpoint(host: str, epoch: int) -> ContinuityCheckpoint:
    return ContinuityCheckpoint(
        id="ccp-test",
        source_host_id=host,
        authority_epoch=epoch,
        backup_filename="snapshot.paibackup",
        backup_sha256="a" * 64,
        backup_size=123,
        payload_sha256="b" * 64,
        data_manifest_hash="c" * 64,
        active_body_revision_id=None,
        active_body_git_revision="deadbeef",
        schema_versions={"identity": (1,), "work": (3,)},
    )


def _grant(checkpoint: ContinuityCheckpoint, token: str = "G" * 64) -> TransferGrant:
    now = datetime.now(timezone.utc)
    return TransferGrant(
        id="ctg-test",
        checkpoint_id=checkpoint.id,
        source_host_id=checkpoint.source_host_id,
        target_host_id="target-host",
        source_epoch=checkpoint.authority_epoch,
        token=token,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=10)).isoformat(),
    )


def test_single_host_authority_fences_source_and_transfers_epoch(tmp_path):
    store = ContinuityStore(tmp_path / "agent-continuity.sqlite3")
    source = HostContinuationAuthority(
        store,
        host_id="source-host",
        root_key_store=FixedKeyStore(b"S" * 32),
    )
    target = HostContinuationAuthority(
        store,
        host_id="target-host",
        root_key_store=FixedKeyStore(b"T" * 32),
    )

    lease = source.bootstrap_or_resume()
    assert lease.epoch == 1
    assert source.assert_active().host_id == "source-host"
    with pytest.raises(ContinuityAuthorityError):
        target.bootstrap_or_resume()

    checkpoint = _checkpoint("source-host", lease.epoch)
    store.record_checkpoint(checkpoint)
    grant = _grant(checkpoint)
    store.prepare_transfer_grant(grant)
    source.fence_for_transfer(grant.id)

    with pytest.raises(ContinuityAuthorityError):
        source.assert_active()
    with pytest.raises(ContinuityAuthorityError):
        store.consume_transfer(
            grant_id=grant.id,
            grant_token="wrong" * 16,
            target_host_id="target-host",
            target_authority_token=target.target_token(2),
        )
    with pytest.raises(ContinuityAuthorityError):
        store.consume_transfer(
            grant_id=grant.id,
            grant_token=grant.token,
            target_host_id="other-host",
            target_authority_token=target.target_token(2),
        )

    target_lease = store.consume_transfer(
        grant_id=grant.id,
        grant_token=grant.token,
        target_host_id="target-host",
        target_authority_token=target.target_token(2),
    )
    assert target_lease.epoch == 2
    assert target.assert_active().epoch == 2
    with pytest.raises(ContinuityAuthorityError):
        source.assert_active()
    with pytest.raises(ContinuityAuthorityError):
        store.consume_transfer(
            grant_id=grant.id,
            grant_token=grant.token,
            target_host_id="target-host",
            target_authority_token=target.target_token(2),
        )


def test_authority_and_grant_credentials_are_never_persisted_raw(tmp_path):
    database = tmp_path / "agent-continuity.sqlite3"
    store = ContinuityStore(database)
    source = HostContinuationAuthority(
        store,
        host_id="source-host",
        root_key_store=FixedKeyStore(b"K" * 32),
    )
    lease = source.bootstrap_or_resume()
    checkpoint = _checkpoint("source-host", lease.epoch)
    store.record_checkpoint(checkpoint)
    grant = _grant(checkpoint, token="transfer-secret-" + "x" * 64)
    store.prepare_transfer_grant(grant)

    persisted = database.read_bytes()
    assert source.token_for_epoch(1).encode() not in persisted
    assert grant.token.encode() not in persisted
    assert b"K" * 32 not in persisted


def test_same_host_lazily_renews_expired_lease_but_transfer_still_fences_it(tmp_path):
    store = ContinuityStore(tmp_path / "agent-continuity.sqlite3")
    source = HostContinuationAuthority(
        store,
        host_id="source-host",
        root_key_store=FixedKeyStore(b"S" * 32),
        ttl_seconds=30,
    )
    lease = source.bootstrap_or_resume()
    with store._con() as connection:
        connection.execute(
            "UPDATE continuation_authority SET expires_at=? WHERE slot=1",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
        )

    renewed = source.assert_active()
    assert renewed.host_id == "source-host"
    assert renewed.epoch == lease.epoch
    assert datetime.fromisoformat(renewed.expires_at) > datetime.now(timezone.utc)

    checkpoint = _checkpoint("source-host", renewed.epoch)
    store.record_checkpoint(checkpoint)
    grant = _grant(checkpoint)
    store.prepare_transfer_grant(grant)
    source.fence_for_transfer(grant.id)
    with pytest.raises(ContinuityAuthorityError, match="fenced"):
        source.assert_active()

    other = HostContinuationAuthority(
        store,
        host_id="other-host",
        root_key_store=FixedKeyStore(b"O" * 32),
    )
    with pytest.raises(ContinuityAuthorityError):
        other.bootstrap_or_resume()
