from __future__ import annotations

from pathlib import Path

import pytest

from dotfileswitcher.errors import ManifestError, SafetyError, TransactionError
from dotfileswitcher.health import HealthRunner
from dotfileswitcher.manifest import HealthCheck, LinkSpec, ProfileManifest, SourceSpec
from dotfileswitcher.paths import AppPaths, assert_managed_config_path
from dotfileswitcher.runner import Runner
from dotfileswitcher.state import AppState
from dotfileswitcher.switcher import ProfileSwitcher


def make_paths(tmp_path: Path, home: Path) -> AppPaths:
    paths = AppPaths(
        home=home,
        data=tmp_path / "data",
        state=tmp_path / "state",
        cache=tmp_path / "cache",
        sources=tmp_path / "data" / "sources",
        profiles=tmp_path / "data" / "profiles",
        backups=tmp_path / "state" / "backups",
        transactions=tmp_path / "state" / "transactions",
        lock_file=tmp_path / "state" / "lock",
        state_file=tmp_path / "state" / "state.json",
    )
    paths.ensure()
    return paths


def make_manifest(
    name: str,
    links: list[LinkSpec],
    *,
    health: list[HealthCheck] | None = None,
) -> ProfileManifest:
    return ProfileManifest(
        name=name,
        display_name=name.title(),
        source=SourceSpec(type="git", url=f"https://example.invalid/{name}.git"),
        links=links,
        health=health or [],
    )


