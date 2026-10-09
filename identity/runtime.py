from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .body import BodyManifest, BodyRevisionStatus
from .context import compose_identity_context
from .self_model import SelfProfile
from .store import IdentityStore


@dataclass(frozen=True)
class IdentityRuntimeStatus:
    manifest_id: str
    running_git_revision: str | None
    active_revision_id: str | None
    active_git_revision: str | None
    body_compatible: bool | None
    self_version: int | None
    bootstrap_state: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "running_git_revision": self.running_git_revision,
            "active_revision_id": self.active_revision_id,
            "active_git_revision": self.active_git_revision,
            "body_compatible": self.body_compatible,
            "self_version": self.self_version,
            "bootstrap_state": self.bootstrap_state,
        }


class IdentityRuntime:
    """Live Body/Self context with a strict no-authority boundary.

    The first exact running revision may establish the initial Body baseline only
    when the lineage database is empty. Once lineage exists, this runtime never
    auto-activates a different revision; adoption remains an owner-governed E7
    operation.
    """

    def __init__(
        self,
        *,
        store: IdentityStore,
        running_git_revision: str | None,
        body_manifest_path: str | Path | None = None,
        events=None,
    ) -> None:
        self.store = store
        self.running_git_revision = str(running_git_revision or "").strip() or None
        self.events = events
        if body_manifest_path is None:
            body_manifest_path = Path(__file__).resolve().parents[1] / "config" / "vishnu-body.yaml"
        self.body_manifest_path = Path(body_manifest_path)
        self.body = BodyManifest.load(self.body_manifest_path)
        self._bootstrap_state = "uninitialized"
        self._bootstrap()

    def _emit(self, event: str, **payload: Any) -> None:
        if self.events is not None:
            self.events.emit(event, **payload)

    def _body_count(self) -> int:
        row = self.store.connection.execute("SELECT COUNT(*) FROM software_body_revisions").fetchone()
        return int(row[0]) if row else 0

    def _bootstrap(self) -> None:
        active = self.store.active_body_revision()
        count = self._body_count()
        if active is None and count == 0 and self.running_git_revision:
            revision_id = self.store.record_body_revision(
                self.body,
                git_revision=self.running_git_revision,
                status=BodyRevisionStatus.CANDIDATE,
            )
            self.store.activate_body_revision(revision_id, actor="trusted_runtime_baseline_bootstrap")
            self.store.set_state("baseline_body_initialized", {"revision_id": revision_id})
            self._bootstrap_state = "baseline_initialized"
            self._emit("identity.body_baseline_initialized", revision_id=revision_id)
            return
        if active is None and count > 0:
            self._bootstrap_state = "lineage_present_no_active_body"
            self._emit("identity.body_activation_required", revision_count=count)
            return
        if active is None:
            self._bootstrap_state = "exact_running_revision_unavailable"
            self._emit("identity.body_revision_unknown")
            return
        if self.running_git_revision and str(active.get("git_revision")) != self.running_git_revision:
            self._bootstrap_state = "running_body_mismatch"
            self._emit(
                "identity.body_mismatch",
                active_revision_id=str(active.get("revision_id")),
                active_git_revision=str(active.get("git_revision")),
                running_git_revision=self.running_git_revision,
            )
            return
        self._bootstrap_state = "ready" if self.running_git_revision else "active_body_running_revision_unknown"

    def status(self) -> IdentityRuntimeStatus:
        active = self.store.active_body_revision()
        latest = self.store.latest_self_version()
        if active is None or self.running_git_revision is None:
            compatible: bool | None = None
        else:
            compatible = str(active.get("git_revision")) == self.running_git_revision
        return IdentityRuntimeStatus(
            manifest_id=self.body.manifest_id,
            running_git_revision=self.running_git_revision,
            active_revision_id=str(active.get("revision_id")) if active else None,
            active_git_revision=str(active.get("git_revision")) if active else None,
            body_compatible=compatible,
            self_version=int(latest[0]) if latest else None,
            bootstrap_state=self._bootstrap_state,
        )

    def assert_body_compatible(self) -> dict[str, Any]:
        status = self.status()
        if not self.running_git_revision:
            raise RuntimeError("exact running Body revision is unavailable")
        if not status.active_revision_id:
            raise RuntimeError("no active Body revision is registered")
        if status.body_compatible is not True:
            raise RuntimeError("running revision does not match the active Body revision")
        active = self.store.active_body_revision()
        if active is None:
            raise RuntimeError("active Body revision disappeared")
        return active

    def context_envelope(self):
        active = self.store.active_body_revision()
        latest = self.store.latest_self_version()
        profile = latest[1] if latest else None
        return compose_identity_context(
            self.body,
            profile,
            active_body_revision=str(active.get("revision_id")) if active else None,
        )

    def context_dict(self) -> dict[str, Any]:
        envelope = self.context_envelope().to_dict()
        status = self.status()
        envelope["runtime"] = {
            "body_compatible": status.body_compatible,
            "manifest_id": status.manifest_id,
            "self_version": status.self_version,
        }
        return envelope

    def update_self(self, payload: dict[str, Any], *, actor: str = "owner") -> tuple[int, SelfProfile]:
        profile = SelfProfile.from_dict(payload)
        version = self.store.append_self_version(profile, created_by=str(actor or "owner"))
        self._emit("identity.self_updated", version=version, actor=str(actor or "owner"))
        return version, profile
