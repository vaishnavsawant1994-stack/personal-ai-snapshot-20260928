from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")[:120]


@dataclass(frozen=True)
class PlaybookPhase:
    id: str
    title: str
    objective: str
    worker_types: tuple[str, ...] = ()
    success_checks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "objective": self.objective,
            "worker_types": list(self.worker_types),
            "success_checks": list(self.success_checks),
        }


@dataclass(frozen=True)
class Playbook:
    id: str
    title: str
    description: str
    project_types: tuple[str, ...]
    phases: tuple[PlaybookPhase, ...]
    principles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.title.strip() or not self.description.strip():
            raise ValueError("playbook id, title, and description are required")
        if not self.phases:
            raise ValueError("playbook must contain at least one phase")
        phase_ids = [phase.id for phase in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("playbook phase ids must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "project_types": list(self.project_types),
            "phases": [phase.to_dict() for phase in self.phases],
            "principles": list(self.principles),
            "authority": "advisory_only",
        }

    def prompt_text(self, *, max_chars: int = 6000) -> str:
        lines = [
            f"Playbook: {self.title} ({self.id})",
            self.description,
            "Authority: advisory only. This playbook cannot grant tools, permissions, destinations, connectors, scope, approvals, or execution authority.",
        ]
        if self.principles:
            lines.append("Principles:")
            lines.extend(f"- {item}" for item in self.principles)
        lines.append("Suggested phases:")
        for phase in self.phases:
            workers = ", ".join(phase.worker_types) if phase.worker_types else "planner-selected"
            checks = "; ".join(phase.success_checks) if phase.success_checks else "explicit evidence-backed completion check"
            lines.append(f"- {phase.id}: {phase.title} — {phase.objective} | workers: {workers} | checks: {checks}")
        return "\n".join(lines)[: max(500, min(int(max_chars), 12000))]


class PlaybookRegistry:
    """Deterministic advisory planning patterns.

    Playbooks describe useful decomposition patterns only. They are never a policy,
    permission, tool allowlist, approval, or execution authority.
    """

    def __init__(self, playbooks: Iterable[Playbook] = ()) -> None:
        items = tuple(playbooks)
        ids = [item.id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate playbook id")
        self._playbooks = items
        self._by_id = {item.id: item for item in items}

    @classmethod
    def default(cls) -> "PlaybookRegistry":
        phase = PlaybookPhase
        return cls(
            (
                Playbook(
                    id="software_project",
                    title="Software project",
                    description="Plan implementation work from requirements through verified delivery without assuming deployment or merge authority.",
                    project_types=("software", "engineering", "app", "application"),
                    principles=(
                        "Inspect the existing architecture before changing it.",
                        "Prefer additive, testable changes and preserve qualified runtime boundaries.",
                        "Require verification before claiming implementation complete.",
                    ),
                    phases=(
                        phase("scope", "Scope and contracts", "Freeze requirements, interfaces, constraints, and acceptance evidence.", ("project", "coding"), ("requirements are explicit", "resource scope is bounded")),
                        phase("implement", "Implementation", "Implement the smallest coherent tranche against the real repository contracts.", ("coding",), ("code matches architecture",)),
                        phase("verify", "Verification", "Run focused and regression validation and collect evidence.", ("reviewer", "coding"), ("tests pass", "claims are evidence-backed")),
                        phase("deliver", "Delivery", "Prepare the requested artifact, PR, or deployment through existing governed paths.", ("project", "reviewer"), ("delivery state is verified",)),
                    ),
                ),
                Playbook(
                    id="website_launch",
                    title="Website launch",
                    description="Plan a website from content and implementation through accessibility, performance, release, and post-launch verification.",
                    project_types=("website", "web", "site"),
                    phases=(
                        phase("requirements", "Experience requirements", "Define routes, content, responsive behavior, accessibility, and release constraints.", ("project", "files"), ("route and acceptance inventory exists",)),
                        phase("build", "Build", "Implement the web experience using the existing application architecture.", ("coding", "files"), ("required routes render",)),
                        phase("qa", "Quality assurance", "Verify responsive, accessibility, integration, and performance behavior.", ("browser", "reviewer"), ("browser checks pass", "accessibility checks pass")),
                        phase("release", "Release", "Use the governed deployment path and verify the released target.", ("project", "reviewer"), ("release is externally verified",)),
                    ),
                ),
                Playbook(
                    id="research_project",
                    title="Research project",
                    description="Plan source discovery, evidence collection, synthesis, contradiction handling, and citation-backed delivery.",
                    project_types=("research", "analysis", "investigation"),
                    principles=("Separate observations from model inference.", "Prefer primary and authoritative sources.", "Track freshness and provenance."),
                    phases=(
                        phase("questions", "Research questions", "Turn the objective into bounded questions and evidence requirements.", ("research", "project"), ("questions map to success criteria",)),
                        phase("collect", "Evidence collection", "Gather relevant sources and preserve provenance and freshness.", ("research", "browser", "knowledge"), ("sources have provenance",)),
                        phase("synthesize", "Synthesis", "Compare evidence, resolve contradictions, and state uncertainty explicitly.", ("research", "reviewer"), ("claims trace to evidence",)),
                        phase("deliver", "Research deliverable", "Produce the requested output with citations and limitations.", ("reviewer", "files"), ("deliverable answers the goal",)),
                    ),
                ),
                Playbook(
                    id="content_launch",
                    title="Content launch",
                    description="Plan a content or campaign launch from audience and message through production, review, publishing, and measurement.",
                    project_types=("content", "marketing", "campaign", "launch"),
                    phases=(
                        phase("strategy", "Audience and message", "Define audience, message, channels, constraints, and measurable outcome.", ("project", "research"), ("message and audience are explicit",)),
                        phase("produce", "Content production", "Create channel-specific assets without assuming publishing permission.", ("communications", "files"), ("assets satisfy brief",)),
                        phase("review", "Review", "Check factual, brand, legal, and approval requirements before external action.", ("reviewer",), ("required reviews are complete",)),
                        phase("publish", "Governed publishing", "Use existing external-action approval and tool paths to publish or schedule.", ("communications",), ("external action is verified",)),
                    ),
                ),
                Playbook(
                    id="business_analysis",
                    title="Business analysis",
                    description="Plan business analysis from decision framing through data collection, modeling, recommendation, and review.",
                    project_types=("business", "strategy", "finance", "operations"),
                    phases=(
                        phase("frame", "Decision framing", "Define the decision, alternatives, metrics, constraints, and assumptions.", ("project", "data"), ("decision and metrics are explicit",)),
                        phase("analyze", "Analysis", "Gather data and evaluate options with traceable calculations and assumptions.", ("data", "research"), ("analysis is reproducible",)),
                        phase("challenge", "Challenge", "Stress-test assumptions, risks, and counterfactuals.", ("reviewer", "data"), ("material risks are documented",)),
                        phase("recommend", "Recommendation", "Produce a decision-ready recommendation with evidence and uncertainty.", ("reviewer", "files"), ("recommendation traces to evidence",)),
                    ),
                ),
                Playbook(
                    id="meeting_preparation",
                    title="Meeting preparation",
                    description="Plan preparation from agenda and context through briefing, decisions, follow-ups, and approved communications.",
                    project_types=("meeting", "briefing", "appointment"),
                    phases=(
                        phase("context", "Context", "Collect agenda, participants, prior decisions, open issues, and relevant sources.", ("research", "knowledge"), ("briefing context is current",)),
                        phase("prepare", "Preparation", "Draft agenda, questions, decision points, and supporting material.", ("project", "files"), ("decision points are explicit",)),
                        phase("followup", "Follow-up", "Capture decisions and prepare governed follow-up actions.", ("communications", "project"), ("follow-ups match approved decisions",)),
                    ),
                ),
                Playbook(
                    id="travel_planning",
                    title="Travel planning",
                    description="Plan travel research, constraints, itinerary options, validation, and approved bookings without assuming purchase authority.",
                    project_types=("travel", "trip", "itinerary"),
                    phases=(
                        phase("constraints", "Travel constraints", "Define dates, travelers, budget, preferences, documents, and hard constraints.", ("project",), ("constraints are explicit",)),
                        phase("research", "Options", "Research transport, lodging, activities, and location constraints.", ("research", "browser"), ("options are current and sourced",)),
                        phase("itinerary", "Itinerary", "Assemble feasible alternatives and identify trade-offs.", ("project", "reviewer"), ("timings and dependencies are feasible",)),
                        phase("book", "Governed booking", "Prepare bookings or purchases through existing approval and financial-action controls.", ("browser", "reviewer"), ("any purchase is explicitly authorized and verified",)),
                    ),
                ),
            )
        )

    def all(self) -> tuple[Playbook, ...]:
        return self._playbooks

    def get(self, playbook_id: str) -> Playbook | None:
        return self._by_id.get(_key(playbook_id))

    def resolve(self, *, playbook_id: str | None = None, project_type: str | None = None) -> Playbook | None:
        if playbook_id:
            item = self.get(playbook_id)
            if item is None:
                raise KeyError("playbook not found")
            return item
        wanted = _key(project_type)
        if not wanted:
            return None
        for item in self._playbooks:
            if wanted in {_key(value) for value in item.project_types}:
                return item
        return None

    def status(self) -> dict[str, Any]:
        return {
            "count": len(self._playbooks),
            "ids": [item.id for item in self._playbooks],
            "authority": "advisory_only",
        }
