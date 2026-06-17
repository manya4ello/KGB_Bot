import subprocess

import pytest

from secretary_bot.knowledge.storage import GitKB, parse_owner_repo, render_project


def _items():
    return [
        {"type": "decision", "statement": "Use SQLite", "rationale": "simple", "participants": ["1"], "source_ids": [5]},
        {"type": "idea", "statement": "Add caching", "rationale": None, "participants": [], "source_ids": []},
        {"type": "argument", "statement": "Caching cuts latency", "source_ids": [7]},
    ]


def test_render_project_produces_all_files():
    files = render_project("proj", "Proj", _items())
    assert set(files) == {
        "projects/proj/decisions.md",
        "projects/proj/ideas.md",
        "projects/proj/arguments.md",
        "projects/proj/index.md",
    }
    assert "Use SQLite" in files["projects/proj/decisions.md"]
    assert "Add caching" in files["projects/proj/ideas.md"]
    assert "Caching cuts latency" in files["projects/proj/arguments.md"]
    assert "Решения" in files["projects/proj/index.md"]


def test_render_is_deterministic():
    assert render_project("p", "P", _items()) == render_project("p", "P", _items())


def test_render_empty_project():
    files = render_project("p", "P", [])
    assert "_Пока пусто._" in files["projects/p/decisions.md"]


def test_parse_owner_repo():
    assert parse_owner_repo("https://github.com/manya4ello/KGB_Bot_Materials") == (
        "manya4ello",
        "KGB_Bot_Materials",
    )
    assert parse_owner_repo("git@github.com:manya4ello/KGB_Bot_Materials.git") == (
        "manya4ello",
        "KGB_Bot_Materials",
    )
    assert parse_owner_repo("https://example.com/x/y") is None


def test_ensure_repo_configures_deploy_key(tmp_path):
    key = tmp_path / "kgb_key"
    key.write_text("dummy", encoding="utf-8")
    kb = GitKB(tmp_path / "kb", deploy_key_path=str(key))
    kb.ensure_repo()
    out = subprocess.run(
        ["git", "config", "core.sshCommand"],
        cwd=tmp_path / "kb",
        capture_output=True,
        text=True,
    )
    assert str(key) in out.stdout


def test_git_sync_commits_and_pushes(tmp_path):
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)

    work = tmp_path / "work"
    kb = GitKB(work, repo_url=str(remote))
    files = render_project("proj", "Proj", _items())

    assert kb.sync(files, "feat: initial knowledge", push=True) is True
    # nothing changed on a second identical sync
    assert kb.sync(files, "noop", push=True) is False

    # verify the push landed in the bare remote
    verify = tmp_path / "verify"
    subprocess.run(["git", "clone", str(remote), str(verify)], check=True, capture_output=True)
    decisions = (verify / "projects" / "proj" / "decisions.md").read_text(encoding="utf-8")
    assert "Use SQLite" in decisions
