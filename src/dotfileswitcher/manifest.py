from __future__ import annotations

import importlib.resources
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ManifestError


@dataclass(frozen=True)
class SourceSpec:
    type: str
    url: str
    branch: str = "main"
    pinned_revision: str | None = None
    update_policy: str = "stable"


@dataclass(frozen=True)
class LinkSpec:
    source: str
    target: str
    required: bool = True


@dataclass(frozen=True)
class HealthCheck:
    type: str
    value: str
    timeout: int = 15


@dataclass(frozen=True)
class ProfileManifest:
    name: str
    display_name: str
    source: SourceSpec
    links: list[LinkSpec]
    stop: list[list[str]] = field(default_factory=list)
    start: list[list[str]] = field(default_factory=list)
    health: list[HealthCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any], manifest_path: Path) -> ProfileManifest:
        _reject_unknown_keys(
            data,
            {"profile", "source", "links", "commands", "health", "notes"},
            manifest_path,
            "manifest",
        )
        try:
            source_data = data["source"]
            links_data = data["links"]
            profile_data = data["profile"]
            name = profile_data["name"]
        except KeyError as exc:
            raise ManifestError(f"{manifest_path}: missing key {exc}") from exc

        _reject_unknown_keys(profile_data, {"name", "display_name"}, manifest_path, "profile")
        _reject_unknown_keys(
            source_data,
            {"type", "url", "branch", "pinned_revision", "update_policy"},
            manifest_path,
            "source",
        )
        if not str(name).strip():
            raise ManifestError(f"{manifest_path}: profile.name must not be empty")

        source = SourceSpec(
            type=str(source_data.get("type", "git")),
            url=_required_str(source_data, "url", manifest_path, "source"),
            branch=str(source_data.get("branch", "main")),
            pinned_revision=source_data.get("pinned_revision"),
            update_policy=str(source_data.get("update_policy", "stable")),
        )
        if not source.url.strip() or not source.branch.strip():
            raise ManifestError(f"{manifest_path}: source url and branch must not be empty")
        if source.type != "git":
            raise ManifestError(f"{manifest_path}: only git sources are supported right now")
        if source.update_policy not in {"stable", "upstream"}:
            raise ManifestError(f"{manifest_path}: update_policy must be stable or upstream")

        if not isinstance(links_data, list):
            raise ManifestError(f"{manifest_path}: links must be an array")

        links: list[LinkSpec] = []
        seen_targets: set[str] = set()
        for item in links_data:
            if not isinstance(item, dict):
                raise ManifestError(f"{manifest_path}: invalid link entry: {item!r}")
            _reject_unknown_keys(item, {"source", "target", "required"}, manifest_path, "links")
            required = item.get("required", True)
            if not isinstance(required, bool):
                raise ManifestError(f"{manifest_path}: link required must be a boolean")
            link = LinkSpec(
                source=_required_str(item, "source", manifest_path, "links"),
                target=_required_str(item, "target", manifest_path, "links"),
                required=required,
            )
            if not link.source.strip() or not link.target.strip():
                raise ManifestError(f"{manifest_path}: link source and target must not be empty")
            if link.target in seen_targets:
                raise ManifestError(f"{manifest_path}: duplicate link target: {link.target}")
            seen_targets.add(link.target)
            links.append(link)
        if not links:
            raise ManifestError(f"{manifest_path}: profile must define at least one link")

        commands = data.get("commands", {})
        if not isinstance(commands, dict):
            raise ManifestError(f"{manifest_path}: commands must be a table")
        _reject_unknown_keys(commands, {"stop", "start"}, manifest_path, "commands")
        health_table = data.get("health", {})
        if not isinstance(health_table, dict):
            raise ManifestError(f"{manifest_path}: health must be a table")
        _reject_unknown_keys(health_table, {"checks"}, manifest_path, "health")
        health_data = health_table.get("checks", [])
        if not isinstance(health_data, list):
            raise ManifestError(f"{manifest_path}: health.checks must be an array")
        health = [_health_check(check, manifest_path) for check in health_data]
        notes = data.get("notes", [])
        if not isinstance(notes, list):
            raise ManifestError(f"{manifest_path}: notes must be an array")
        return cls(
            name=str(name),
            display_name=str(profile_data.get("display_name", name)),
            source=source,
            links=links,
            stop=_commands(commands.get("stop", []), manifest_path),
            start=_commands(commands.get("start", []), manifest_path),
            health=health,
            notes=[str(note) for note in notes],
        )


def _commands(items: list[Any], manifest_path: Path) -> list[list[str]]:
    commands: list[list[str]] = []
    for item in items:
        if isinstance(item, str):
            raise ManifestError(
                f"{manifest_path}: commands must be argv arrays, not shell strings: {item}"
            )
        if not isinstance(item, list) or not all(isinstance(part, str) for part in item):
            raise ManifestError(f"{manifest_path}: invalid command entry: {item!r}")
        if not item:
            raise ManifestError(f"{manifest_path}: command entries must not be empty")
        commands.append(item)
    return commands


def _health_check(check: Any, manifest_path: Path) -> HealthCheck:
    if not isinstance(check, dict):
        raise ManifestError(f"{manifest_path}: invalid health check entry: {check!r}")
    _reject_unknown_keys(check, {"type", "value", "timeout"}, manifest_path, "health.checks")
    try:
        timeout = int(check.get("timeout", 15))
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{manifest_path}: health check timeout must be an integer") from exc
    result = HealthCheck(
        type=_required_str(check, "type", manifest_path, "health.checks"),
        value=_required_str(check, "value", manifest_path, "health.checks"),
        timeout=timeout,
    )
    if result.type not in {"path_exists", "source_path_exists", "command"}:
        raise ManifestError(f"{manifest_path}: unknown health check type: {result.type}")
    if not result.value.strip():
        raise ManifestError(f"{manifest_path}: health check value must not be empty")
    if result.timeout <= 0:
        raise ManifestError(f"{manifest_path}: health check timeout must be positive")
    return result


def _reject_unknown_keys(
    data: dict[str, Any],
    allowed: set[str],
    manifest_path: Path,
    section: str,
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        names = ", ".join(unknown)
        raise ManifestError(f"{manifest_path}: unknown keys in {section}: {names}")


def _required_str(data: dict[str, Any], key: str, manifest_path: Path, section: str) -> str:
    try:
        value = data[key]
    except KeyError as exc:
        raise ManifestError(f"{manifest_path}: missing key {section}.{key}") from exc
    if not isinstance(value, str):
        raise ManifestError(f"{manifest_path}: {section}.{key} must be a string")
    return value


def load_manifest(path: Path) -> ProfileManifest:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return ProfileManifest.from_dict(data, path)


def built_in_manifest_dir() -> Path:
    return Path(str(importlib.resources.files("dotfileswitcher") / "profiles"))


def discover_manifests(extra_dirs: list[Path] | None = None) -> dict[str, ProfileManifest]:
    manifests: dict[str, ProfileManifest] = {}
    candidates = [built_in_manifest_dir()]
    if extra_dirs:
        candidates.extend(extra_dirs)
    for directory in candidates:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.toml")):
            manifest = load_manifest(path)
            if manifest.name in manifests:
                raise ManifestError(f"duplicate profile manifest: {manifest.name}")
            manifests[manifest.name] = manifest
    return manifests