def test_switch_backs_up_existing_directory_and_rollback(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    existing = home / ".config" / "rofi"
    existing.mkdir(parents=True)
    (existing / "config.rasi").write_text("old")

    source_root = tmp_path / "source"
    source_rofi = source_root / ".config" / "rofi"
    source_rofi.mkdir(parents=True)
    (source_rofi / "config.rasi").write_text("new")

    paths = make_paths(tmp_path, home)
    manifest = make_manifest("fake", [LinkSpec(source=".config/rofi", target="~/.config/rofi")])

    switcher = ProfileSwitcher(paths, Runner())
    state = switcher.switch(manifest, source_root, AppState())

    assert existing.is_symlink()
    assert existing.resolve() == source_rofi

    state = switcher.rollback(state)
    assert not existing.is_symlink()
    assert (existing / "config.rasi").read_text() == "old"


def test_failed_switch_restores_touched_targets(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    existing = home / ".config" / "rofi"
    existing.mkdir(parents=True)
    (existing / "config.rasi").write_text("old")

    source_root = tmp_path / "source"
    source_rofi = source_root / ".config" / "rofi"
    source_rofi.mkdir(parents=True)
    (source_rofi / "config.rasi").write_text("new")

    manifest = make_manifest(
        "fake",
        [LinkSpec(source=".config/rofi", target="~/.config/rofi")],
        health=[HealthCheck(type="path_exists", value="~/.config/definitely-missing")],
    )

    switcher = ProfileSwitcher(make_paths(tmp_path, home), Runner())

    with pytest.raises(TransactionError):
        switcher.switch(manifest, source_root, AppState())

    assert not existing.is_symlink()
    assert (existing / "config.rasi").read_text() == "old"


def test_switch_rejects_source_path_escape(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    source_root = tmp_path / "source"
    source_root.mkdir()
    manifest = make_manifest("fake", [LinkSpec(source="../outside", target="~/.config/rofi")])

    switcher = ProfileSwitcher(make_paths(tmp_path, home), Runner())

    with pytest.raises(SafetyError):
        switcher.switch(manifest, source_root, AppState())


def test_managed_config_path_rejects_prefix_sibling(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    with pytest.raises(SafetyError):
        assert_managed_config_path(home / ".configevil" / "hypr")


def test_dry_run_switch_does_not_mutate_filesystem(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    existing = home / ".config" / "rofi"
    existing.mkdir(parents=True)
    (existing / "config.rasi").write_text("old")

    source_root = tmp_path / "source"
    source_rofi = source_root / ".config" / "rofi"
    source_rofi.mkdir(parents=True)
    (source_rofi / "config.rasi").write_text("new")

    manifest = make_manifest("fake", [LinkSpec(source=".config/rofi", target="~/.config/rofi")])
    switcher = ProfileSwitcher(make_paths(tmp_path, home), Runner(dry_run=True))
    state = AppState(active_profile="old")

    result = switcher.switch(manifest, source_root, state)

    assert result is state
    assert not existing.is_symlink()
    assert (existing / "config.rasi").read_text() == "old"


def test_rollback_restores_previous_profile_links(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    (source_a / ".config" / "rofi").mkdir(parents=True)
    (source_b / ".config" / "rofi").mkdir(parents=True)

    paths = make_paths(tmp_path, home)
    switcher = ProfileSwitcher(paths, Runner())
    manifest_a = make_manifest("a", [LinkSpec(source=".config/rofi", target="~/.config/rofi")])
    manifest_b = make_manifest("b", [LinkSpec(source=".config/rofi", target="~/.config/rofi")])

    state = switcher.switch(manifest_a, source_a, AppState())
    state = switcher.switch(manifest_b, source_b, state)

    target = home / ".config" / "rofi"
    assert target.resolve() == source_b / ".config" / "rofi"

    state = switcher.rollback(state)

    assert state.active_profile == "a"
    assert state.previous_profile == "b"
    assert target.resolve() == source_a / ".config" / "rofi"


def test_rollback_preserves_unexpected_target_conflict(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    source_root = tmp_path / "source"
    source_rofi = source_root / ".config" / "rofi"
    source_rofi.mkdir(parents=True)

    paths = make_paths(tmp_path, home)
    switcher = ProfileSwitcher(paths, Runner())
    manifest = make_manifest("fake", [LinkSpec(source=".config/rofi", target="~/.config/rofi")])
    state = switcher.switch(manifest, source_root, AppState())

    target = home / ".config" / "rofi"
    target.unlink()
    target.mkdir()
    (target / "unexpected").write_text("user change")

    state = switcher.rollback(state)

    assert not target.exists()
    conflicts = list(paths.backups.glob("rollback-conflict-*-rofi"))
    assert len(conflicts) == 1
    assert (conflicts[0] / "unexpected").read_text() == "user change"
    assert state.active_profile is None


def test_manifest_rejects_duplicate_link_targets(tmp_path):
    data = {
        "profile": {"name": "fake"},
        "source": {"url": "https://example.invalid/fake.git"},
        "links": [
            {"source": "one", "target": "~/.config/rofi"},
            {"source": "two", "target": "~/.config/rofi"},
        ],
    }

    with pytest.raises(ManifestError, match="duplicate link target"):
        ProfileManifest.from_dict(data, tmp_path / "fake.toml")


def test_manifest_rejects_unknown_keys(tmp_path):
    data = {
        "profile": {"name": "fake"},
        "source": {"url": "https://example.invalid/fake.git"},
        "links": [{"source": "one", "target": "~/.config/rofi"}],
        "surprise": True,
    }

    with pytest.raises(ManifestError, match="unknown keys"):
        ProfileManifest.from_dict(data, tmp_path / "fake.toml")


def test_manifest_rejects_shell_start_commands(tmp_path):
    data = {
        "profile": {"name": "fake"},
        "source": {"url": "https://example.invalid/fake.git"},
        "links": [{"source": "one", "target": "~/.config/rofi"}],
        "commands": {"start": ["hyprctl reload"]},
    }

    with pytest.raises(ManifestError, match="argv arrays"):
        ProfileManifest.from_dict(data, tmp_path / "fake.toml")


def test_manifest_rejects_non_boolean_required(tmp_path):
    data = {
        "profile": {"name": "fake"},
        "source": {"url": "https://example.invalid/fake.git"},
        "links": [{"source": "one", "target": "~/.config/rofi", "required": "yes"}],
    }

    with pytest.raises(ManifestError, match="required must be a boolean"):
        ProfileManifest.from_dict(data, tmp_path / "fake.toml")


def test_manifest_rejects_invalid_health_timeout(tmp_path):
    data = {
        "profile": {"name": "fake"},
        "source": {"url": "https://example.invalid/fake.git"},
        "links": [{"source": "one", "target": "~/.config/rofi"}],
        "health": {"checks": [{"type": "path_exists", "value": "~/.config/rofi", "timeout": 0}]},
    }

    with pytest.raises(ManifestError, match="timeout must be positive"):
        ProfileManifest.from_dict(data, tmp_path / "fake.toml")


def test_health_runner_source_and_path_checks(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    source_root = tmp_path / "source"
    (source_root / ".config" / "rofi").mkdir(parents=True)
    (home / ".config").mkdir()
    (home / ".config" / "existing").write_text("ok")
    manifest = make_manifest(
        "fake",
        [LinkSpec(source=".config/rofi", target="~/.config/rofi")],
        health=[
            HealthCheck(type="source_path_exists", value=".config/rofi"),
            HealthCheck(type="path_exists", value="~/.config/existing"),
        ],
    )

    messages = HealthRunner(Runner()).run(manifest, source_root)

    assert len(messages) == 2


def test_file_lock_serializes_same_process_attempts(tmp_path):
    from dotfileswitcher.lock import FileLock

    lock_path = tmp_path / "lock"
    with FileLock(lock_path):
        assert lock_path.read_text() == "locked\n"
