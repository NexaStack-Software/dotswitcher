from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from .errors import DotfileSwitcherError, SafetyError, TransactionError
from .health import HealthRunner
from .manifest import ProfileManifest
from .paths import AppPaths, assert_managed_config_path, expand_user_path
from .runner import Runner
from .state import AppState, LinkState


class ProfileSwitcher:
    def __init__(self, paths: AppPaths, runner: Runner) -> None:
        self.paths = paths
        self.runner = runner
        self.health = HealthRunner(runner)

    def switch(self, profile: ProfileManifest, source_dir: Path, state: AppState) -> AppState:
        self._validate_links(profile, source_dir)
        if self.runner.dry_run:
            for link in profile.links:
                target = assert_managed_config_path(expand_user_path(link.target))
                source = self._resolve_link_source(source_dir, link.source)
                print(f"would link {target} -> {source}")
            self._stop(profile)
            self._start(profile)
            self.health.run(profile, source_dir)
            return state

        transaction_id = time.strftime("%Y%m%d-%H%M%S")
        transaction_dir = self.paths.transactions / transaction_id
        transaction_dir.mkdir(parents=True, exist_ok=True)
        touched_links: dict[str, LinkState] = {}

        try:
            self._stop(profile)
            new_links: dict[str, LinkState] = {}
            for link in profile.links:
                target = assert_managed_config_path(expand_user_path(link.target))
                source = self._resolve_link_source(source_dir, link.source)
                previous_target = self._current_symlink_target(target)
                backup = self._replace_link(target, source, transaction_dir)
                link_state = LinkState(
                    target=str(source),
                    previous=previous_target,
                    previous_type=(
                        "directory" if backup else ("symlink" if previous_target else "missing")
                    ),
                    backup=str(backup) if backup else None,
                )
                new_links[str(target)] = link_state
                touched_links[str(target)] = link_state
            self._start(profile)
            self.health.run(profile, source_dir)
            state.previous_links = dict(state.links)
            state.previous_profile = state.active_profile
            state.active_profile = profile.name
            state.links = new_links
            return state
        except Exception as exc:
            self._rollback_links(touched_links)
            raise TransactionError(
                f"switch to {profile.name} failed and rollback was attempted: {exc}"
            ) from exc

    def rollback(self, state: AppState) -> AppState:
        if not state.links:
            raise DotfileSwitcherError("no switch state available for rollback")
        current_links = dict(state.links)
        self._rollback_links(state.links)
        state.active_profile, state.previous_profile = state.previous_profile, state.active_profile
        state.links = state.previous_links
        state.previous_links = current_links
        return state

    def _validate_links(self, profile: ProfileManifest, source_dir: Path) -> None:
        seen_targets: set[Path] = set()
        for link in profile.links:
            target = assert_managed_config_path(expand_user_path(link.target))
            if target in seen_targets:
                raise DotfileSwitcherError(f"{profile.name}: duplicate link target: {target}")
            seen_targets.add(target)
            source = self._resolve_link_source(source_dir, link.source)
            if link.required and not source.exists() and not source.is_symlink():
                raise DotfileSwitcherError(
                    f"{profile.name}: required source path missing: {source} -> {target}"
                )

    def _replace_link(self, target: Path, source: Path, transaction_dir: Path) -> Path | None:
        target.parent.mkdir(parents=True, exist_ok=True)
        backup: Path | None = None

        if target.exists() or target.is_symlink():
            if target.is_symlink():
                target.unlink()
            else:
                backup = transaction_dir / "backup" / self._backup_key(target)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(backup))

        os.symlink(source, target)
        return backup

    def _rollback_links(self, links: dict[str, LinkState]) -> None:
        for target_text, info in links.items():
            target = Path(target_text)
            if target.is_symlink() or target.exists():
                if target.is_symlink():
                    target.unlink()
                else:
                    backup = self._unique_backup_path(target)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(backup))

            if info.backup and Path(info.backup).exists():
                shutil.move(info.backup, str(target))
            elif info.previous:
                previous = Path(info.previous)
                if previous.exists() or previous.is_symlink():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(previous, target)

    def _stop(self, profile: ProfileManifest) -> None:
        for command in profile.stop:
            self.runner.run(self._expand_command(command), check=False, timeout=20)

    def _start(self, profile: ProfileManifest) -> None:
        for command in profile.start:
            self.runner.run(self._expand_command(command), check=False, timeout=20)

    def _backup_key(self, target: Path) -> str:
        try:
            relative = str(target.relative_to(Path.home()))
        except ValueError:
            relative = str(target).replace(str(Path.home()), "home")
        return relative.strip("/").replace("/", "__")

    def _unique_backup_path(self, target: Path) -> Path:
        base = self.paths.backups / f"rollback-conflict-{time.time_ns()}-{target.name}"
        candidate = base
        counter = 1
        while candidate.exists():
            candidate = base.with_name(f"{base.name}-{counter}")
            counter += 1
        return candidate

    def _current_symlink_target(self, target: Path) -> str | None:
        if target.is_symlink():
            return str(target.resolve())
        return None

    def _resolve_link_source(self, source_dir: Path, link_source: str) -> Path:
        relative = Path(link_source)
        if relative.is_absolute() or ".." in relative.parts:
            raise SafetyError(f"refusing link source outside profile source: {link_source}")
        root = source_dir.resolve(strict=False)
        source = (source_dir / relative).resolve(strict=False)
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise SafetyError(
                f"refusing link source outside profile source: {link_source}"
            ) from exc
        return source

    def _expand_command(self, command: list[str]) -> list[str]:
        return [os.path.expanduser(os.path.expandvars(part)) for part in command]
