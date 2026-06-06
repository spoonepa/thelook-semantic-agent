"""
LangGraph metrics agent over the dbt Semantic Layer.

Three tools:
  list_metrics              — discover what metrics exist
  list_dimensions_for_metric — discover what dimensions apply
  query_metric              — execute a metric query

Model: Gemini 2.5 via Vertex AI. Swap MODEL_NAME / ChatVertexAI to use
another provider if you prefer.

Run:
  python agent/metrics_agent.py "what was total revenue by month last year?"
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_vertexai import ChatVertexAI
from langgraph.prebuilt import create_react_agent

from semantic_layer_client import SemanticLayerClient

MODEL_NAME = os.environ.get("AGENT_MODEL", "gemini-2.5-pro")
PROJECT = os.environ.get("GCP_PROJECT")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")

_client = SemanticLayerClient()


# ---------- tools ----------

@tool
def list_metrics() -> str:
    """List every metric defined in the semantic layer.

    Returns a JSON array of objects with keys: name, label, description, type.
    Call this FIRST whenever the user asks a quantitative question, so you know
    which metrics actually exist. You may only query metrics returned here.
    """
    metrics = _client.list_metrics()
    return json.dumps(metrics, indent=2)


@tool
def list_dimensions_for_metric(metric_name: str) -> str:
    """List the dimensions you can group or filter a given metric by.

    Args:
      metric_name: exact metric name from list_metrics, e.g. "revenue".

    Returns a JSON array of dimensions with name, description, type, and
    (for time dimensions) queryableGranularities.
    """
    dims = _client.list_dimensions([metric_name])
    return json.dumps(dims, indent=2)


@tool
def query_metric(
    metrics: list[str],
    group_by: list[dict] | None = None,
    where: list[str] | None = None,
    order_by: list[dict] | None = None,
    limit: int | None = None,
) -> str:
    """Run a Semantic Layer query and return the result rows as JSON.

    Args:
      metrics: list of metric names, e.g. ["revenue", "orders"].
      group_by: list of {"name": "<dim>"} or {"name": "metric_time", "grain": "MONTH"}.
                Valid grains: DAY, WEEK, MONTH, QUARTER, YEAR.
      where: list of MetricFlow filter strings. Use double curly braces and
             Dimension() / TimeDimension(). Examples:
               "{{ Dimension('order_items__user_country') }} = 'United States'"
               "{{ TimeDimension('metric_time', 'MONTH') }} >= '2024-01-01'"
      order_by: list of {"descending": bool, "metric": {"name": "..."}} or
                {"descending": bool, "groupBy": {"name": "...", "grain": "..."}}.
      limit: integer row limit.

    Returns JSON with keys: columns, rows, sql.
    """
    result = _client.query(
        metrics=metrics,
        group_by=group_by,
        where=where,
        order_by=order_by,
        limit=limit,
    )
    # Keep it compact for the model context
    return json.dumps(
        {
            "columns": [c.get("name") for c in result["columns"]],
            "rows": result["rows"][:200],  # safety cap
            "row_count": len(result["rows"]),
            "sql": result["sql"],
        },
        indent=2,
        default=str,
    )


# ---------- agent ----------

SYSTEM_PROMPT = """You are a retail analytics assistant. You answer business
questions by querying a governed semantic layer.

RULES:
1. Always call `list_metrics` first when a question is quantitative. Never invent
   a metric name. If the user asks for something not in the metric list, do not
   approximate — ask a clarifying question or say it isn't defined.
2. Call `list_dimensions_for_metric` before grouping or filtering, to verify the
   dimension name and (for time) the available grains. Dimension names are
   fully-qualified, e.g. `order_items__user_country` — copy them exactly.
3. Use `query_metric` to fetch data. Prefer fewer, well-targeted calls over
   many small ones. Always set a `limit` for grouped queries (default 50).
4. When showing results, summarize concisely. Mention the metric definition
   used so the user can audit it. Do not show raw SQL unless asked.
5. If a query returns zero rows, do not retry blindly. Inspect the filter and
   ask the user if it might be wrong.
6. Do not perform calculations the semantic layer can do — ask it for the ratio
   metric instead (e.g. use `gross_margin_pct`, don't divide gross_profit by
   revenue yourself).

Today's date is 2026-05-27. The dataset is e-commerce orders covering ~2019
through present in the source data.
"""


def build_agent():
    llm = ChatVertexAI(
        model_name=MODEL_NAME,
        project=PROJECT,
        location=LOCATION,
        temperature=0,
    )
    tools = [list_metrics, list_dimensions_for_metric, query_metric]
    return create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)


def ask(question: str) -> dict[str, Any]:
    """Run one question through the agent and return the final state."""
    agent = build_agent()
    return agent.invoke({"messages": [HumanMessage(content=question)]})


def main():
    if len(sys.argv) < 2:
        print('Usage: python metrics_agent.py "your question"')
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    state = ask(question)
    final = state["messages"][-1]
    print("\n=== Answer ===\n")
    print(final.content)
    print("\n=== Tool calls ===")
    for m in state["messages"]:
        if getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                print(f"- {tc['name']}({json.dumps(tc['args'], default=str)[:200]})")


if __name__ == "__main__":
    main()
