from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import CommandError


@dataclass
class RunResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


class Runner:
    def __init__(self, dry_run: bool = False, verbose: bool = False) -> None:
        self.dry_run = dry_run
        self.verbose = verbose

    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        timeout: int = 120,
    ) -> RunResult:
        if self.verbose or self.dry_run:
            where = f" (cwd={cwd})" if cwd else ""
            print(f"+ {' '.join(args)}{where}")
        if self.dry_run:
            return RunResult(args, 0, "", "")
        proc = subprocess.run(
            args,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        result = RunResult(args, proc.returncode, proc.stdout, proc.stderr)
        if check and proc.returncode != 0:
            raise CommandError(
                f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr.strip()}"
            )
        return result

    def exists(self, executable: str) -> bool:
        try:
            self.run(["bash", "-lc", f"command -v {executable}"], check=True, timeout=10)
            return True
        except CommandError:
            return False
