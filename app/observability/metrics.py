from __future__ import annotations

from collections import defaultdict
from threading import Lock


ALLOWED_METRICS = {
    "fx_analyzer_ingestion_runs_total": ("provider", "dataset", "status"),
    "fx_analyzer_ingestion_run_duration_seconds": ("provider", "dataset"),
    "fx_analyzer_provider_requests_total": ("provider", "outcome", "status_class"),
    "fx_analyzer_provider_request_duration_seconds": ("provider",),
    "fx_analyzer_provider_retries_total": ("provider", "reason"),
    "fx_analyzer_observations_total": ("provider", "outcome"),
    "fx_analyzer_quarantined_records_total": ("provider", "reason"),
    "fx_analyzer_quality_state": ("instrument", "state"),
    "fx_analyzer_worker_active_runs": (),
}
HISTOGRAMS = {
    "fx_analyzer_ingestion_run_duration_seconds",
    "fx_analyzer_provider_request_duration_seconds",
}
HISTOGRAM_BUCKETS = (0.01, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0, 300.0, 900.0)


class MetricsRegistry:
    """Small in-process Prometheus text registry with a fixed label schema."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._lock = Lock()

    def increment(self, name: str, amount: float = 1, **labels: str) -> None:
        self._update(name, amount, labels, replace=False)

    def observe(self, name: str, value: float, **labels: str) -> None:
        if name not in HISTOGRAMS:
            raise ValueError("metric is not a histogram")
        self._update(name + "_sum", value, labels, replace=False, base_name=name)
        self._update(name + "_count", 1, labels, replace=False, base_name=name)
        expected = ALLOWED_METRICS[name]
        with self._lock:
            for boundary in (*HISTOGRAM_BUCKETS, float("inf")):
                if value <= boundary:
                    label_values = {**labels, "le": "+Inf" if boundary == float("inf") else f"{boundary:g}"}
                    key = (name + "_bucket", tuple(sorted((item, str(label_values[item])) for item in (*expected, "le"))))
                    self._values[key] += 1

    def gauge(self, name: str, value: float, **labels: str) -> None:
        self._update(name, value, labels, replace=True)

    def render(self) -> str:
        with self._lock:
            rows = sorted(self._values.items())
        lines = []
        for (name, labels), value in rows:
            suffix = "{" + ",".join(f'{key}="{_escape(item)}"' for key, item in labels) + "}" if labels else ""
            lines.append(f"{name}{suffix} {value:g}")
        return "\n".join(lines) + ("\n" if lines else "")

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def _update(self, name: str, value: float, labels: dict[str, str], *, replace: bool,
                base_name: str | None = None) -> None:
        expected = ALLOWED_METRICS.get(base_name or name)
        if expected is None or set(labels) != set(expected):
            raise ValueError("metric name or labels are not in the low-cardinality schema")
        key = (name, tuple(sorted((item, str(labels[item])) for item in expected)))
        with self._lock:
            if replace:
                self._values[key] = value
            else:
                self._values[key] += value


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


metrics = MetricsRegistry()
