# Technical Specification

## Goals

- Install several Hyprland dotfile distributions side by side.
- Keep each distribution as close to upstream as possible.
- Switch between complete profiles, including keybindings.
- Support safe upstream updates.
- Avoid mutating user config during package installation.

## Non Goals

- Merge different dotfiles into one unified configuration.
- Force common keybindings across profiles.
- Hide upstream licensing or ownership.

## Profile Lifecycle

1. `install` clones the upstream source into staging.
2. The staged source is checked out according to the profile update policy.
3. The staged source replaces the managed source directory.
4. `switch` creates symlinks from user config paths to the managed source.
5. `update` repeats the staging flow before replacing the managed source.
6. `rollback` restores the previous profile link state where available.

## Update Policies

`upstream` tracks the configured branch.

`stable` tracks a pinned revision listed in the manifest. This should become the default once the project has CI that validates known-good revisions.

## Safety Rules

- The package installation must not edit `$HOME`.
- Managed destinations must be under allow-listed user paths.
- Shell commands in manifests should be argv arrays.
- Existing non-symlink targets are moved into transaction backups before replacement.
- A lock file prevents concurrent switch/update operations.
- A failed switch must restore every target touched by the in-progress transaction.
- Dry-run mode must not create, move, delete, or relink managed user paths.
- Manifest link sources must be relative paths that remain inside the profile source tree.
- Managed destination checks must use path ancestry, not string prefixes.
- Profile manifests should reject unknown fields, duplicate link targets, invalid command shapes,
  and invalid health checks before switching starts.

## Command Model

Lifecycle commands are argv arrays and are executed without a shell.

Health checks of type `command` are shell snippets. This keeps simple checks compact, but it
means command health checks are trusted manifest content and should not be loaded from
unreviewed sources.

## Profile Adapter Roadmap

Each upstream project has a different layout and installer model. The generic manifest model is enough for simple layouts, but production quality requires per-profile adapters for:

- dependency discovery
- upstream install script compatibility
- generated config files
- split repositories
- services and process lifecycle
- health checks that prove the UI actually started
