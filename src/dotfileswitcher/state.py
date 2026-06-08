from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .errors import StateError

STATE_VERSION = 1


@dataclass
class LinkState:
    target: str
    previous: str | None
    previous_type: str
    backup: str | None


@dataclass
class AppState:
    active_profile: str | None = None
    previous_profile: str | None = None
    links: dict[str, LinkState] = field(default_factory=dict)
    previous_links: dict[str, LinkState] = field(default_factory=dict)
    installed_revisions: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> AppState:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
        except OSError as exc:
            raise StateError(f"could not read state file {path}: {exc}") from exc
        except JSONDecodeError as exc:
            raise StateError(f"state file is not valid JSON: {path}") from exc
        if not isinstance(data, dict):
            raise StateError(f"state file must contain a JSON object: {path}")
        version = data.get("version", 0)
        if version not in {0, STATE_VERSION}:
            raise StateError(f"unsupported state file version {version}: {path}")
        return cls(
            active_profile=_optional_str(data, "active_profile", path),
            previous_profile=_optional_str(data, "previous_profile", path),
            links=_link_states(data.get("links", {}), path, "links"),
            previous_links=_link_states(data.get("previous_links", {}), path, "previous_links"),
            installed_revisions=_str_dict(
                data.get("installed_revisions", {}),
                path,
                "installed_revisions",
            ),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        data: dict[str, Any] = {
            "version": STATE_VERSION,
            "active_profile": self.active_profile,
            "previous_profile": self.previous_profile,
            "installed_revisions": self.installed_revisions,
            "links": {
                key: {
                    "target": value.target,
                    "previous": value.previous,
                    "previous_type": value.previous_type,
                    "backup": value.backup,
                }
                for key, value in self.links.items()
            },
            "previous_links": {
                key: {
                    "target": value.target,
                    "previous": value.previous,
                    "previous_type": value.previous_type,
                    "backup": value.backup,
                }
                for key, value in self.previous_links.items()
            },
        }
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)


def _optional_str(data: dict[str, Any], key: str, path: Path) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise StateError(f"state field {key} must be a string or null: {path}")
    return value


def _link_states(value: Any, path: Path, field: str) -> dict[str, LinkState]:
    if not isinstance(value, dict):
        raise StateError(f"state field {field} must be an object: {path}")
    links: dict[str, LinkState] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, dict):
            raise StateError(f"state field {field} contains an invalid link entry: {path}")
        target = item.get("target")
        previous = item.get("previous")
        previous_type = item.get("previous_type", "missing")
        backup = item.get("backup")
        if not isinstance(target, str):
            raise StateError(f"state link {key} target must be a string: {path}")
        if previous is not None and not isinstance(previous, str):
            raise StateError(f"state link {key} previous must be a string or null: {path}")
        if not isinstance(previous_type, str):
            raise StateError(f"state link {key} previous_type must be a string: {path}")
        if backup is not None and not isinstance(backup, str):
            raise StateError(f"state link {key} backup must be a string or null: {path}")
        links[key] = LinkState(
            target=target,
            previous=previous,
            previous_type=previous_type,
            backup=backup,
        )
    return links


def _str_dict(value: Any, path: Path, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise StateError(f"state field {field} must be an object of strings: {path}")
    return dict(value)
