"""
Thin client for the dbt Cloud Semantic Layer GraphQL API.

Three operations the agent needs:
  - list_metrics()         catalog discovery
  - list_dimensions(metric) per-metric dimension discovery
  - query(...)              create + poll for results

Set these env vars before using:
  DBT_SL_HOST          e.g. semantic-layer.cloud.getdbt.com
  DBT_SL_ENV_ID        numeric environment id from dbt Cloud
  DBT_SL_TOKEN         service token with Semantic Layer + Metadata perms
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests


class SemanticLayerError(RuntimeError):
    pass


class SemanticLayerClient:
    def __init__(
        self,
        host: str | None = None,
        environment_id: int | None = None,
        token: str | None = None,
        poll_interval_s: float = 1.0,
        poll_timeout_s: float = 60.0,
    ):
        self.host = host or os.environ["DBT_SL_HOST"]
        self.environment_id = int(environment_id or os.environ["DBT_SL_ENV_ID"])
        self.token = token or os.environ["DBT_SL_TOKEN"]
        self.endpoint = f"https://{self.host}/api/graphql"
        self.poll_interval_s = poll_interval_s
        self.poll_timeout_s = poll_timeout_s

    # ---------- low-level ----------

    def _gql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = requests.post(
            self.endpoint,
            json={"query": query, "variables": variables or {}},
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise SemanticLayerError(body["errors"])
        return body["data"]

    # ---------- discovery ----------

    def list_metrics(self) -> list[dict[str, str]]:
        """Return [{name, description, type, label}, ...] for all metrics."""
        q = """
        query Metrics($environmentId: BigInt!) {
          metrics(environmentId: $environmentId) {
            name
            description
            type
            label
          }
        }
        """
        data = self._gql(q, {"environmentId": self.environment_id})
        return data["metrics"]

    def list_dimensions(self, metrics: list[str]) -> list[dict[str, str]]:
        """Return dimensions usable with the given metric(s)."""
        q = """
        query Dims($environmentId: BigInt!, $metrics: [MetricInput!]!) {
          dimensions(environmentId: $environmentId, metrics: $metrics) {
            name
            description
            type
            queryableGranularities
          }
        }
        """
        return self._gql(
            q,
            {
                "environmentId": self.environment_id,
                "metrics": [{"name": m} for m in metrics],
            },
        )["dimensions"]

    # ---------- query ----------

    def query(
        self,
        metrics: list[str],
        group_by: list[dict[str, str]] | None = None,
        where: list[str] | None = None,
        order_by: list[dict[str, Any]] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """
        Execute a Semantic Layer query and return the result as a dict with
        columns + rows.

        group_by entries look like {"name": "metric_time", "grain": "MONTH"}
                              or  {"name": "product_category"}
        where entries are MetricFlow filter strings, e.g.
            "{{ Dimension('order_items__user_country') }} = 'United States'"
        order_by entries look like
            {"descending": True, "metric": {"name": "revenue"}}
          or
            {"descending": False, "groupBy": {"name": "metric_time", "grain": "MONTH"}}
        """
        create = """
        mutation Create(
          $environmentId: BigInt!
          $metrics: [MetricInput!]!
          $groupBy: [GroupByInput!]
          $where: [WhereInput!]
          $orderBy: [OrderByInput!]
          $limit: Int
        ) {
          createQuery(
            environmentId: $environmentId
            metrics: $metrics
            groupBy: $groupBy
            where: $where
            orderBy: $orderBy
            limit: $limit
          ) { queryId }
        }
        """
        variables: dict[str, Any] = {
            "environmentId": self.environment_id,
            "metrics": [{"name": m} for m in metrics],
        }
        if group_by:
            variables["groupBy"] = group_by
        if where:
            variables["where"] = [{"sql": w} for w in where]
        if order_by:
            variables["orderBy"] = order_by
        if limit is not None:
            variables["limit"] = limit

        query_id = self._gql(create, variables)["createQuery"]["queryId"]

        poll = """
        query Poll($environmentId: BigInt!, $queryId: String!) {
          query(environmentId: $environmentId, queryId: $queryId) {
            status
            sql
            error
            jsonResult
          }
        }
        """
        deadline = time.time() + self.poll_timeout_s
        while time.time() < deadline:
            r = self._gql(
                poll, {"environmentId": self.environment_id, "queryId": query_id}
            )["query"]
            status = r["status"]
            if status == "SUCCESSFUL":
                import json

                parsed = json.loads(r["jsonResult"]) if r.get("jsonResult") else {}
                return {
                    "status": status,
                    "sql": r.get("sql"),
                    "columns": parsed.get("schema", {}).get("fields", []),
                    "rows": parsed.get("data", []),
                }
            if status == "FAILED":
                raise SemanticLayerError(r.get("error") or "query failed")
            time.sleep(self.poll_interval_s)
        raise SemanticLayerError(f"query {query_id} timed out after {self.poll_timeout_s}s")
