from __future__ import annotations

import argparse
import shutil
import sys
from contextlib import nullcontext
from pathlib import Path

from . import __version__
from .errors import DotfileSwitcherError
from .gitops import GitStore
from .lock import FileLock
from .manifest import ProfileManifest, discover_manifests
from .paths import AppPaths
from .runner import Runner
from .state import AppState
from .switcher import ProfileSwitcher


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runner = Runner(dry_run=args.dry_run, verbose=args.verbose)
    paths = AppPaths.defaults()

    try:
        if args.command == "version":
            print(__version__)
            return 0

        manifests = discover_manifests([Path.cwd() / "profiles"])
        state = AppState.load(paths.state_file)

        if args.command == "doctor":
            return cmd_doctor(paths, manifests, runner)
        if args.command == "init":
            paths.ensure()
            return cmd_init(paths)
        if args.command == "list":
            return cmd_list(manifests, state)
        if args.command == "status":
            return cmd_status(paths, manifests, state)

        if not args.dry_run:
            paths.ensure()
        lock = nullcontext() if args.dry_run else FileLock(paths.lock_file)
        with lock:
            store = GitStore(paths.sources, paths.cache / "staging", runner)
            switcher = ProfileSwitcher(paths, runner)
            if args.command == "install":
                return cmd_install(args.profile, manifests, store, state, paths, runner)
            if args.command == "update":
                return cmd_update(args.profile, args.check, manifests, store, state, paths, runner)
            if args.command == "switch":
                return cmd_switch(args.profile, manifests, store, switcher, state, paths, runner)
            if args.command == "rollback":
                if runner.dry_run:
                    if not state.links:
                        raise DotfileSwitcherError("no switch state available for rollback")
                    print(f"would roll back {len(state.links)} managed link(s)")
                    return 0
                state = switcher.rollback(state)
                state.save(paths.state_file)
                print("rolled back to previous profile")
                return 0

        parser.print_help()
        return 2
    except DotfileSwitcherError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dotfileswitcher")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print actions without mutating state",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="print executed commands")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version")
    sub.add_parser("init")
    sub.add_parser("doctor")
    sub.add_parser("list")
    sub.add_parser("status")

    install = sub.add_parser("install")
    install.add_argument("profile", help="profile name or all")

    update = sub.add_parser("update")
    update.add_argument("profile", nargs="?", default="all", help="profile name or all")
    update.add_argument("--check", action="store_true", help="only check for available updates")

    switch = sub.add_parser("switch")
    switch.add_argument("profile")

    sub.add_parser("rollback")
    return parser


def cmd_doctor(
    paths: AppPaths,
    manifests: dict[str, ProfileManifest],
    runner: Runner,
) -> int:
    print("dotfileswitcher doctor")
    print(f"data:  {paths.data}")
    print(f"state: {paths.state}")
    print(f"cache: {paths.cache}")
    missing = [name for name in ("git", "hyprctl") if shutil.which(name) is None]
    if missing:
        print("missing commands: " + ", ".join(missing))
    else:
        print("commands: git ok, hyprctl ok")
    print(f"profiles: {', '.join(sorted(manifests))}")
    return 1 if missing else 0


def cmd_init(paths: AppPaths) -> int:
    paths.ensure()
    print("initialized dotfileswitcher")
    print(f"data:  {paths.data}")
    print(f"state: {paths.state}")
    print("next:  dotfileswitcher doctor && dotfileswitcher install all")
    return 0


def cmd_list(manifests: dict[str, ProfileManifest], state: AppState) -> int:
    for name, manifest in sorted(manifests.items()):
        marker = "*" if state.active_profile == name else " "
        print(f"{marker} {name:12} {manifest.display_name}")
    return 0


def cmd_status(
    paths: AppPaths,
    manifests: dict[str, ProfileManifest],
    state: AppState,
) -> int:
    print(f"active:   {state.active_profile or '-'}")
    print(f"previous: {state.previous_profile or '-'}")
    for name in sorted(manifests):
        source = paths.sources / name
        installed = "yes" if (source / ".git").exists() else "no"
        revision = state.installed_revisions.get(name, "-")
        print(f"{name:12} installed={installed:3} revision={revision}")
    return 0


def cmd_install(
    profile_name: str,
    manifests: dict[str, ProfileManifest],
    store: GitStore,
    state: AppState,
    paths: AppPaths,
    runner: Runner,
) -> int:
    for profile in select_profiles(profile_name, manifests):
        revision = store.install(profile)
        state.installed_revisions[profile.name] = revision
        if runner.dry_run:
            print(f"would install {profile.name}")
        else:
            print(f"installed {profile.name} at {revision[:12]}")
    if not runner.dry_run:
        state.save(paths.state_file)
    return 0


def cmd_update(
    profile_name: str,
    check_only: bool,
    manifests: dict[str, ProfileManifest],
    store: GitStore,
    state: AppState,
    paths: AppPaths,
    runner: Runner,
) -> int:
    for profile in select_profiles(profile_name, manifests):
        result = store.update(profile, check_only=check_only)
        if not check_only and result != "not installed":
            state.installed_revisions[profile.name] = store.revision(profile)
        print(f"{profile.name}: {result}")
    if not runner.dry_run:
        state.save(paths.state_file)
    return 0


def cmd_switch(
    profile_name: str,
    manifests: dict[str, ProfileManifest],
    store: GitStore,
    switcher: ProfileSwitcher,
    state: AppState,
    paths: AppPaths,
    runner: Runner,
) -> int:
    profile = require_profile(profile_name, manifests)
    if not store.is_installed(profile):
        raise DotfileSwitcherError(f"{profile.name} is not installed; run install first")
    state = switcher.switch(profile, store.source_dir(profile), state)
    if runner.dry_run:
        print(f"would switch to {profile.name}")
        return 0
    state.installed_revisions[profile.name] = store.revision(profile)
    state.save(paths.state_file)
    print(f"switched to {profile.name}")
    return 0


def select_profiles(name: str, manifests: dict[str, ProfileManifest]) -> list[ProfileManifest]:
    if name == "all":
        return [manifests[key] for key in sorted(manifests)]
    return [require_profile(name, manifests)]


def require_profile(name: str, manifests: dict[str, ProfileManifest]) -> ProfileManifest:
    try:
        return manifests[name]
    except KeyError as exc:
        raise DotfileSwitcherError(f"unknown profile: {name}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
