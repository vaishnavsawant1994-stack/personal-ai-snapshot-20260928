from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum

class ActionRisk(IntEnum):
    READ_ONLY = 0
    REVERSIBLE = 1
    EXTERNAL_SIDE_EFFECT = 2
    DESTRUCTIVE = 3
    CRITICAL = 4

@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool
    reason: str

class PermissionEngine:
    """Authoritative policy layer below the LLM/tool planner."""
    DEFAULT_RULES = {
        "read": "allow",
        "create": "allow",
        "edit": "allow",
        "delete": "ask",
        "external_communication": "ask",
        "execute_actions": "ask",
        "financial_actions": "ask",
        "account_security_changes": "ask",
    }
    RULE_VALUES = {"allow", "ask", "never"}

    def __init__(self, mode: str = "ask", rules: dict[str, str] | None = None):
        self.mode = mode
        self.rules = {**self.DEFAULT_RULES, **(rules or {})}

    def set_rules(self, rules: dict[str, str]) -> dict[str, str]:
        if not isinstance(rules, dict) or set(rules) != set(self.DEFAULT_RULES):
            raise ValueError("all owner permission groups must be provided")
        clean = {str(key): str(value).lower() for key, value in rules.items()}
        if any(value not in self.RULE_VALUES for value in clean.values()):
            raise ValueError("permission values must be allow, ask, or never")
        self.rules = clean
        return dict(clean)

    def decide(self, risk: int, *, confirmed: bool = False, operation: str | None = None) -> PermissionDecision:
        r = ActionRisk(int(risk))
        rule = self.rules.get(operation or "")
        # Explicit denial is a policy boundary and cannot be overridden by a
        # confirmation button on a pending approval.
        if rule == "never":
            return PermissionDecision(False, False, "blocked by owner permission rule")
        if confirmed:
            return PermissionDecision(True, False, "explicitly confirmed")
        mode = self.mode
        if mode in {"observe", "suggest"}:
            if r == ActionRisk.READ_ONLY:
                return PermissionDecision(True, False, "read-only action")
            return PermissionDecision(False, True, "safe mode requires explicit owner approval")
        if rule == "ask":
            return PermissionDecision(False, True, "owner approval required by permission rule")
        if rule == "allow":
            # Consequential and critical actions always retain the approval
            # boundary even if a broad rule is accidentally configured.
            if r >= ActionRisk.DESTRUCTIVE or operation in {"financial_actions", "account_security_changes"}:
                return PermissionDecision(False, True, "high-risk action requires confirmation")
            return PermissionDecision(True, False, "allowed by owner permission rule")
        if mode == "ask":
            if r == ActionRisk.READ_ONLY:
                return PermissionDecision(True, False, "read-only action")
            return PermissionDecision(False, True, "confirmation required")
        if mode == "act":
            if r <= ActionRisk.REVERSIBLE:
                return PermissionDecision(True, False, "allowed by act mode")
            return PermissionDecision(False, True, "high-risk action requires confirmation")
        return PermissionDecision(False, True, "unknown autonomy mode")

    def authorize(self, risk: int, *, confirmed: bool = False) -> None:
        decision = self.decide(risk, confirmed=confirmed)
        if not decision.allowed:
            raise PermissionError(decision.reason)
