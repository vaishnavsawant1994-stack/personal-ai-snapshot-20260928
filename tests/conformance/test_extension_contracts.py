from __future__ import annotations

import pytest

from integrations.extension_contracts import ExtensionGrantStore, ExtensionManifest


def test_extension_install_never_grants_requested_permissions(tmp_path):
    store = ExtensionGrantStore(tmp_path / "extensions.sqlite3")
    manifest = ExtensionManifest(
        id="sample",
        version="1.0.0",
        publisher="example",
        requested_permissions=("files.read", "network.send"),
        endpoint="https://example.invalid",
    )
    result = store.install(manifest)
    assert result["granted_permissions"] == []
    assert store.grants("sample") == []


def test_extension_permissions_require_owner_and_declared_scope(tmp_path):
    store = ExtensionGrantStore(tmp_path / "extensions.sqlite3")
    store.install(ExtensionManifest(id="sample", version="1.0.0", requested_permissions=("files.read",)))
    with pytest.raises(PermissionError):
        store.grant("sample", "files.read", actor="extension")
    with pytest.raises(PermissionError):
        store.grant("sample", "files.write", actor="owner")
    store.grant("sample", "files.read", actor="owner")
    assert store.is_granted("sample", "files.read")
