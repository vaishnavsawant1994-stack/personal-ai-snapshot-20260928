from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class ExtensionManifest:
    id: str
    version: str
    publisher: str = "unknown"
    capabilities: tuple[str, ...] = ()
    requested_permissions: tuple[str, ...] = ()
    data_scopes: tuple[str, ...] = ()
    network_hosts: tuple[str, ...] = ()
    filesystem_scopes: tuple[str, ...] = ()
    background_hooks: tuple[str, ...] = ()
    endpoint: str | None = None
    signature: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.version.strip():
            raise ValueError("extension id and version are required")
        if self.endpoint and not self.endpoint.startswith("https://"):
            raise ValueError("extension endpoint must use HTTPS")
        for host in self.network_hosts:
            if "://" in host or "/" in host:
                raise ValueError("network_hosts must contain host names, not URLs")
        if len(self.requested_permissions) > 100 or len(self.capabilities) > 100:
            raise ValueError("extension manifest exceeds capability/permission limits")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "publisher": self.publisher,
            "capabilities": list(self.capabilities),
            "requested_permissions": list(self.requested_permissions),
            "data_scopes": list(self.data_scopes),
            "network_hosts": list(self.network_hosts),
            "filesystem_scopes": list(self.filesystem_scopes),
            "background_hooks": list(self.background_hooks),
            "endpoint": self.endpoint,
            "signature": self.signature,
            "metadata": dict(self.metadata),
        }

    @property
    def manifest_hash(self) -> str:
        payload = self.to_dict()
        # Signatures attest to a payload; they are not part of the payload hash.
        payload["signature"] = None
        return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ExtensionManifest":
        requested = raw.get("requested_permissions", raw.get("permissions", ()))
        return cls(
            id=str(raw.get("id") or "").strip(),
            version=str(raw.get("version") or "").strip(),
            publisher=str(raw.get("publisher") or "unknown").strip() or "unknown",
            capabilities=tuple(sorted(set(map(str, raw.get("capabilities", ())))))[:100],
            requested_permissions=tuple(sorted(set(map(str, requested or ()))) )[:100],
            data_scopes=tuple(sorted(set(map(str, raw.get("data_scopes", ())))))[:100],
            network_hosts=tuple(sorted(set(map(str, raw.get("network_hosts", ())))))[:100],
            filesystem_scopes=tuple(sorted(set(map(str, raw.get("filesystem_scopes", ())))))[:100],
            background_hooks=tuple(sorted(set(map(str, raw.get("background_hooks", ())))))[:50],
            endpoint=str(raw.get("endpoint") or "").strip() or None,
            signature=str(raw.get("signature") or "").strip() or None,
            metadata=dict(raw.get("metadata") or {}),
        )


class ExtensionGrantStore:
    """Owner-controlled grants; installation or enablement never grants access."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS extension_manifests(
                    extension_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    manifest_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    installed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS extension_grants(
                    extension_id TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    granted_by TEXT NOT NULL,
                    granted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(extension_id, permission),
                    FOREIGN KEY(extension_id) REFERENCES extension_manifests(extension_id) ON DELETE CASCADE
                );
                """
            )

    def _con(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def install(self, manifest: ExtensionManifest) -> dict[str, Any]:
        payload = manifest.to_dict()
        with self._con() as con:
            existing = con.execute(
                "SELECT version, manifest_hash FROM extension_manifests WHERE extension_id=?",
                (manifest.id,),
            ).fetchone()
            if existing is not None and str(existing["manifest_hash"]) != manifest.manifest_hash:
                # A changed package invalidates old grants; owner must re-review it.
                con.execute("DELETE FROM extension_grants WHERE extension_id=?", (manifest.id,))
            con.execute(
                """
                INSERT INTO extension_manifests(extension_id,version,manifest_hash,payload_json)
                VALUES(?,?,?,?)
                ON CONFLICT(extension_id) DO UPDATE SET
                    version=excluded.version,
                    manifest_hash=excluded.manifest_hash,
                    payload_json=excluded.payload_json,
                    installed_at=CURRENT_TIMESTAMP
                """,
                (manifest.id, manifest.version, manifest.manifest_hash, _stable(payload)),
            )
        return {
            "extension_id": manifest.id,
            "manifest_hash": manifest.manifest_hash,
            "requested_permissions": list(manifest.requested_permissions),
            "granted_permissions": self.grants(manifest.id),
            "note": "installation does not grant permissions",
        }

    def grant(self, extension_id: str, permission: str, *, actor: str) -> None:
        if str(actor) != "owner":
            raise PermissionError("only the owner may grant extension permissions")
        permission = str(permission or "").strip()
        if not permission:
            raise ValueError("permission is required")
        with self._con() as con:
            row = con.execute("SELECT payload_json FROM extension_manifests WHERE extension_id=?", (str(extension_id),)).fetchone()
            if row is None:
                raise KeyError(extension_id)
            manifest = ExtensionManifest.from_dict(json.loads(row[0]))
            if permission not in manifest.requested_permissions:
                raise PermissionError("extension did not declare this permission")
            con.execute(
                "INSERT OR IGNORE INTO extension_grants(extension_id,permission,granted_by) VALUES(?,?,?)",
                (str(extension_id), permission, "owner"),
            )

    def revoke(self, extension_id: str, permission: str, *, actor: str) -> None:
        if str(actor) != "owner":
            raise PermissionError("only the owner may revoke extension permissions")
        with self._con() as con:
            con.execute("DELETE FROM extension_grants WHERE extension_id=? AND permission=?", (str(extension_id), str(permission)))

    def grants(self, extension_id: str) -> list[str]:
        with self._con() as con:
            return [
                str(row[0])
                for row in con.execute(
                    "SELECT permission FROM extension_grants WHERE extension_id=? ORDER BY permission",
                    (str(extension_id),),
                ).fetchall()
            ]

    def is_granted(self, extension_id: str, permission: str) -> bool:
        return str(permission) in set(self.grants(extension_id))
