from __future__ import annotations

import shutil
import time
from pathlib import Path

from .manifest import ProfileManifest
from .runner import Runner


class GitStore:
    def __init__(self, sources_dir: Path, staging_dir: Path, runner: Runner) -> None:
        self.sources_dir = sources_dir
        self.staging_dir = staging_dir
        self.runner = runner

    def source_dir(self, profile: ProfileManifest) -> Path:
        return self.sources_dir / profile.name

    def is_installed(self, profile: ProfileManifest) -> bool:
        return (self.source_dir(profile) / ".git").exists()

    def install(self, profile: ProfileManifest) -> str:
        dest = self.source_dir(profile)
        if self.runner.dry_run:
            self._plan_stage_clone(profile)
            return "dry-run"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not self.is_installed(profile):
            staged = self._stage_clone(profile)
            self._replace_source(profile, staged)
        return self.revision(profile)

    def checkout_policy(self, profile: ProfileManifest) -> str:
        dest = self.source_dir(profile)
        if profile.source.update_policy == "stable" and profile.source.pinned_revision:
            self.runner.run(["git", "fetch", "--all", "--tags"], cwd=dest, timeout=900)
            self.runner.run(
                ["git", "checkout", "--detach", profile.source.pinned_revision],
                cwd=dest,
            )
        else:
            self.runner.run(["git", "checkout", profile.source.branch], cwd=dest)
            self.runner.run(["git", "pull", "--ff-only"], cwd=dest, timeout=900)
        return self.revision(profile)

    def update(self, profile: ProfileManifest, *, check_only: bool = False) -> str:
        dest = self.source_dir(profile)
        if not self.is_installed(profile):
            if self.runner.dry_run:
                self._plan_stage_clone(profile)
                return "dry-run"
            return "not installed"
        if self.runner.dry_run:
            self.runner.run(["git", "fetch", "--all", "--tags"], cwd=dest, timeout=900)
            return "dry-run"
        before = self.revision(profile)
        if check_only:
            self.runner.run(["git", "fetch", "--all", "--tags"], cwd=dest, timeout=900)
            target = self.target_revision(profile)
            if before == target:
                return f"up to date ({before[:12]})"
            return f"update available {before[:12]} -> {target[:12]}"
        staged = self._stage_clone(profile)
        after = self._revision_at(staged)
        if before != after:
            self._replace_source(profile, staged)
        return f"{before[:12]} -> {after[:12]}"

    def revision(self, profile: ProfileManifest) -> str:
        result = self.runner.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.source_dir(profile),
            timeout=30,
        )
        return result.stdout.strip()

    def target_revision(self, profile: ProfileManifest) -> str:
        if profile.source.update_policy == "stable" and profile.source.pinned_revision:
            return profile.source.pinned_revision
        result = self.runner.run(
            ["git", "rev-parse", f"origin/{profile.source.branch}"],
            cwd=self.source_dir(profile),
            timeout=30,
        )
        return result.stdout.strip()

    def _stage_clone(self, profile: ProfileManifest) -> Path:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        staged = self.staging_dir / profile.name
        if staged.exists():
            shutil.rmtree(staged)
        self.runner.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--branch",
                profile.source.branch,
                profile.source.url,
                str(staged),
            ],
            timeout=900,
        )
        if profile.source.update_policy == "stable" and profile.source.pinned_revision:
            self.runner.run(
                ["git", "checkout", "--detach", profile.source.pinned_revision],
                cwd=staged,
            )
        return staged

    def _plan_stage_clone(self, profile: ProfileManifest) -> Path:
        staged = self.staging_dir / profile.name
        self.runner.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--branch",
                profile.source.branch,
                profile.source.url,
                str(staged),
            ],
            timeout=900,
        )
        if profile.source.update_policy == "stable" and profile.source.pinned_revision:
            self.runner.run(
                ["git", "checkout", "--detach", profile.source.pinned_revision],
                cwd=staged,
            )
        return staged

    def _replace_source(self, profile: ProfileManifest, staged: Path) -> None:
        dest = self.source_dir(profile)
        old = dest.with_name(f"{dest.name}.old-{int(time.time())}")
        if dest.exists():
            dest.rename(old)
        staged.rename(dest)
        if old.exists():
            shutil.rmtree(old)

    def _revision_at(self, path: Path) -> str:
        result = self.runner.run(["git", "rev-parse", "HEAD"], cwd=path, timeout=30)
        return result.stdout.strip()
