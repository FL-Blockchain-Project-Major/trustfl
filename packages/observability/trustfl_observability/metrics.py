"""Small Prometheus-compatible metrics registry with no runtime dependency."""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Mapping


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[
            tuple[str, tuple[tuple[str, str], ...]], tuple[int, float, list[float]]
        ] = {}

    @staticmethod
    def _key(labels: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((str(k), str(v)) for k, v in (labels or {}).items()))

    @staticmethod
    def _labels(labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return ""
        return "{" + ",".join(f'{key}="{_escape(value)}"' for key, value in labels) + "}"

    def inc(self, name: str, labels: Mapping[str, str] | None = None, value: float = 1) -> None:
        with self._lock:
            self._counters[(name, self._key(labels))] += value

    def set(self, name: str, value: float, labels: Mapping[str, str] | None = None) -> None:
        with self._lock:
            self._gauges[(name, self._key(labels))] = value

    def observe(self, name: str, value: float, labels: Mapping[str, str] | None = None) -> None:
        key = (name, self._key(labels))
        with self._lock:
            count, total, buckets = self._histograms.get(key, (0, 0.0, []))
            self._histograms[key] = (count + 1, total + value, [*buckets, value])

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"{name}{self._labels(labels)} {value:g}")
            for (name, labels), value in sorted(self._gauges.items()):
                lines.append(f"{name}{self._labels(labels)} {value:g}")
            for (name, labels), (count, total, values) in sorted(self._histograms.items()):
                base = self._labels(labels)
                lines.append(f"{name}_count{base} {count}")
                lines.append(f"{name}_sum{base} {total:g}")
                for quantile in (0.5, 0.9, 0.99):
                    sample = sorted(values)[min(len(values) - 1, int((len(values) - 1) * quantile))]
                    suffix = self._labels((*labels, ("quantile", str(quantile))))
                    lines.append(f"{name}{suffix} {sample:g}")
        return "\n".join(lines) + ("\n" if lines else "")

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


metrics = MetricsRegistry()
