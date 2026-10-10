from __future__ import annotations

from typing import Iterable

from future_intelligence.work_orchestration.capabilities import (
    CapabilityRecord,
    CapabilityRegistry,
    CapabilityState,
    capability_tokens,
    normalize_capability,
)
from future_intelligence.work_orchestration.models import ReadinessStatus, WorkOrder, WorkPlan

from .defaults import DEFAULT_WORKERS
from .models import WorkerAssessment, WorkerAssignment, WorkerProfile


class WorkerRegistry:
    """Deterministic role registry. Workers never execute tools directly."""

    def __init__(self, profiles: Iterable[WorkerProfile] = DEFAULT_WORKERS) -> None:
        items = tuple(profiles)
        self._profiles = {profile.id: profile for profile in items}
        if len(self._profiles) != len(items):
            raise ValueError("worker ids must be unique")

    @classmethod
    def default(cls) -> "WorkerRegistry":
        return cls(DEFAULT_WORKERS)

    def all(self) -> tuple[WorkerProfile, ...]:
        return tuple(self._profiles.values())

    def get(self, worker_id: str) -> WorkerProfile | None:
        return self._profiles.get(str(worker_id))

    @staticmethod
    def _profile_tokens(profile: WorkerProfile) -> set[str]:
        return set(capability_tokens(profile.id, *profile.supported_capabilities))

    def _tool_compatible(self, profile: WorkerProfile, record: CapabilityRecord) -> bool:
        if profile.allow_any_available_tool:
            return True
        return bool(self._profile_tokens(profile) & set(record.tags))

    def _candidate_tools(self, profile: WorkerProfile, capabilities: CapabilityRegistry) -> tuple[str, ...]:
        if not capabilities.source_available or not profile.can_propose_tools:
            return ()
        if profile.allow_any_available_tool:
            return capabilities.available_tool_names()
        return tuple(
            record.tool_name
            for record in capabilities.available()
            if self._tool_compatible(profile, record)
        )

    def assess_order(self, order: WorkOrder, capabilities: CapabilityRegistry) -> tuple[WorkerAssignment | None, list[str], list[str]]:
        blockers: list[str] = []
        warnings: list[str] = []
        profile = self.get(order.worker_type)
        if profile is None:
            return None, [f"{order.id} requests unknown worker role {order.worker_type}"], warnings

        metadata = order.resource_scope.metadata
        requested_tool = str(metadata.get("requested_tool") or "").strip()
        parent_capabilities = tuple(
            str(item)
            for item in (metadata.get("allowed_capabilities") or ())
            if str(item).strip()
        )
        selected: CapabilityRecord | None = None
        if profile.requires_tool and not requested_tool:
            blockers.append(f"{order.id} uses worker role {profile.id} but does not select a tool")
        if requested_tool:
            if not profile.can_propose_tools:
                blockers.append(f"{order.id} worker role {profile.id} cannot propose tools")
            elif not capabilities.source_available:
                blockers.append(f"{order.id} selects tool {requested_tool} but ToolRegistry is unavailable")
            else:
                selected = capabilities.get_tool(requested_tool)
                if selected is None or not selected.available:
                    blockers.append(f"{order.id} selects unavailable tool {requested_tool}")
                elif not self._tool_compatible(profile, selected):
                    blockers.append(f"{order.id} tool {requested_tool} is incompatible with worker role {profile.id}")
                elif selected.state is CapabilityState.EXPERIMENTAL:
                    warnings.append(f"{order.id} selects experimental tool {requested_tool}")

        profile_tokens = self._profile_tokens(profile)
        selected_tokens = set(selected.tags) if selected is not None else set()
        matched: list[str] = []
        for requirement in order.allowed_capabilities:
            normalized = normalize_capability(requirement)
            if profile.allow_any_available_tool and selected is not None:
                if selected.matches(requirement) or normalized in selected_tokens:
                    matched.append(requirement)
                else:
                    blockers.append(
                        f"{order.id} generic tool {selected.tool_name} does not advertise required capability {requirement}"
                    )
                continue
            if normalized in profile_tokens or normalized in selected_tokens or (selected is not None and selected.matches(requirement)):
                matched.append(requirement)
            else:
                blockers.append(f"{order.id} worker role {profile.id} does not support required capability {requirement}")

        if requested_tool and not order.allowed_capabilities and parent_capabilities:
            aligned = False
            role_scope = normalize_capability(profile.id)
            for requirement in parent_capabilities:
                normalized = normalize_capability(requirement)
                explicit_tool_match = selected is not None and (
                    selected.matches(requirement) or normalized in selected_tokens
                )
                broad_role_match = (
                    selected is not None
                    and normalized == role_scope
                    and self._tool_compatible(profile, selected)
                )
                if profile.allow_any_available_tool:
                    aligned = aligned or bool(explicit_tool_match)
                else:
                    aligned = aligned or bool(explicit_tool_match or broad_role_match)
            if not aligned:
                blockers.append(
                    f"{order.id} selected tool {requested_tool} is outside the goal capability scope"
                )

        candidate_tools = self._candidate_tools(profile, capabilities)
        assignment = WorkerAssignment(
            work_order_id=order.id,
            worker_id=profile.id,
            selected_tool=requested_tool or None,
            candidate_tools=candidate_tools[:20],
            matched_capabilities=tuple(matched),
            metadata={
                "tool_registry_available": capabilities.source_available,
                "role_only": not bool(requested_tool),
                "parent_capability_scope_present": bool(parent_capabilities),
                "intelligence": {
                    "agent_role": profile.id,
                    "routing_policy": profile.routing_policy,
                    "required_model_capabilities": list(profile.required_model_capabilities),
                    "preferred_model_capabilities": list(profile.preferred_model_capabilities),
                    "parallelizable": profile.parallelizable,
                    "deliberation_mode": profile.deliberation_mode,
                    "model_is_authority": False,
                },
            },
        )
        return assignment, blockers, warnings

    def assess_plan(self, plan: WorkPlan, capabilities: CapabilityRegistry) -> WorkerAssessment:
        assignments: list[WorkerAssignment] = []
        blockers: list[str] = []
        warnings: list[str] = []
        for order in plan.work_orders:
            assignment, order_blockers, order_warnings = self.assess_order(order, capabilities)
            if assignment is not None:
                assignments.append(assignment)
            blockers.extend(order_blockers)
            warnings.extend(order_warnings)
        blockers = list(dict.fromkeys(blockers))
        warnings = list(dict.fromkeys(warnings))
        status = ReadinessStatus.HOLD if blockers else ReadinessStatus.DEGRADED if warnings else ReadinessStatus.READY
        score = max(0.0, 100.0 - 25.0 * len(blockers) - 5.0 * len(warnings))
        return WorkerAssessment(
            status=status,
            score=score,
            assignments=tuple(assignments),
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )

    def status(self) -> dict[str, object]:
        return {
            "profiles": len(self._profiles),
            "worker_ids": list(self._profiles),
            "authority": "proposal_only",
            "execution_authority": "existing_p10_p6_tool_registry",
            "intelligence_profiles": {
                profile.id: {
                    "routing_policy": profile.routing_policy,
                    "required_model_capabilities": list(profile.required_model_capabilities),
                    "preferred_model_capabilities": list(profile.preferred_model_capabilities),
                    "parallelizable": profile.parallelizable,
                    "deliberation_mode": profile.deliberation_mode,
                }
                for profile in self._profiles.values()
            },
        }
