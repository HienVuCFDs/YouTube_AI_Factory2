from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .base import (
    EXECUTION_EXTERNAL_SIDECAR,
    ProviderAdapter,
    ProviderDescriptor,
    ProviderRequest,
)


class ProviderGatewayError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderRoutePolicy:
    preferred: tuple[str, ...] = ()
    excluded: frozenset[str] = field(default_factory=frozenset)
    min_quality: int = 0
    max_estimated_cost: float | None = None
    prefer_subscription: bool = True
    allow_external_sidecar: bool = True
    allow_api_billing: bool = True
    allow_subscription_billing: bool = True


@dataclass(frozen=True, slots=True)
class ProviderRouteResult:
    selected: ProviderDescriptor
    candidates: tuple[dict[str, Any], ...]
    reason: str


class ProviderGateway:
    """Single registry and execution entry point for provider adapters."""

    def __init__(self, adapters: Iterable[ProviderAdapter] = ()):
        self._adapters: dict[str, ProviderAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: ProviderAdapter) -> None:
        key = adapter.descriptor.key
        if key in self._adapters:
            raise ProviderGatewayError(f"Provider da duoc dang ky: {key}")
        self._adapters[key] = adapter

    def get(self, provider: str) -> ProviderAdapter | None:
        return self._adapters.get(provider.strip().lower())

    def require(self, provider: str) -> ProviderAdapter:
        key = provider.strip().lower()
        adapter = self.get(key)
        if adapter is None:
            available = ", ".join(sorted(self._adapters)) or "(none)"
            raise ProviderGatewayError(
                f"Scene provider chua duoc ho tro: {key or '(empty)'}. "
                f"Provider da dang ky: {available}"
            )
        return adapter

    def descriptors(
        self,
        *,
        capability: str | None = None,
        execution_mode: str | None = None,
    ) -> tuple[ProviderDescriptor, ...]:
        items = (adapter.descriptor for adapter in self._adapters.values())
        return tuple(
            sorted(
                (
                    descriptor
                    for descriptor in items
                    if (capability is None or capability in descriptor.capabilities)
                    and (execution_mode is None or descriptor.execution_mode == execution_mode)
                ),
                key=lambda descriptor: descriptor.key,
            )
        )

    def provider_keys(
        self,
        *,
        capability: str | None = None,
        execution_mode: str | None = None,
    ) -> tuple[str, ...]:
        return tuple(
            descriptor.key
            for descriptor in self.descriptors(
                capability=capability,
                execution_mode=execution_mode,
            )
        )

    def execute_scene(
        self,
        provider: str,
        database: Any,
        job: Mapping[str, Any],
        artifact_root: Path,
        *,
        capability: str = "",
    ) -> str:
        adapter = self.require(provider)
        descriptor = adapter.descriptor
        if descriptor.execution_mode == EXECUTION_EXTERNAL_SIDECAR:
            raise ProviderGatewayError(
                f"Provider {descriptor.key} chay qua sidecar/web va phai nhan viec tu hang doi ngoai"
            )
        selected_capability = capability or next(iter(descriptor.capabilities))
        if not adapter.supports(selected_capability):
            raise ProviderGatewayError(
                f"Provider {descriptor.key} khong ho tro capability {selected_capability}"
            )
        return adapter.execute(
            ProviderRequest(
                capability=selected_capability,
                database=database,
                job=job,
                artifact_root=Path(artifact_root),
            )
        )

    def route(
        self,
        capability: str,
        *,
        provider_states: Mapping[str, Mapping[str, Any]] | None = None,
        policy: ProviderRoutePolicy | None = None,
    ) -> ProviderRouteResult:
        """Select an available provider using deterministic policy metadata."""
        chosen_policy = policy or ProviderRoutePolicy()
        states = provider_states or {}
        preferred_rank = {
            key.strip().lower(): index
            for index, key in enumerate(chosen_policy.preferred)
            if key.strip()
        }
        ranked: list[tuple[float, ProviderDescriptor, dict[str, Any]]] = []
        rejected: list[dict[str, Any]] = []
        for descriptor in self.descriptors(capability=capability):
            state = dict(states.get(descriptor.key) or {})
            reason = ""
            if descriptor.key in chosen_policy.excluded:
                reason = "excluded_by_policy"
            elif not descriptor.enabled:
                reason = "disabled"
            elif descriptor.billing_mode == "api" and not chosen_policy.allow_api_billing:
                reason = "paid_api_disabled"
            elif (
                descriptor.billing_mode == "subscription"
                and not chosen_policy.allow_subscription_billing
            ):
                reason = "subscription_media_disabled"
            elif descriptor.quality_score < chosen_policy.min_quality:
                reason = "quality_below_minimum"
            elif (
                descriptor.execution_mode == EXECUTION_EXTERNAL_SIDECAR
                and not chosen_policy.allow_external_sidecar
            ):
                reason = "external_sidecar_not_allowed"
            elif state.get("circuit_open"):
                reason = "circuit_open"
            elif state.get("available") is False:
                reason = str(state.get("reason") or "unavailable")
            elif (
                chosen_policy.max_estimated_cost is not None
                and descriptor.estimated_unit_cost is not None
                and descriptor.estimated_unit_cost > chosen_policy.max_estimated_cost
            ):
                reason = "cost_above_limit"
            if reason:
                rejected.append({"provider": descriptor.key, "eligible": False, "reason": reason})
                continue

            score = float(descriptor.quality_score * 10 - descriptor.priority)
            if chosen_policy.prefer_subscription and descriptor.billing_mode in {"subscription", "local"}:
                score += 1000
            if descriptor.estimated_unit_cost is None:
                score -= 50
            else:
                score -= descriptor.estimated_unit_cost * 100
            if descriptor.key in preferred_rank:
                score += 500 - preferred_rank[descriptor.key]
            item = {
                "provider": descriptor.key,
                "eligible": True,
                "score": round(score, 3),
                "quality_score": descriptor.quality_score,
                "priority": descriptor.priority,
                "billing_mode": descriptor.billing_mode,
                "estimated_unit_cost": descriptor.estimated_unit_cost,
                "execution_mode": descriptor.execution_mode,
            }
            ranked.append((score, descriptor, item))

        if not ranked:
            detail = ", ".join(f"{item['provider']}={item['reason']}" for item in rejected)
            raise ProviderGatewayError(
                f"Khong co provider san sang cho capability {capability}. {detail}"
            )
        ranked.sort(key=lambda item: (-item[0], item[1].key))
        selected = ranked[0][1]
        candidates = tuple([item[2] for item in ranked] + rejected)
        return ProviderRouteResult(
            selected=selected,
            candidates=candidates,
            reason=(
                f"Chon {selected.key}: billing={selected.billing_mode}, "
                f"quality={selected.quality_score}, priority={selected.priority}"
            ),
        )
