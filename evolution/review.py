from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import requests


_GITHUB_PR = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)(?:[/?#].*)?$")


@dataclass(frozen=True)
class ReviewVerification:
    review_ref: str
    revision: str
    verified: bool
    approved: bool
    state: str
    reviewer: str | None = None
    reason: str = ""


class ReviewVerifier(Protocol):
    def verify(self, review_ref: str, *, revision: str) -> ReviewVerification: ...


class GitHubPublicReviewVerifier:
    """Read-only GitHub PR verifier; it cannot create, merge, or modify reviews."""

    def __init__(self, *, repository: str, timeout_seconds: float = 10.0) -> None:
        self.repository = str(repository or "").strip()
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        if "/" not in self.repository:
            raise ValueError("repository must be owner/name")

    def verify(self, review_ref: str, *, revision: str) -> ReviewVerification:
        ref = str(review_ref or "").strip()
        match = _GITHUB_PR.match(ref)
        if match is None:
            return ReviewVerification(ref, str(revision), False, False, "invalid", reason="review_ref is not a GitHub pull request URL")
        owner, repo, number = match.groups()
        if f"{owner}/{repo}".casefold() != self.repository.casefold():
            return ReviewVerification(ref, str(revision), False, False, "wrong_repository", reason="pull request belongs to a different repository")
        base = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        pr_response = requests.get(f"{base}/pulls/{number}", headers=headers, timeout=self.timeout_seconds)
        if pr_response.status_code != 200:
            return ReviewVerification(ref, str(revision), False, False, "unavailable", reason=f"GitHub returned {pr_response.status_code}")
        pr = pr_response.json()
        head_sha = str(((pr.get("head") or {}).get("sha") or ""))
        if head_sha != str(revision):
            return ReviewVerification(ref, str(revision), False, False, "revision_mismatch", reason="pull request head does not match verified implementation revision")
        review_response = requests.get(f"{base}/pulls/{number}/reviews?per_page=100", headers=headers, timeout=self.timeout_seconds)
        if review_response.status_code != 200:
            return ReviewVerification(ref, str(revision), False, False, str(pr.get("state") or "open"), reason=f"review lookup returned {review_response.status_code}")
        reviews = review_response.json()
        latest_by_user: dict[str, dict] = {}
        for item in reviews if isinstance(reviews, list) else []:
            login = str(((item.get("user") or {}).get("login") or "")).strip()
            if login:
                latest_by_user[login] = item
        approvals = [item for item in latest_by_user.values() if str(item.get("state") or "").upper() == "APPROVED"]
        reviewer = str(((approvals[-1].get("user") or {}).get("login") or "")) if approvals else None
        return ReviewVerification(
            review_ref=ref,
            revision=str(revision),
            verified=True,
            approved=bool(approvals),
            state=str(pr.get("state") or "open"),
            reviewer=reviewer or None,
            reason="approved review found" if approvals else "pull request is verified but has no current approved review",
        )
