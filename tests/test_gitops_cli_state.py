from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dotfileswitcher import cli
from dotfileswitcher.errors import StateError
from dotfileswitcher.gitops import GitStore
from dotfileswitcher.manifest import LinkSpec, ProfileManifest, SourceSpec
from dotfileswitcher.runner import Runner
from dotfileswitcher.state import AppState, LinkState


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def commit_all(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            message,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return git(repo, "rev-parse", "HEAD")


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "upstream"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch", "main"], cwd=repo, check=True)
    config = repo / ".config" / "rofi"
    config.mkdir(parents=True)
    (config / "config.rasi").write_text("first")
    first = commit_all(repo, "initial")
    return repo, first


def profile_for(repo: Path, *, pinned_revision: str | None = None) -> ProfileManifest:
    return ProfileManifest(
        name="local",
        display_name="Local",
        source=SourceSpec(
            type="git",
            url=str(repo),
            branch="main",
            pinned_revision=pinned_revision,
            update_policy="stable" if pinned_revision else "upstream",
        ),
        links=[LinkSpec(source=".config/rofi", target="~/.config/rofi")],
    )


def test_gitstore_install_check_and_update_with_local_repo(tmp_path):
    repo, _first = make_repo(tmp_path)
    profile = profile_for(repo)
    store = GitStore(tmp_path / "sources", tmp_path / "staging", Runner())

    installed = store.install(profile)
    assert installed
    assert (store.source_dir(profile) / ".config" / "rofi" / "config.rasi").read_text() == "first"
    assert "up to date" in store.update(profile, check_only=True)

    (repo / ".config" / "rofi" / "config.rasi").write_text("second")
    second = commit_all(repo, "second")

    assert second[:12] in store.update(profile, check_only=True)
    result = store.update(profile)

    assert second[:12] in result
    assert store.revision(profile) == second
    assert (store.source_dir(profile) / ".config" / "rofi" / "config.rasi").read_text() == "second"


def test_gitstore_stable_install_checks_out_pinned_revision(tmp_path):
    repo, first = make_repo(tmp_path)
    (repo / ".config" / "rofi" / "config.rasi").write_text("second")
    commit_all(repo, "second")

    profile = profile_for(repo, pinned_revision=first)
    store = GitStore(tmp_path / "sources", tmp_path / "staging", Runner())

    assert store.install(profile) == first
    assert (store.source_dir(profile) / ".config" / "rofi" / "config.rasi").read_text() == "first"


def test_cli_install_switch_status_and_rollback_with_isolated_home(tmp_path, monkeypatch, capsys):
    repo, _first = make_repo(tmp_path)
    home = tmp_path / "home"
    xdg_data = tmp_path / "xdg-data"
    xdg_state = tmp_path / "xdg-state"
    xdg_cache = tmp_path / "xdg-cache"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))

    project = tmp_path / "project"
    profiles = project / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "local.toml").write_text(
        f"""
[profile]
name = "local"
display_name = "Local Test"

[source]
type = "git"
url = "{repo}"
branch = "main"
update_policy = "upstream"

[[links]]
source = ".config/rofi"
target = "~/.config/rofi"
""".lstrip()
    )
    monkeypatch.chdir(project)

    assert cli.main(["install", "local"]) == 0
    assert "installed local" in capsys.readouterr().out

    assert cli.main(["switch", "local"]) == 0
    output = capsys.readouterr().out
    assert "switched to local" in output
    assert (home / ".config" / "rofi").is_symlink()

    assert cli.main(["status"]) == 0
    output = capsys.readouterr().out
    assert "active:   local" in output
    assert "local        installed=yes" in output

    assert cli.main(["rollback"]) == 0
    assert not (home / ".config" / "rofi").exists()


def test_cli_dry_run_install_does_not_create_xdg_state(tmp_path, monkeypatch, capsys):
    repo, _first = make_repo(tmp_path)
    home = tmp_path / "home"
    xdg_data = tmp_path / "xdg-data"
    xdg_state = tmp_path / "xdg-state"
    xdg_cache = tmp_path / "xdg-cache"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))

    project = tmp_path / "project"
    profiles = project / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "local.toml").write_text(
        f"""
[profile]
name = "local"

[source]
url = "{repo}"

[[links]]
source = ".config/rofi"
target = "~/.config/rofi"
""".lstrip()
    )
    monkeypatch.chdir(project)

    assert cli.main(["--dry-run", "install", "local"]) == 0
    assert "would install local" in capsys.readouterr().out
    assert not xdg_data.exists()
    assert not xdg_state.exists()
    assert not xdg_cache.exists()


def test_cli_dry_run_rollback_does_not_mutate_links(tmp_path, monkeypatch, capsys):
    repo, _first = make_repo(tmp_path)
    home = tmp_path / "home"
    xdg_data = tmp_path / "xdg-data"
    xdg_state = tmp_path / "xdg-state"
    xdg_cache = tmp_path / "xdg-cache"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))

    project = tmp_path / "project"
    profiles = project / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "local.toml").write_text(
        f"""
[profile]
name = "local"

[source]
url = "{repo}"

[[links]]
source = ".config/rofi"
target = "~/.config/rofi"
""".lstrip()
    )
    monkeypatch.chdir(project)

    assert cli.main(["install", "local"]) == 0
    assert cli.main(["switch", "local"]) == 0
    capsys.readouterr()
    target = home / ".config" / "rofi"
    assert target.is_symlink()

    assert cli.main(["--dry-run", "rollback"]) == 0

    assert "would roll back 1 managed link" in capsys.readouterr().out
    assert target.is_symlink()


def test_cli_unknown_profile_returns_error(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.chdir(tmp_path)

    assert cli.main(["switch", "missing"]) == 1

    assert "unknown profile: missing" in capsys.readouterr().err


def test_state_round_trip_and_rejects_invalid_json(tmp_path):
    state_path = tmp_path / "state.json"
    state = AppState(
        active_profile="a",
        previous_profile="b",
        links={
            "/tmp/target": LinkState(
                target="/tmp/source",
                previous=None,
                previous_type="missing",
                backup=None,
            )
        },
        installed_revisions={"a": "abc"},
    )

    state.save(state_path)
    data = json.loads(state_path.read_text())
    assert data["version"] == 1
    loaded = AppState.load(state_path)
    assert loaded.active_profile == "a"
    assert loaded.links["/tmp/target"].target == "/tmp/source"

    state_path.write_text("{not-json")
    with pytest.raises(StateError, match="not valid JSON"):
        AppState.load(state_path)


def test_state_rejects_invalid_shape(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"version": 1, "links": []}))

    with pytest.raises(StateError, match="links"):
        AppState.load(state_path)
