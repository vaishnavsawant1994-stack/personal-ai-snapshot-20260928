from __future__ import annotations

from .models import WorkerProfile


DEFAULT_WORKERS: tuple[WorkerProfile, ...] = (
    WorkerProfile(
        id="research",
        description="Gather, compare and synthesize information without granting execution authority.",
        supported_capabilities=("research", "read", "search", "browse", "web", "knowledge", "retrieval"),
        output_kinds=("notes", "sources", "brief"),
    ),
    WorkerProfile(
        id="coding",
        description="Plan and perform governed software work through existing repository/tool authorities.",
        supported_capabilities=("code", "coding", "git", "github", "repository", "test", "build", "deploy", "read", "write"),
        output_kinds=("patch", "commit", "tests", "build"),
    ),
    WorkerProfile(
        id="browser",
        description="Use governed browser or web capabilities for navigation and retrieval.",
        supported_capabilities=("browser", "web", "browse", "navigate", "search", "read"),
        output_kinds=("page", "observation", "artifact"),
    ),
    WorkerProfile(
        id="files",
        description="Work with governed files, documents and storage capabilities.",
        supported_capabilities=("file", "files", "document", "drive", "storage", "read", "write", "edit"),
        output_kinds=("file", "document", "artifact"),
    ),
    WorkerProfile(
        id="data",
        description="Analyze or transform governed structured data and databases.",
        supported_capabilities=("data", "database", "sql", "sheet", "spreadsheet", "analytics", "read", "write"),
        output_kinds=("dataset", "analysis", "table", "query_result"),
    ),
    WorkerProfile(
        id="communications",
        description="Draft or propose governed external communications; sending remains separately authorized.",
        supported_capabilities=("communication", "communications", "email", "message", "calendar", "send", "share", "publish", "read"),
        output_kinds=("draft", "message", "email", "event"),
    ),
    WorkerProfile(
        id="knowledge",
        description="Retrieve and structure governed memory and knowledge sources.",
        supported_capabilities=("knowledge", "memory", "search", "retrieval", "research", "read"),
        output_kinds=("context", "citation", "knowledge_entry"),
    ),
    WorkerProfile(
        id="project",
        description="Coordinate project tasks, milestones and workflow metadata without bypassing execution controls.",
        supported_capabilities=("project", "task", "workflow", "plan", "automation", "read", "write", "edit"),
        output_kinds=("task", "milestone", "plan", "status"),
    ),
    WorkerProfile(
        id="reviewer",
        description="Review outputs, evidence and quality; cannot grant approval or verification by itself.",
        supported_capabilities=("review", "verify", "verification", "quality", "research", "knowledge", "search", "read"),
        can_propose_tools=True,
        output_kinds=("review", "critique", "recommendation"),
    ),
    WorkerProfile(
        id="tool",
        description="Generic wrapper for a specifically selected available tool; ToolRegistry remains authoritative.",
        supported_capabilities=(),
        can_propose_tools=True,
        requires_tool=True,
        allow_any_available_tool=True,
        output_kinds=("tool_result",),
    ),
)
