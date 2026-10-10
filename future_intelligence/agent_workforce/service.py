from __future__ import annotations

import re
from collections import Counter

from models.contracts import ModelRequest

from .chat import AgentConversationStore
from .models import AgentInstanceState, AgentVersionState
from .store import AgentWorkforceStore


CORE_AGENTS = (
    ("project-manager", "Project Manager", "project_manager", "Plans and coordinates a project team.", ("planning", "coordination", "reporting")),
    ("coding", "Coding Agent", "coding", "Software development, repository work, debugging and testing.", ("development", "git", "testing", "code_review")),
    ("research", "Research Agent", "research", "Research, source analysis and information synthesis.", ("web_research", "analysis", "sources")),
    ("browser", "Browser Agent", "browser", "Governed browser navigation, extraction and verification.", ("browsing", "data_extraction", "automation")),
    ("data", "Data Agent", "data", "Data analysis, databases, spreadsheets and reporting.", ("analysis", "sql", "spreadsheets", "visualization")),
    ("reviewer", "Reviewer Agent", "reviewer", "Independent review, evidence checking and quality control.", ("review", "quality", "verification")),
    ("qa", "QA Agent", "qa", "Testing, regression checking and acceptance verification.", ("testing", "validation", "security_checks")),
    ("security", "Security Agent", "security", "Security review and vulnerability analysis without execution authority.", ("security", "audit", "review")),
    ("design", "Design Agent", "design", "UI/UX design, visual specifications and design-system work.", ("ui_ux", "design", "accessibility")),
    ("files", "Files Agent", "files", "Project-scoped file organization and document work.", ("files", "documents")),
    ("communications", "Communications Agent", "communications", "Drafts and prepares communications subject to approval policy.", ("communications", "drafting")),
    ("knowledge", "Knowledge Agent", "knowledge", "Maintains project knowledge and verified reusable learnings.", ("knowledge", "synthesis")),
)

WORKER_AGENT_SLUGS = {
    "project": "project-manager",
    "project_manager": "project-manager",
    "orchestrator": "project-manager",
    "coding": "coding",
    "research": "research",
    "browser": "browser",
    "data": "data",
    "reviewer": "reviewer",
    "review": "reviewer",
    "qa": "qa",
    "security": "security",
    "design": "design",
    "files": "files",
    "communications": "communications",
    "knowledge": "knowledge",
}

WORK_STATUS_INSTANCE_STATE = {
    "draft": AgentInstanceState.ASSIGNED.value,
    "queued": AgentInstanceState.ASSIGNED.value,
    "running": AgentInstanceState.WORKING.value,
    "waiting_approval": AgentInstanceState.WAITING_APPROVAL.value,
    "waiting_resource": AgentInstanceState.WAITING_RESOURCE.value,
    "retrying": AgentInstanceState.RETRYING.value,
    "blocked": AgentInstanceState.BLOCKED.value,
    "paused": AgentInstanceState.PAUSED.value,
    "recovery_required": AgentInstanceState.RECOVERING.value,
    "verifying": AgentInstanceState.VERIFYING.value,
    "reviewing": AgentInstanceState.REVIEWING.value,
}
TERMINAL_WORK_STATES = {"completed", "failed", "cancelled"}


