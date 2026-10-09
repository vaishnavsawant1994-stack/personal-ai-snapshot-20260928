from identity import BodyManifest, BodyRevisionStatus, IdentityStore, SelfProfile


def _body(version: int, *, work: int = 1) -> BodyManifest:
    return BodyManifest.from_dict(
        {
            "body_version": version,
            "identity": {"name": "Vishnu", "role": "personal_ai"},
            "contracts": {
                "work": work,
                "evidence": 2,
                "evolution": 1,
                "continuity": 1,
                "extension": 1,
            },
            "mission": ["assist the owner"],
        }
    )


def test_self_history_is_append_only():
    with IdentityStore() as store:
        first = SelfProfile(preferences={"density": "comfortable"})
        second = SelfProfile(preferences={"density": "compact"})

        v1 = store.append_self_version(first, created_by="owner")
        v2 = store.append_self_version(second, created_by="owner")

        assert (v1, v2) == (1, 2)
        assert store.get_self_version(1) == first
        assert store.latest_self_version() == (2, second)
        assert len(store.list_events(event_type="self.version.created")) == 2


def test_body_activation_preserves_lineage_and_supersedes_prior_active_revision():
    with IdentityStore() as store:
        first = _body(1)
        second = _body(2, work=2)
        first_id = store.record_body_revision(first, git_revision="aaa")
        second_id = store.record_body_revision(second, git_revision="bbb")

        store.activate_body_revision(first_id, actor="owner")
        assert store.active_body_revision()["revision_id"] == first_id

        store.activate_body_revision(second_id, actor="owner")

        assert store.active_body_revision()["revision_id"] == second_id
        assert store.get_body_revision(first_id)["status"] == BodyRevisionStatus.SUPERSEDED.value
        assert store.get_body_revision(second_id)["status"] == BodyRevisionStatus.ACTIVE.value
        assert len(store.list_events(event_type="body.revision.activated")) == 2


def test_identity_state_is_transactional_key_value_state():
    with IdentityStore() as store:
        store.set_state("runtime_instance_id", {"value": "runtime-1"})
        assert store.get_state("runtime_instance_id") == {"value": "runtime-1"}
        assert store.get_state("missing", "fallback") == "fallback"
