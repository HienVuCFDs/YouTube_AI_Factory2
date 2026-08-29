from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping


SCENE_IMAGE = "scene.image"
SCENE_ANIMATED_IMAGE = "scene.animated_image"
SCENE_VIDEO = "scene.video"

EXECUTION_IN_PROCESS = "in_process"
EXECUTION_EXTERNAL_SIDECAR = "external_sidecar"
ExecutionMode = Literal["in_process", "external_sidecar"]
BillingMode = Literal["subscription", "api", "local", "unknown"]


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """Stable metadata used by the gateway and future orchestrator routing."""

    key: str
    display_name: str
    capabilities: frozenset[str]
    execution_mode: ExecutionMode = EXECUTION_IN_PROCESS
    priority: int = 100
    quality_score: int = 50
    billing_mode: BillingMode = "unknown"
    estimated_unit_cost: float | None = None
    enabled: bool = True
    max_attempts: int = 2
    fallback_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_key = self.key.strip().lower()
        if not normalized_key:
            raise ValueError("Provider key must not be empty")
        if normalized_key != self.key:
            object.__setattr__(self, "key", normalized_key)
        if not self.display_name.strip():
            raise ValueError("Provider display name must not be empty")
        if not self.capabilities:
            raise ValueError("Provider must declare at least one capability")
        if self.execution_mode not in {EXECUTION_IN_PROCESS, EXECUTION_EXTERNAL_SIDECAR}:
            raise ValueError(f"Unsupported provider execution mode: {self.execution_mode}")
        if self.billing_mode not in {"subscription", "api", "local", "unknown"}:
            raise ValueError(f"Unsupported provider billing mode: {self.billing_mode}")
        if not 0 <= int(self.quality_score) <= 100:
            raise ValueError("Provider quality score must be between 0 and 100")
        if int(self.priority) < 0:
            raise ValueError("Provider priority must be non-negative")
        if self.estimated_unit_cost is not None and float(self.estimated_unit_cost) < 0:
            raise ValueError("Provider estimated cost must be non-negative")
        if int(self.max_attempts) < 1:
            raise ValueError("Provider max_attempts must be positive")


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """Provider-neutral payload passed from a worker to an adapter."""

    capability: str
    database: Any
    job: Mapping[str, Any]
    artifact_root: Path


class ProviderAdapter(ABC):
    """Interface every AI/media provider must implement.

    The adapter intentionally receives the existing database and job payload.
    This keeps phase 1 backward-compatible while establishing one contract for
    later MCP/A2A orchestration.
    """

    descriptor: ProviderDescriptor

    def supports(self, capability: str) -> bool:
        return capability in self.descriptor.capabilities

    @abstractmethod
    def execute(self, request: ProviderRequest) -> str:
        """Execute one provider request and return the local output path."""