class AgentWorkforceService:
    """Owner-facing workforce layer over Vishnu canonical Work.

    It allocates intelligence workers, not execution authority. Tool permission,
    approvals, durable effect execution, evidence and Completion Judge remain in
    the existing Work/P10/P6 stack. Direct specialist chat is model-only and is
    durably bound to one Project plus one immutable agent version.
    """

    def __init__(
        self,
        store: AgentWorkforceStore,
        *,
        worker_registry=None,
        work_store=None,
        worker_intelligence=None,
        models=None,
        events=None,
    ):
        self.store = store
        self.worker_registry = worker_registry
        self.work_store = work_store
        self.worker_intelligence = worker_intelligence
        self.models = models
        self.events = events
        self.chat_store = AgentConversationStore(store.connection, lock=store.lock)
        self.seed_core_agents()

    def _emit(self, event: str, **payload):
        if self.events is not None:
            self.events.emit(event, **payload)

    def seed_core_agents(self) -> None:
        for slug, name, role, description, capabilities in CORE_AGENTS:
            template = self.store.get_template_by_slug(slug)
            if template is None:
                template = self.store.create_template(slug=slug, name=name, role=role, description=description, system_owned=True)
            if not self.store.list_versions(template["id"]):
                self.store.create_version(
                    template["id"], version="1.0", state=AgentVersionState.PREFERRED.value,
                    capabilities=capabilities, memory_policy="project_only",
                    instructions=(
                        f"You are Vishnu's {name}. Work only inside the assigned Project and WorkOrder. "
                        "Treat model output as untrusted. Never claim completion without canonical evidence. "
                        "Never import another Project's memory, files or decisions unless Vishnu provides an explicit authorized transfer."
                    ),
                    model_policy={"routing": "auto", "authority": False},
                    qualification={"source": "system_seed", "authority": False},
                )

    def summary(self) -> dict:
        return self.store.summary()

    def catalog(self) -> list[dict]:
        result = []
        for template in self.store.list_templates():
            versions = self.store.list_versions(template["id"])
            instances = self.store.list_instances(template_id=template["id"])
            active = [row for row in instances if row["state"] not in {"idle", "completed", "failed", "stopped"}]
            preferred = next((row for row in versions if row["state"] == "preferred"), versions[0] if versions else None)
            result.append({
                **template,
                "preferred_version": preferred,
                "version_count": len(versions),
                "instance_count": len([row for row in instances if row["state"] != "stopped"]),
                "active_instance_count": len(active),
            })
        return result

    def detail(self, template_id: str) -> dict:
        template = self.store.get_template(template_id)
        return {
            **template,
            "versions": self.store.list_versions(template_id),
            "instances": self.store.list_instances(template_id=template_id),
            "observations": self.store.list_observations(template_id, limit=100),
            "conversations": self.chat_store.list(template_id=template_id, limit=100),
        }

    def create_custom_agent(self, *, name: str, role: str, description: str, instructions: str, capabilities=(), tools=(), model_policy=None) -> dict:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:90]
        if not slug:
            raise ValueError("agent name must contain letters or numbers")
        if self.store.get_template_by_slug(slug) is not None:
            raise ValueError("an agent with this normalized name already exists")
        template = self.store.create_template(slug=slug, name=name, role=role, description=description, system_owned=False)
        version = self.store.create_version(
            template["id"], version="1.0", state=AgentVersionState.CANDIDATE.value,
            instructions=instructions, capabilities=tuple(capabilities), tools=tuple(tools),
            memory_policy="project_only", model_policy=model_policy or {"routing": "auto", "authority": False},
        )
        self._emit("agent.template.created", template_id=template["id"], version_id=version["id"])
        return {"template": template, "version": version}

    def create_version(self, template_id: str, *, version: str, parent_version_id: str, instructions: str, capabilities=(), tools=(), model_policy=None) -> dict:
        parent = self.store.get_version(parent_version_id)
        if parent["template_id"] != template_id:
            raise ValueError("parent version does not belong to template")
        normalized_version = str(version).strip()
        if any(row["version"] == normalized_version for row in self.store.list_versions(template_id)):
            raise ValueError("agent version already exists")
        created = self.store.create_version(
            template_id, version=normalized_version, state=AgentVersionState.CANDIDATE.value,
            instructions=instructions, capabilities=tuple(capabilities) or tuple(parent["capabilities"]),
            tools=tuple(tools) or tuple(parent["tools"]), memory_policy=parent["memory_policy"],
            model_policy=model_policy or parent["model_policy"], parent_version_id=parent_version_id,
            qualification={"requires_qualification": True, "authority": False},
        )
        self._emit("agent.version.candidate_created", template_id=template_id, version_id=created["id"], parent_version_id=parent_version_id)
        return created

    @staticmethod
    def _validated_qualification(state: str, qualification: dict | None) -> dict:
        qualification = dict(qualification or {})
        if state not in {"stable", "preferred"}:
            return qualification
        if qualification.get("passed") is not True:
            raise ValueError("stable/preferred promotion requires passed qualification")
        evidence_refs = qualification.get("evidence_refs")
        if not isinstance(evidence_refs, (list, tuple)) or not any(str(item).strip() for item in evidence_refs):
            raise ValueError("stable/preferred promotion requires qualification evidence_refs")
        run_id = str(qualification.get("qualification_run_id") or "").strip()
        summary = str(qualification.get("test_summary") or "").strip()
        if not run_id and not summary:
            raise ValueError("stable/preferred promotion requires a qualification_run_id or test_summary")
        qualification["evidence_refs"] = [str(item).strip() for item in evidence_refs if str(item).strip()][:100]
        qualification["authority"] = False
        return qualification

    def promote_version(self, version_id: str, *, state: str, qualification: dict) -> dict:
        if state not in {"experimental", "stable", "preferred", "degraded", "archived"}:
            raise ValueError("unsupported promotion state")
        qualification = self._validated_qualification(state, qualification)
        result = self.store.set_version_state(version_id, state, qualification=qualification)
        self._emit("agent.version.state_changed", template_id=result["template_id"], version_id=version_id, state=state)
        return result

    def create_instance(self, template_id: str, *, project_id: str, version_id: str | None = None, model_provider: str | None = None, model_id: str | None = None) -> dict:
        if not project_id:
            raise ValueError("project_id is required for a runtime agent instance")
        instance = self.store.create_instance(template_id, project_id=project_id, version_id=version_id, model_provider=model_provider, model_id=model_id)
        self._emit("agent.instance.created", instance_id=instance["id"], template_id=template_id, project_id=project_id, version_id=instance["version_id"])
        return instance

    def create_team(self, project_id: str, requirements: dict[str, int]) -> dict:
        if not project_id:
            raise ValueError("project_id is required")
        if len(dict(requirements or {})) > 50:
            raise ValueError("too many agent types requested")
        clean = Counter()
        for slug, raw_count in dict(requirements or {}).items():
            count = max(0, min(100, int(raw_count)))
            if count:
                clean[str(slug)] += count
        if not clean:
            clean["project-manager"] = 1
        if clean.get("project-manager", 0) == 0:
            clean["project-manager"] = 1
        members = []
        for slug, count in clean.items():
            template = self.store.get_template_by_slug(slug)
            if template is None:
                raise KeyError(f"unknown agent type: {slug}")
            for _ in range(count):
                members.append(self.create_instance(template["id"], project_id=project_id))
        self._emit("agent.team.created", project_id=project_id, instance_ids=[row["id"] for row in members])
        return {"project_id": project_id, "members": self.store.list_project_team(project_id)}

    def ensure_project_manager(self, project_id: str) -> dict:
        """Idempotently make the Project Manager the first workforce member."""
        if not project_id:
            raise ValueError("project_id is required")
        existing = [row for row in self.store.list_project_team(project_id) if bool(row.get("is_manager"))]
        if existing:
            return existing[0]
        template = self.store.get_template_by_slug("project-manager")
        if template is None:
            raise RuntimeError("Project Manager template unavailable")
        return self.create_instance(template["id"], project_id=project_id)

    def _work_order(self, work_order_id: str):
        if self.work_store is None:
            return None
        getter = getattr(self.work_store, "get_order", None) or getattr(self.work_store, "get_work_order", None)
        if getter is None:
            raise RuntimeError("canonical WorkStore cannot resolve WorkOrders")
        return getter(work_order_id)

    def assign(self, instance_id: str, *, project_id: str, work_order_id: str) -> dict:
        if self.work_store is not None:
            work = self._work_order(work_order_id)
            if work is None:
                raise KeyError(work_order_id)
            work_project = getattr(work, "project_id", None) if not isinstance(work, dict) else work.get("project_id")
            if work_project != project_id:
                raise PermissionError("WorkOrder belongs to a different project")
        assignment = self.store.assign(instance_id, project_id=project_id, work_order_id=work_order_id)
        self._emit("agent.assignment.created", assignment_id=assignment["id"], instance_id=instance_id, project_id=project_id, work_order_id=work_order_id, version_id=assignment["version_id"])
        return assignment

    @staticmethod
    def _order_status(order) -> str:
        status = getattr(order, "status", "")
        return str(getattr(status, "value", status) or "").lower()

    @staticmethod
    def _order_capabilities(order) -> set[str]:
        return {str(item).strip().lower() for item in (getattr(order, "allowed_capabilities", ()) or ()) if str(item).strip()}

    def _agent_slug_for_order(self, order) -> str | None:
        worker_type = str(getattr(order, "worker_type", "") or "").strip().lower()
        if worker_type in WORKER_AGENT_SLUGS:
            return WORKER_AGENT_SLUGS[worker_type]
        if worker_type != "tool":
            return None
        capabilities = self._order_capabilities(order)
        if capabilities & {"browser", "browsing", "web", "web_research"}:
            return "browser"
        if capabilities & {"files", "documents", "filesystem"}:
            return "files"
        if capabilities & {"communications", "email", "messaging"}:
            return "communications"
        if capabilities & {"data", "sql", "spreadsheet", "spreadsheets", "analysis"}:
            return "data"
        if capabilities & {"git", "coding", "development", "testing"}:
            return "coding"
        if capabilities & {"research", "sources"}:
            return "research"
        return None

    def _assignment_for_work_order(self, work_order_id: str) -> dict | None:
        row = self.store.connection.execute(
            "SELECT * FROM agent_assignments WHERE work_order_id=?", (str(work_order_id),)
        ).fetchone()
        return dict(row) if row is not None else None

    def reconcile_project_work(self, project_id: str) -> dict:
        """Project canonical Work -> workforce projection, never execution authority.

        This may allocate an idle specialist and mirror canonical Work status into
        the workforce UI. It does not dispatch Work, call tools, grant approvals,
        produce Evidence or decide completion.
        """
        manager = self.ensure_project_manager(project_id)
        if self.work_store is None or not hasattr(self.work_store, "latest_project_plan_record"):
            return {"project_id": project_id, "manager": manager, "assignments": [], "unmapped": []}
        record = self.work_store.latest_project_plan_record(project_id)
        if not record:
            return {"project_id": project_id, "manager": manager, "assignments": [], "unmapped": []}
        plan = record["plan"] if isinstance(record, dict) else record
        assignments, unmapped = [], []
        for order in tuple(getattr(plan, "work_orders", ()) or ()):
            order_id = str(getattr(order, "id", "") or "")
            if not order_id:
                continue
            status = self._order_status(order)
            existing = self._assignment_for_work_order(order_id)
            if existing is not None:
                if status in TERMINAL_WORK_STATES and not existing.get("completed_at"):
                    existing = self.store.finish_assignment(
                        existing["id"], status="completed" if status == "completed" else "failed"
                    )
                elif status not in TERMINAL_WORK_STATES:
                    projected_state = WORK_STATUS_INSTANCE_STATE.get(status)
                    if projected_state:
                        self.store.set_instance_state(existing["instance_id"], projected_state)
                assignments.append(existing)
                continue
            if status in TERMINAL_WORK_STATES:
                continue
            slug = self._agent_slug_for_order(order)
            if slug is None:
                unmapped.append(order_id)
                continue
            template = self.store.get_template_by_slug(slug)
            if template is None:
                unmapped.append(order_id)
                continue
            team = self.store.list_project_team(project_id)
            candidate = next(
                (
                    row for row in team
                    if row.get("template_id") == template["id"]
                    and row.get("state") in {AgentInstanceState.IDLE.value, AgentInstanceState.COMPLETED.value}
                    and not row.get("current_work_order_id")
                ),
                None,
            )
            if candidate is None:
                instance = self.create_instance(template["id"], project_id=project_id)
                instance_id = instance["id"]
            else:
                instance_id = candidate["instance_id"]
            assignment = self.store.assign(instance_id, project_id=project_id, work_order_id=order_id)
            projected_state = WORK_STATUS_INSTANCE_STATE.get(status)
            if projected_state:
                self.store.set_instance_state(instance_id, projected_state)
            assignments.append(assignment)
            self._emit(
                "agent.assignment.reconciled",
                assignment_id=assignment["id"],
                instance_id=instance_id,
                project_id=project_id,
                work_order_id=order_id,
                worker_type=str(getattr(order, "worker_type", "")),
                authority=False,
            )
        return {
            "project_id": project_id,
            "manager": manager,
            "assignments": assignments,
            "unmapped": unmapped,
            "execution_authority": False,
        }

    def project_team(self, project_id: str) -> list[dict]:
        return self.store.list_project_team(project_id)

    def create_conversation(
        self,
        template_id: str,
        *,
        project_id: str,
        instance_id: str | None = None,
        title: str = "New agent chat",
    ) -> dict:
        self.store.get_template(template_id)
        if not project_id:
            raise ValueError("project_id is required")
        if instance_id:
            instance = self.store.get_instance(instance_id)
            if instance["template_id"] != template_id:
                raise PermissionError("instance belongs to another agent")
            if instance["project_id"] != project_id:
                raise PermissionError("agent instance is bound to another project")
            version_id = instance["version_id"]
        else:
            version_id = self.store.preferred_version(template_id)["id"]
        conversation = self.chat_store.create(
            template_id=template_id,
            version_id=version_id,
            instance_id=instance_id,
            project_id=project_id,
            title=title,
        )
        self._emit(
            "agent.chat.created",
            conversation_id=conversation["id"],
            template_id=template_id,
            version_id=version_id,
            project_id=project_id,
            instance_id=instance_id,
        )
        return conversation

    def list_conversations(self, *, template_id: str, project_id: str, limit: int = 100) -> list[dict]:
        self.store.get_template(template_id)
        return self.chat_store.list(template_id=template_id, project_id=project_id, limit=limit)

    def conversation(self, conversation_id: str, *, project_id: str) -> dict:
        conversation = self.chat_store.get(conversation_id)
        if conversation["project_id"] != project_id:
            raise PermissionError("agent conversation belongs to another project")
        return {**conversation, "messages": self.chat_store.messages(conversation_id, limit=200)}

    def direct_chat(
        self,
        conversation_id: str,
        *,
        project_id: str,
        prompt: str,
        project_context: str = "",
        sensitivity: str = "internal",
    ) -> dict:
        conversation = self.chat_store.get(conversation_id)
        if conversation["project_id"] != project_id:
            raise PermissionError("agent conversation belongs to another project")
        if conversation["state"] != "active":
            raise RuntimeError("agent conversation is closed")
        if self.models is None:
            raise RuntimeError("model router unavailable")
        version = self.store.get_version(conversation["version_id"])
        template = self.store.get_template(conversation["template_id"])
        instance = self.store.get_instance(conversation["instance_id"]) if conversation.get("instance_id") else None
        if instance is not None and instance["project_id"] != project_id:
            raise PermissionError("agent instance is bound to another project")

        prior = self.chat_store.messages(conversation_id, limit=24)
        history = tuple(
            {"role": row["role"], "content": row["content"]}
            for row in prior
            if row["role"] in {"user", "assistant"}
        )
        user_message = self.chat_store.append(conversation_id, role="user", content=prompt)
        system = (
            f"You are Vishnu's {template['name']} ({template['role']}), agent version {version['version']}.\n"
            "You are an intelligence specialist, not execution authority. Never claim a tool action, deployment, send, merge, "
            "external change, verification or completion unless canonical Vishnu evidence supplied in this chat proves it. "
            "Never use memory, files, decisions or context from any Project other than the Project explicitly bound to this conversation.\n"
            f"Agent instructions:\n{version['instructions'][:16000]}\n"
            f"Authorized Project context only:\n{str(project_context or '')[:16000]}"
        )
        policy = dict(version.get("model_policy") or {})
        request = ModelRequest(
            prompt=str(prompt)[:16000],
            system=system,
            history=history,
            agent_id=conversation.get("instance_id") or conversation["template_id"],
            project_id=project_id,
            capability="chat",
            routing_policy=str(policy.get("routing_policy") or "fast_chat"),
            sensitivity=str(sensitivity or "internal"),
            preferred_provider=(instance or {}).get("model_provider") or policy.get("provider"),
            preferred_model=(instance or {}).get("model_id") or policy.get("model"),
            tools_allowed=(),
            metadata={"agent_version_id": version["id"], "agent_chat": True, "authority": False},
        )
        response = self.models.request(request)
        assistant_message = self.chat_store.append(
            conversation_id,
            role="assistant",
            content=response.content,
            provider=response.provider_id,
            model_id=response.model_id,
            request_id=response.request_id,
        )
        self._emit(
            "agent.chat.reply",
            conversation_id=conversation_id,
            template_id=conversation["template_id"],
            version_id=version["id"],
            project_id=project_id,
            request_id=response.request_id,
        )
        return {
            "conversation": self.chat_store.get(conversation_id),
            "user_message": user_message,
            "assistant_message": assistant_message,
            "usage": response.usage.__dict__,
            "provider": response.provider_id,
            "model": response.model_id,
            "model_output_authority": False,
            "tool_execution_authority": False,
            "completion_authority": False,
        }

    def record_learning(self, template_id: str, version_id: str, *, kind: str, summary: str, project_id: str | None = None, work_order_id: str | None = None, score: float | None = None, evidence_ref: str | None = None) -> dict:
        observation = self.store.record_observation(
            template_id, version_id, kind=kind, summary=summary, project_id=project_id,
            work_order_id=work_order_id, score=score, evidence_ref=evidence_ref,
        )
        self._emit("agent.learning.observed", template_id=template_id, version_id=version_id, observation_id=observation["id"])
        return observation

    def specialist_proposal(self, *, work_order_id: str, prompt: str, project_id: str, instance_id: str, context: str = "", sensitivity: str = "internal") -> dict:
        instance = self.store.get_instance(instance_id)
        if instance["project_id"] != project_id:
            raise PermissionError("agent instance is bound to another project")
        if instance["current_work_order_id"] not in {None, work_order_id}:
            raise PermissionError("agent instance is assigned to another WorkOrder")
        if self.worker_intelligence is None:
            raise RuntimeError("worker intelligence unavailable")
        response = self.worker_intelligence.invoke(
            work_order_id, prompt, sensitivity=sensitivity,
            context=(
                "PROJECT ISOLATION: only the supplied Project context is authorized. "
                "Do not infer or retrieve context from another Project.\n" + str(context)[:16000]
            ),
        )
        return {
            "request_id": response.request_id,
            "provider": response.provider_id,
            "model": response.model_id,
            "content": response.content,
            "usage": response.usage.__dict__,
            "agent_instance_id": instance_id,
            "agent_version_id": instance["version_id"],
            "project_id": project_id,
            "work_order_id": work_order_id,
            "model_output_authority": False,
            "completion_authority": False,
        }
