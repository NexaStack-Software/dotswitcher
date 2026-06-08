class DotfileSwitcherError(Exception):
    """Base exception for expected user-facing failures."""


class ManifestError(DotfileSwitcherError):
    """A profile manifest is invalid."""


class SafetyError(DotfileSwitcherError):
    """An operation tried to touch an unmanaged path."""


class CommandError(DotfileSwitcherError):
    """An external command failed."""


class StateError(DotfileSwitcherError):
    """The persisted application state is invalid or unreadable."""


class TransactionError(DotfileSwitcherError):
    """A switch transaction failed."""
