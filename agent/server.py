"""FastAPI wrapper around the LangGraph metrics agent.

Endpoints:
  GET  /health   liveness check, no auth required by app (Cloud Run IAM enforces auth)
  POST /ask      {"question": "..."} -> {"answer", "metrics_used", "dimensions_used", ...}

Logs one JSON line per request to stdout. Cloud Logging parses the
`severity`/`message` envelope and puts the rest in `jsonPayload`.
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from metrics_agent import build_agent


# ---------- structured logging ----------

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload, default=str)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(_JsonFormatter())
_logger = logging.getLogger("agent")
_logger.setLevel(logging.INFO)
_logger.handlers = [_handler]
_logger.propagate = False


def _log(message: str, level: int = logging.INFO, **fields: Any) -> None:
    _logger.log(level, message, extra={"extra_fields": fields})


# ---------- agent singleton ----------

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


# ---------- request/response models ----------

class AskRequest(BaseModel):
    question: str


def _extract_usage(state: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Pull metric and dimension names out of the agent's tool-call history."""
    metrics: set[str] = set()
    dims: set[str] = set()
    for m in state.get("messages", []):
        for tc in getattr(m, "tool_calls", None) or []:
            if tc.get("name") != "query_metric":
                continue
            args = tc.get("args", {}) or {}
            for mn in args.get("metrics") or []:
                metrics.add(mn)
            for gb in args.get("group_by") or []:
                if name := gb.get("name"):
                    dims.add(name)
            for w in args.get("where") or []:
                if "Dimension(" in w:
                    inner = w.split("Dimension(", 1)[1].split(")", 1)[0]
                    dims.add(inner.strip().strip("'\""))
                if "TimeDimension(" in w:
                    dims.add("metric_time")
    return sorted(metrics), sorted(dims)


# ---------- app ----------

app = FastAPI(title="thelook semantic agent")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask")
def ask_endpoint(req: AskRequest, request: Request) -> dict[str, Any]:
    # Cloud Run sets X-Cloud-Trace-Context as "TRACE_ID/SPAN_ID;o=N"
    trace_header = request.headers.get("x-cloud-trace-context", "")
    request_id = trace_header.split("/")[0] if trace_header else str(uuid.uuid4())

    started = time.time()
    _log("request_received", request_id=request_id, question=req.question)

    try:
        agent = _get_agent()
        state = agent.invoke({"messages": [HumanMessage(content=req.question)]})
    except Exception as e:
        latency_ms = int((time.time() - started) * 1000)
        _log(
            "request_failed",
            level=logging.ERROR,
            request_id=request_id,
            question=req.question,
            error=f"{type(e).__name__}: {e}",
            latency_ms=latency_ms,
        )
        raise

    answer = state["messages"][-1].content
    metrics_used, dims_used = _extract_usage(state)
    status = "answered" if metrics_used else "no_query"
    latency_ms = int((time.time() - started) * 1000)

    _log(
        "request_completed",
        request_id=request_id,
        question=req.question,
        status=status,
        metrics_used=metrics_used,
        dimensions_used=dims_used,
        latency_ms=latency_ms,
    )

    return {
        "request_id": request_id,
        "answer": answer,
        "status": status,
        "metrics_used": metrics_used,
        "dimensions_used": dims_used,
        "latency_ms": latency_ms,
    }
