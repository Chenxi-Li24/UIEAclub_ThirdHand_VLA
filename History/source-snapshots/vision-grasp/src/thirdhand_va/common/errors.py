"""Shared exception types used at public V/A boundaries."""


class ThirdHandError(Exception):
    """Base class for recoverable ThirdHand domain failures."""


class ContractError(ValueError, ThirdHandError):
    """An external value does not satisfy a public data contract."""


class ConfigurationError(ValueError, ThirdHandError):
    """A configuration value is missing or unsafe."""


class AdapterError(RuntimeError, ThirdHandError):
    """An injected hardware, process, or network adapter failed."""


__all__ = [
    "AdapterError",
    "ConfigurationError",
    "ContractError",
    "ThirdHandError",
]

