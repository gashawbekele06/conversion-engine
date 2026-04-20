"""Lightweight tracing: writes JSONL trace rows + (optionally) mirrors to Langfuse.

Every agent tool call, every channel send, every LLM call writes a row
here. The evidence-graph script in Act V walks these rows to verify
numeric claims.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterator

from .config import load_config


@dataclass
class TraceRow:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    started_at: float
    ended_at: float | None
    duration_ms: float | None
    attributes: dict[str, Any]
    status: str  # "ok" | "error" | "skipped"
    error: str | None = None


class Tracer:
    def __init__(self, path: Path | None = None) -> None:
        cfg = load_config()
        self.path = path or (cfg.traces_dir / "trace_log.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._current_trace: str | None = None
        self._current_span: str | None = None

    @contextmanager
    def trace(self, name: str, **attributes: Any) -> Iterator[dict[str, Any]]:
        prev_trace = self._current_trace
        self._current_trace = self._current_trace or f"tr_{uuid.uuid4().hex[:10]}"
        parent = self._current_span
        span_id = f"sp_{uuid.uuid4().hex[:8]}"
        self._current_span = span_id
        started = time.time()
        row_attrs: dict[str, Any] = dict(attributes)
        row = TraceRow(
            trace_id=self._current_trace,
            span_id=span_id,
            parent_span_id=parent,
            name=name,
            started_at=started,
            ended_at=None,
            duration_ms=None,
            attributes=row_attrs,
            status="ok",
        )
        try:
            yield row_attrs  # caller may mutate
        except Exception as exc:  # noqa: BLE001 — we rethrow
            row.status = "error"
            row.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            row.ended_at = time.time()
            row.duration_ms = (row.ended_at - row.started_at) * 1000.0
            row.attributes = row_attrs
            self._write(row)
            self._current_span = parent
            if parent is None:
                self._current_trace = prev_trace

    def _write(self, row: TraceRow) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(row), default=str) + "\n")


_default_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    global _default_tracer
    if _default_tracer is None:
        _default_tracer = Tracer()
    return _default_tracer
