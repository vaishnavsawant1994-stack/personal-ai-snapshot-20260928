from __future__ import annotations

import os

from automation.work_bridge import AutomationWorkBridge
from evolution import ContinuousEvolutionRuntime
from identity import IdentityRuntime
from integrations.extension_contracts import ExtensionGrantStore
from integrations.provider_contracts import runtime_provider_inventory


def attach_e9_runtime(runtime: dict) -> dict:
    """Attach E9 convergence services after E1–E8 and P10 are fully constructed."""

    events = runtime["events"]
    trusted_release_revision = str(os.environ.get("VISHNU_TRUSTED_RELEASE_REVISION") or "").strip() or None
    trusted_release_activate = str(os.environ.get("VISHNU_TRUSTED_RELEASE_ACTIVATE") or "").strip().lower() in {"1", "true", "yes", "activate"}
    identity = IdentityRuntime(
        store=runtime["identity_store"],
        running_git_revision=runtime.get("running_git_revision"),
        events=events,
        trusted_release_revision=trusted_release_revision,
        allow_trusted_release_activation=trusted_release_activate,
    )
    runtime["identity_runtime"] = identity
    agent_executor = runtime.get("agent_executor")
    if agent_executor is not None and hasattr(agent_executor, "attach_identity_context"):
        agent_executor.attach_identity_context(identity.context_dict)

    code_body = runtime.get("code_body")
    authority = runtime.get("continuation_authority")
    if code_body is not None and authority is not None and hasattr(code_body, "attach_continuation_authority"):
        def body_mutation_guard():
            authority.assert_active()
            identity.assert_body_compatible()
        code_body.attach_continuation_authority(body_mutation_guard)

    continuous = ContinuousEvolutionRuntime(
        events=events,
        ingestor=runtime["evidence_ingestor"],
        evolution=runtime["evolution"],
        preferences=runtime.get("preferences"),
    )
    runtime["continuous_evolution"] = continuous

    work_bridge = getattr(runtime.get("advanced_autonomy"), "_work_bridge", None)
    if work_bridge is not None:
        runtime["automation_work_bridge"] = AutomationWorkBridge(
            engine=runtime["automations"],
            work_store=work_bridge.work,
            events=events,
        )
        runtime["canonical_work_store"] = work_bridge.work
        runtime["canonical_evidence_store"] = work_bridge.evidence
    else:
        runtime["automation_work_bridge"] = None
        runtime["canonical_work_store"] = None

    extension_grants = ExtensionGrantStore(runtime["settings"].data_dir / "extension-grants.sqlite3")
    runtime["extension_grants"] = extension_grants
    for plugin in runtime.get("plugins").list() if runtime.get("plugins") is not None else ():
        from integrations.extension_contracts import ExtensionManifest
        extension_grants.install(
            ExtensionManifest(
                id=plugin.id,
                version=plugin.version,
                publisher="legacy-manifest",
                capabilities=(),
                requested_permissions=tuple(plugin.permissions),
                endpoint=plugin.endpoint,
                metadata={"name": plugin.name, "description": plugin.description, "legacy_enabled": plugin.enabled},
            )
        )

    runtime["provider_inventory"] = runtime_provider_inventory(runtime)
    events.emit(
        "e9.runtime_ready",
        identity_state=identity.status().bootstrap_state,
        work_authority=getattr(getattr(runtime.get("advanced_autonomy"), "_canonical_work_authority", None), "mode", "unavailable"),
        continuous_evolution=continuous.enabled,
        providers=len(runtime["provider_inventory"]),
    )
    return runtime


def start_e9_services(runtime: dict) -> None:
    continuous = runtime.get("continuous_evolution")
    if continuous is not None:
        continuous.start()


def stop_e9_services(runtime: dict) -> None:
    continuous = runtime.get("continuous_evolution")
    if continuous is not None:
        continuous.stop()
    bridge = runtime.get("automation_work_bridge")
    if bridge is not None:
        bridge.close()
