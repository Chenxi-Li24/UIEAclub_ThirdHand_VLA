"""Exception hierarchy exposed by the offline SDK."""

from __future__ import annotations


class VisionSDKError(Exception):
    """Base class for all SDK-owned failures."""


class InputValidationError(VisionSDKError, ValueError):
    """Caller-owned data violates a public SDK contract."""


class ModelLoadError(VisionSDKError, RuntimeError):
    """An optional model dependency or explicitly configured asset is unavailable."""


class ModelContractError(VisionSDKError, RuntimeError):
    """A model adapter returned data outside its declared contract."""


class ExtensionError(VisionSDKError, RuntimeError):
    """A caller-provided extension failed during a named pipeline stage."""

    def __init__(self, stage: str, plugin_name: str, cause: BaseException) -> None:
        self.stage = stage
        self.plugin_name = plugin_name
        self.cause = cause
        super().__init__(f"{stage} extension {plugin_name} failed: {type(cause).__name__}")

