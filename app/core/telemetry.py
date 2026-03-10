from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FlowTelemetry:
    flow_name: str
    step_name: str
    budget_ms: int | None = None
    started_at: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)

    def finish(self, **extra: Any) -> dict[str, Any]:
        latency_ms = round((time.monotonic() - self.started_at) * 1000, 2)
        payload: dict[str, Any] = {
            "flow_name": self.flow_name,
            "step_name": self.step_name,
            "latency_ms": latency_ms,
        }
        if self.budget_ms is not None:
            payload["budget_ms"] = self.budget_ms
            payload["budget_exceeded"] = latency_ms > self.budget_ms
        payload.update(self.metadata)
        payload.update(extra)
        return payload


def start_flow_telemetry(
    flow_name: str,
    step_name: str,
    *,
    budget_ms: int | None = None,
    **metadata: Any,
) -> FlowTelemetry:
    return FlowTelemetry(
        flow_name=flow_name,
        step_name=step_name,
        budget_ms=budget_ms,
        metadata=dict(metadata),
    )
