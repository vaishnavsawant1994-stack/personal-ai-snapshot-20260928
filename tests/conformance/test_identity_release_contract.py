from __future__ import annotations

from identity import IdentityRuntime, IdentityStore


def _manifest(path):
    path.write_text('{"body_version":2,"identity":{"name":"Vishnu","role":"personal_ai"},"contracts":{"work":3,"evidence":3,"evolution":1,"continuity":1,"extension":2},"mission":["assist owner"],"principles":["no self authority"]}',encoding="utf-8")


def test_existing_body_mismatch_requires_exact_operator_release_signal(tmp_path):
    manifest=tmp_path/"body.yaml";_manifest(manifest);store=IdentityStore(tmp_path/"identity.sqlite3")
    IdentityRuntime(store=store,running_git_revision="a"*40,body_manifest_path=manifest)
    blocked=IdentityRuntime(store=store,running_git_revision="b"*40,body_manifest_path=manifest)
    assert blocked.status().body_compatible is False
    wrong=IdentityRuntime(store=store,running_git_revision="b"*40,body_manifest_path=manifest,trusted_release_revision="c"*40,allow_trusted_release_activation=True)
    assert wrong.status().body_compatible is False
    adopted=IdentityRuntime(store=store,running_git_revision="b"*40,body_manifest_path=manifest,trusted_release_revision="b"*40,allow_trusted_release_activation=True)
    assert adopted.status().body_compatible is True
    assert adopted.status().bootstrap_state == "trusted_release_activated"
