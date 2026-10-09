from __future__ import annotations

import base64
import hashlib
import hmac
import os
import platform
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from security.keychain import RootKeyStore

from .models import AuthorityLease
from .store import ContinuityAuthorityError, ContinuityStore


def default_host_id() -> str:
    """Return a stable, non-secret host identity that is never restored from backup."""

    explicit = str(os.getenv("VISHNU_HOST_ID") or "").strip()
    if explicit:
        return explicit[:200]
    material = f"{platform.system()}|{platform.node()}|{uuid.getnode()}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"host-{digest}"


@dataclass
class HostContinuationAuthority:
    """Host-local credential facade over the durable single continuation slot.

    The credential is deterministically derived from the host's owner root key,
    host id and authority epoch. Only its SHA-256 hash is stored in SQLite. The
    root key and raw authority credential never enter checkpoints or transfer
    bundles.
    """

    store: ContinuityStore
    host_id: str
    root_key_store: RootKeyStore
    ttl_seconds: int = 300
    _epoch: int | None = None

    def __init__(
        self,
        store: ContinuityStore,
        *,
        host_id: str | None = None,
        root_key_store: RootKeyStore | None = None,
        ttl_seconds: int = 300,
    ) -> None:
        self.store = store
        self.host_id = str(host_id or default_host_id()).strip()
        if not self.host_id:
            raise ValueError("host_id is required")
        self.root_key_store = root_key_store or RootKeyStore()
        self.ttl_seconds = max(30, int(ttl_seconds))
        self._epoch = None

    def _root_key(self) -> bytes:
        key = self.root_key_store.get_or_create()
        if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
            raise ContinuityAuthorityError("owner root key is unavailable for continuation authority")
        return bytes(key)

    def token_for_epoch(self, epoch: int) -> str:
        if int(epoch) < 1:
            raise ValueError("authority epoch must be positive")
        message = f"vishnu-continuation-authority-v1\0{self.host_id}\0{int(epoch)}".encode("utf-8")
        digest = hmac.new(self._root_key(), message, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def bootstrap_or_resume(self) -> AuthorityLease:
        current = self.store.current_authority()
        if current is None:
            epoch = 1
        else:
            if str(current["host_id"]) != self.host_id:
                raise ContinuityAuthorityError("continuation authority belongs to another host")
            if str(current["status"]) != "active":
                raise ContinuityAuthorityError("this host is fenced from continuation authority")
            epoch = int(current["epoch"])
        token = self.token_for_epoch(epoch)
        lease = self.store.bootstrap(
            host_id=self.host_id,
            token=token,
            ttl_seconds=self.ttl_seconds,
        )
        self._epoch = lease.epoch
        return lease

    def assert_active(self) -> AuthorityLease:
        current = self.store.current_authority()
        if current is None:
            raise ContinuityAuthorityError("continuation authority is not initialized")
        if str(current["host_id"]) != self.host_id:
            raise ContinuityAuthorityError("continuation authority belongs to another host")
        if str(current["status"]) != "active":
            raise ContinuityAuthorityError("this host is fenced from continuation authority")
        epoch = int(current["epoch"])
        token = self.token_for_epoch(epoch)

        # Idle time must not permanently strand a healthy same-host runtime. If
        # the lease elapsed without an explicit transfer/fence, re-prove the same
        # host+epoch credential and renew lazily. A fenced source or a target-owned
        # authority fails before this branch and can never self-resume.
        expires_at = datetime.fromisoformat(str(current["expires_at"])).astimezone(timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            lease = self.store.bootstrap(
                host_id=self.host_id,
                token=token,
                ttl_seconds=self.ttl_seconds,
            )
        else:
            lease = self.store.assert_active(
                host_id=self.host_id,
                epoch=epoch,
                token=token,
            )
        self._epoch = lease.epoch
        return lease

    def renew(self) -> AuthorityLease:
        lease = self.assert_active()
        renewed = self.store.renew(
            host_id=self.host_id,
            epoch=lease.epoch,
            token=self.token_for_epoch(lease.epoch),
            ttl_seconds=self.ttl_seconds,
        )
        self._epoch = renewed.epoch
        return renewed

    def fence_for_transfer(self, grant_id: str) -> None:
        lease = self.assert_active()
        self.store.fence_for_transfer(
            grant_id=str(grant_id),
            host_id=self.host_id,
            epoch=lease.epoch,
            token=self.token_for_epoch(lease.epoch),
        )
        self._epoch = None

    def target_token(self, epoch: int) -> str:
        """Derive the credential a target host will bind when consuming a grant."""

        return self.token_for_epoch(epoch)
