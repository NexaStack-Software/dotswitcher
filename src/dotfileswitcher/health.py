from __future__ import annotations

from pathlib import Path

from .errors import DotfileSwitcherError
from .manifest import HealthCheck, ProfileManifest
from .paths import expand_user_path
from .runner import Runner


class HealthRunner:
    def __init__(self, runner: Runner) -> None:
        self.runner = runner

    def run(self, profile: ProfileManifest, source_dir: Path) -> list[str]:
        messages: list[str] = []
        for check in profile.health:
            messages.append(self._run_one(check, source_dir))
        return messages

    def _run_one(self, check: HealthCheck, source_dir: Path) -> str:
        if check.type == "path_exists":
            path = expand_user_path(check.value.replace("{source}", str(source_dir)))
            if not path.exists() and not path.is_symlink():
                raise DotfileSwitcherError(f"health failed: missing path {path}")
            return f"ok path_exists {path}"
        if check.type == "source_path_exists":
            path = source_dir / check.value
            if not path.exists() and not path.is_symlink():
                raise DotfileSwitcherError(f"health failed: missing source path {path}")
            return f"ok source_path_exists {check.value}"
        if check.type == "command":
            self.runner.run(["bash", "-lc", check.value], timeout=check.timeout)
            return f"ok command {check.value}"
        raise DotfileSwitcherError(f"unknown health check type: {check.type}")
