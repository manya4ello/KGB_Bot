"""Render knowledge items to Markdown and sync to the KB repo (U9, KTD4).

Rendering is pure and deterministic (stable ordering for clean diffs). Git sync
shells out to ``git`` (subprocess; no extra dependency). For the walking
skeleton this renders items as-is — consolidation (U8) is layered in later.

The KB repo MUST be private (KTD4); :func:`assert_repo_private` enforces it
before any push when a GitHub token is available.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from ..logging import get_logger

log = get_logger(__name__)

TYPE_FILES = {"decision": "decisions.md", "idea": "ideas.md", "argument": "arguments.md"}
TYPE_TITLES = {"decision": "Решения", "idea": "Идеи", "argument": "Аргументы"}
TYPE_ORDER = ["decision", "idea", "argument"]

Item = Mapping[str, Any]


# --------------------------------------------------------------------------- #
# Rendering (pure)
# --------------------------------------------------------------------------- #


def _participants(item: Item) -> list[str]:
    p = item.get("participants")
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except (ValueError, TypeError):
            p = [p] if p else []
    return [str(x) for x in p] if isinstance(p, list) else []


def _render_item(item: Item) -> str:
    lines = [f"- **{item['statement']}**"]
    rationale = item.get("rationale")
    if rationale:
        lines.append(f"  - Обоснование: {rationale}")
    participants = _participants(item)
    if participants:
        lines.append(f"  - Участники: {', '.join(participants)}")
    sources = item.get("source_ids") or []
    if sources:
        lines.append(f"  - Источники: {', '.join(str(s) for s in sources)}")
    return "\n".join(lines)


def _render_section(title: str, items: list[Item]) -> str:
    header = f"# {title}\n"
    if not items:
        return f"{header}\n_Пока пусто._\n"
    # Stable sort for clean diffs.
    ordered = sorted(items, key=lambda i: str(i["statement"]).lower())
    body = "\n".join(_render_item(i) for i in ordered)
    return f"{header}\n{body}\n"


def _render_index(title: str, slug: str, by_type: dict[str, list[Item]]) -> str:
    lines = [f"# {title}", "", f"Проект: `{slug}`", ""]
    for t in TYPE_ORDER:
        lines.append(f"- {TYPE_TITLES[t]} ({TYPE_FILES[t]}): {len(by_type[t])}")
    return "\n".join(lines) + "\n"


def render_project(slug: str, title: str, items: Iterable[Item]) -> dict[str, str]:
    """Render all Markdown files for one project. Keys are repo-relative paths."""
    by_type: dict[str, list[Item]] = {t: [] for t in TYPE_ORDER}
    for it in items:
        t = str(it["type"])
        if t in by_type:
            by_type[t].append(it)

    files: dict[str, str] = {}
    for t in TYPE_ORDER:
        files[f"projects/{slug}/{TYPE_FILES[t]}"] = _render_section(TYPE_TITLES[t], by_type[t])
    files[f"projects/{slug}/index.md"] = _render_index(title, slug, by_type)
    return files


# --------------------------------------------------------------------------- #
# Repo visibility check (KTD4)
# --------------------------------------------------------------------------- #

_GH_HTTPS = re.compile(r"github\.com[:/]+([^/]+)/([^/.]+)(?:\.git)?/?$")


def parse_owner_repo(url: str) -> tuple[str, str] | None:
    m = _GH_HTTPS.search(url.strip())
    return (m.group(1), m.group(2)) if m else None


def assert_repo_private(repo_url: str, token: str, *, opener: Callable | None = None) -> None:
    """Raise if the GitHub KB repo is not private. No-op if URL is unparseable."""
    parsed = parse_owner_repo(repo_url)
    if not parsed:
        return
    owner, repo = parsed
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    _open = opener or urllib.request.urlopen
    with _open(req) as resp:  # pragma: no cover - network
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("private", False):
        raise RuntimeError(
            f"KB repo {owner}/{repo} is NOT private — refusing to push knowledge (KTD4)."
        )


# --------------------------------------------------------------------------- #
# Git sync (subprocess)
# --------------------------------------------------------------------------- #


class GitKB:
    def __init__(
        self,
        local_path: str | Path,
        repo_url: str | None = None,
        *,
        deploy_key_path: str | None = None,
        author_name: str = "KGB_Bot",
        author_email: str = "kgb-bot@localhost",
    ) -> None:
        self.local_path = Path(local_path)
        self.repo_url = repo_url
        self.deploy_key_path = deploy_key_path
        self.author_name = author_name
        self.author_email = author_email

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.local_path,
            capture_output=True,
            text=True,
            check=check,
        )

    def ensure_repo(self) -> None:
        self.local_path.mkdir(parents=True, exist_ok=True)
        if not (self.local_path / ".git").exists():
            self._git("init", "-b", "main")
            self._git("config", "user.name", self.author_name)
            self._git("config", "user.email", self.author_email)
        if self.repo_url:
            remotes = self._git("remote", check=False).stdout.split()
            if "origin" in remotes:
                self._git("remote", "set-url", "origin", self.repo_url)
            else:
                self._git("remote", "add", "origin", self.repo_url)
        if self.deploy_key_path:
            # Use the scoped deploy key for all git transport in this repo (KTD9).
            self._git(
                "config",
                "core.sshCommand",
                f"ssh -i {self.deploy_key_path} -o IdentitiesOnly=yes "
                "-o StrictHostKeyChecking=accept-new",
            )

    def write_files(self, files: Mapping[str, str]) -> None:
        for rel, content in files.items():
            path = self.local_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def commit(self, message: str) -> bool:
        """Stage everything and commit. Returns False when there is nothing to commit."""
        self._git("add", "-A")
        if not self._git("status", "--porcelain").stdout.strip():
            return False
        self._git("commit", "-m", message)
        return True

    def push(self) -> None:
        self._git("push", "-u", "origin", "main")

    def sync(self, files: Mapping[str, str], message: str, *, push: bool = False) -> bool:
        """Write files, commit, optionally push. Returns True if a commit was made."""
        self.ensure_repo()
        self.write_files(files)
        changed = self.commit(message)
        if changed and push and self.repo_url:
            self.push()
        return changed
