from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import SafetyError


def xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))


def xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))


def xdg_cache_home() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))


@dataclass(frozen=True)
class AppPaths:
    home: Path
    data: Path
    state: Path
    cache: Path
    sources: Path
    profiles: Path
    backups: Path
    transactions: Path
    lock_file: Path
    state_file: Path

    @classmethod
    def defaults(cls) -> AppPaths:
        data = xdg_data_home() / "dotfileswitcher"
        state = xdg_state_home() / "dotfileswitcher"
        cache = xdg_cache_home() / "dotfileswitcher"
        return cls(
            home=Path.home(),
            data=data,
            state=state,
            cache=cache,
            sources=data / "sources",
            profiles=data / "profiles",
            backups=state / "backups",
            transactions=state / "transactions",
            lock_file=state / "lock",
            state_file=state / "state.json",
        )

    def ensure(self) -> None:
        for path in (
            self.data,
            self.state,
            self.cache,
            self.sources,
            self.profiles,
            self.backups,
            self.transactions,
        ):
            path.mkdir(parents=True, exist_ok=True)


def expand_user_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def assert_under_home(path: Path, home: Path | None = None) -> Path:
    home = (home or Path.home()).resolve()
    resolved = path.expanduser()
    comparable = Path(os.path.abspath(resolved))
    try:
        comparable.relative_to(home)
    except ValueError as exc:
        raise SafetyError(f"refusing to manage path outside HOME: {path}") from exc
    return resolved


def assert_managed_config_path(path: Path) -> Path:
    home = Path.home().resolve()
    resolved = assert_under_home(path, home)
    allowed = [
        home / ".config",
        home / ".local/bin",
        home / ".local/share",
        home / ".cache",
        home / ".icons",
        home / ".themes",
    ]
    absolute = Path(os.path.abspath(resolved))
    if not any(_is_relative_to(absolute, root) for root in allowed):
        raise SafetyError(f"refusing to switch unmanaged destination: {path}")
    return resolved


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
