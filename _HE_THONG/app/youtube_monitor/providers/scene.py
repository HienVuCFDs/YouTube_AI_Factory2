from __future__ import annotations

from typing import Callable

from .base import ProviderAdapter, ProviderDescriptor, ProviderRequest


SceneProviderCallable = Callable[[object, dict, object], str]


class FunctionSceneProviderAdapter(ProviderAdapter):
    """Backward-compatible adapter around an existing scene function."""

    def __init__(self, descriptor: ProviderDescriptor, generate: SceneProviderCallable):
        self.descriptor = descriptor
        self._generate = generate

    def execute(self, request: ProviderRequest) -> str:
        return self._generate(
            request.database,
            dict(request.job),
            request.artifact_root,
        )


class SidecarSceneProviderAdapter(ProviderAdapter):
    """Catalog entry for a provider executed by a browser/desktop sidecar."""

    def __init__(self, descriptor: ProviderDescriptor):
        self.descriptor = descriptor

    def execute(self, request: ProviderRequest) -> str:
        # ProviderGateway blocks this before execution. Keeping the method here
        # satisfies the shared interface and gives direct callers a clear error.
        raise RuntimeError(
            f"Provider {self.descriptor.key} is executed by an external sidecar"
        )
