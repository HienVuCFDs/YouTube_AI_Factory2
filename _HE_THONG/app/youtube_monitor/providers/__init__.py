"""Shared provider contracts and routing for YouTube AI Factory."""

from .base import (
    EXECUTION_EXTERNAL_SIDECAR,
    EXECUTION_IN_PROCESS,
    SCENE_ANIMATED_IMAGE,
    SCENE_IMAGE,
    SCENE_VIDEO,
    ProviderAdapter,
    ProviderDescriptor,
    ProviderRequest,
)
from .gateway import ProviderGateway, ProviderGatewayError, ProviderRoutePolicy, ProviderRouteResult
from .scene import FunctionSceneProviderAdapter, SidecarSceneProviderAdapter

__all__ = [
    "EXECUTION_EXTERNAL_SIDECAR",
    "EXECUTION_IN_PROCESS",
    "SCENE_ANIMATED_IMAGE",
    "SCENE_IMAGE",
    "SCENE_VIDEO",
    "FunctionSceneProviderAdapter",
    "ProviderAdapter",
    "ProviderDescriptor",
    "ProviderGateway",
    "ProviderGatewayError",
    "ProviderRoutePolicy",
    "ProviderRouteResult",
    "ProviderRequest",
    "SidecarSceneProviderAdapter",
]
