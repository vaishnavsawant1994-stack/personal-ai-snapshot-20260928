from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass

from .models import AgentVersionState


@dataclass(frozen=True)
class AgentEvolutionCandidate:
    template_id: str
    parent_version_id: str
    candidate_version_id: str
    version: str
    observation_ids: tuple[str, ...]


class AgentEvolutionRuntime:
    """Continuously turns verified lessons into non-authoritative vNext candidates.

    The runtime is intentionally unable to promote, deploy or grant capabilities.
    It only synthesizes a candidate instruction revision from evidence-backed
    observations belonging to the currently preferred/stable agent version.
    Stable/preferred adoption still goes through AgentWorkforceService's explicit
    qualification gate.
    """

    def __init__(
        self,
        workforce,
        *,
        events=None,
        enabled: bool | None = None,
        observation_threshold: int = 3,
        interval_seconds: float = 60.0,
    ):
        if enabled is None:
            raw = str(os.environ.get("VISHNU_AGENT_EVOLUTION_ENABLED", "1")).strip().lower()
            enabled = raw not in {"0", "false", "no", "off", "disabled"}
        self.workforce = workforce
        self.events = events
        self.enabled = bool(enabled)
        self.observation_threshold = max(2, min(20, int(observation_threshold)))
        self.interval_seconds = max(5.0, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _emit(self, name: str, **payload) -> None:
        if self.events is not None:
            self.events.emit(name, **payload)

    @staticmethod
    def _next_minor_label(current: str, occupied: set[str]) -> str:
        value = str(current or "1.0").strip()
        match = re.fullmatch(r"(v?)(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
        if match:
            prefix, major, minor, _patch = match.groups()
            major_i = int(major)
            minor_i = int(minor or 0) + 1
            while True:
                candidate = f"{prefix}{major_i}.{minor_i}"
                if candidate not in occupied:
                    return candidate
                minor_i += 1
        base = value[:60] or "1.0"
        index = 1
        while f"{base}.{index}" in occupied:
            index += 1
        return f"{base}.{index}"

    @staticmethod
    def _qualification(version: dict) -> dict:
        value = version.get("qualification")
        return dict(value) if isinstance(value, dict) else {}

    def _existing_auto_child(self, versions: list[dict], parent_version_id: str) -> dict | None:
        for version in versions:
            qualification = self._qualification(version)
            marker = qualification.get("auto_evolution")
            if (
                version.get("parent_version_id") == parent_version_id
                and isinstance(marker, dict)
                and marker.get("generated") is True
                and version.get("state") in {
                    AgentVersionState.CANDIDATE.value,
                    AgentVersionState.EXPERIMENTAL.value,
                }
            ):
                return version
        return None

    def _used_observations(self, versions: list[dict]) -> set[str]:
        used: set[str] = set()
        for version in versions:
            marker = self._qualification(version).get("auto_evolution")
            if not isinstance(marker, dict):
                continue
            for observation_id in marker.get("source_observation_ids") or ():
                if str(observation_id).strip():
                    used.add(str(observation_id))
        return used

    @staticmethod
    def _candidate_instructions(parent: dict, target: str, observations: list[dict]) -> str:
        base = str(parent.get("instructions") or "").strip()
        lines = []
        for observation in observations:
            kind = str(observation.get("kind") or "lesson").strip()[:80]
            summary = " ".join(str(observation.get("summary") or "").split())[:600]
            evidence = str(observation.get("evidence_ref") or "").strip()[:300]
            lines.append(f"- [{kind}] {summary} (evidence: {evidence})")
        appendix = (
            f"\n\nVerified lessons incorporated for candidate {target}:\n"
            + "\n".join(lines)
            + "\n\nThese lessons refine reasoning only. They do not expand tools, permissions, "
              "Project access, approval authority, execution authority, Evidence authority, or completion authority."
        )
        return (base + appendix)[:32000]

    def scan_once(self) -> list[AgentEvolutionCandidate]:
        if not self.enabled:
            return []
        created: list[AgentEvolutionCandidate] = []
        store = self.workforce.store
        with store.lock:
            for template in store.list_templates():
                template_id = template["id"]
                parent = store.preferred_version(template_id)
                versions = store.list_versions(template_id)
                if self._existing_auto_child(versions, parent["id"]) is not None:
                    continue
                used = self._used_observations(versions)
                observations = [
                    item
                    for item in reversed(store.list_observations(template_id, version_id=parent["id"], limit=500))
                    if str(item.get("evidence_ref") or "").strip()
                    and str(item.get("summary") or "").strip()
                    and str(item.get("id") or "") not in used
                ]
                if len(observations) < self.observation_threshold:
                    continue
                chosen = observations[: self.observation_threshold]
                occupied = {str(item.get("version") or "") for item in versions}
                target = self._next_minor_label(parent.get("version") or "1.0", occupied)
                candidate = self.workforce.create_version(
                    template_id,
                    version=target,
                    parent_version_id=parent["id"],
                    instructions=self._candidate_instructions(parent, target, chosen),
                    capabilities=tuple(parent.get("capabilities") or ()),
                    tools=tuple(parent.get("tools") or ()),
                    model_policy=dict(parent.get("model_policy") or {}),
                )
                qualification = {
                    "requires_qualification": True,
                    "authority": False,
                    "auto_evolution": {
                        "generated": True,
                        "source_version_id": parent["id"],
                        "source_observation_ids": [item["id"] for item in chosen],
                        "source_evidence_refs": [item["evidence_ref"] for item in chosen],
                    },
                }
                candidate = store.set_version_state(
                    candidate["id"],
                    AgentVersionState.CANDIDATE.value,
                    qualification=qualification,
                )
                record = AgentEvolutionCandidate(
                    template_id=template_id,
                    parent_version_id=parent["id"],
                    candidate_version_id=candidate["id"],
                    version=candidate["version"],
                    observation_ids=tuple(item["id"] for item in chosen),
                )
                created.append(record)
                self._emit(
                    "agent.evolution.candidate_generated",
                    template_id=record.template_id,
                    parent_version_id=record.parent_version_id,
                    candidate_version_id=record.candidate_version_id,
                    version=record.version,
                    observation_ids=list(record.observation_ids),
                    authority=False,
                )
        return created

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception as exc:
                self._emit("agent.evolution.scan_failed", error_type=type(exc).__name__)
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        if not self.enabled or (self._thread is not None and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="vishnu-agent-evolution", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=min(5.0, self.interval_seconds + 0.5))
        self._thread = None
