# dotfileswitcher

`dotfileswitcher` installs, updates, and switches complete Hyprland dotfile distributions side by side.

The design goal is not to merge themes. Each profile keeps its own upstream configuration, keybindings, scripts, bars, launchers, and shell processes. Switching is done by controlled symlinks, health checks, and rollback snapshots.

## Commands

```bash
dotfileswitcher doctor
dotfileswitcher list
dotfileswitcher install all
dotfileswitcher update --check
dotfileswitcher update all
dotfileswitcher switch jakoolit
dotfileswitcher status
dotfileswitcher rollback
```

Use `--dry-run` before mutating commands to inspect planned external commands and link changes:

```bash
dotfileswitcher --dry-run install noctalia
dotfileswitcher --dry-run switch noctalia
```

## State Layout

By default all managed data lives below:

```text
~/.local/share/dotfileswitcher/
~/.local/state/dotfileswitcher/
~/.cache/dotfileswitcher/
```

The active profile is exposed through symlinks such as:

```text
~/.config/hypr
~/.config/waybar
~/.config/rofi
~/.config/quickshell
```

Existing user paths are backed up before the first managed switch.

## Safety Model

- no automatic `$HOME` mutation during package installation
- profile installs go into managed source directories
- updates happen in staging first
- switching uses a transaction directory
- previous targets are recorded for rollback
- commands are scoped to allow-listed paths under `$HOME`
- manifest link sources are rejected when they are absolute or escape the profile source tree
- each profile defines its own stop/start commands and health checks

`start` and `stop` manifest commands must be argv arrays. Health checks of type `command`
are shell snippets and should only be used in trusted built-in or user-authored manifests.

## Development

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
.venv/bin/python -m build --sdist --wheel
```

## AUR

The AUR package should install only the CLI and built-in manifests. Users opt in explicitly:

```bash
dotfileswitcher init
dotfileswitcher install all
```
