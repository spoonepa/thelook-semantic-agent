# thelook_semantic — dbt Semantic Layer learning project

A minimal dbt + MetricFlow project over Google's `bigquery-public-data.thelook_ecommerce`
dataset. Designed to fit inside a dbt Cloud trial and feed a LangGraph agent.

## Layout

```
models/
  staging/      views over the public source tables
  marts/        fct_order_items — the fact table at line-item grain
  semantic/     sem_order_items.yml — semantic model + metrics
```

## Setup

1. **dbt Cloud trial.** Sign up; you get Starter-tier Owner access with the
   Semantic Layer enabled, up to 1,000 queried metrics/month.
2. **BigQuery connection.** Create a GCP service account with
   `BigQuery Data Viewer` + `BigQuery Job User` on your own project (queries
   against the public dataset are billed to your project). Upload the JSON
   key when configuring the connection in dbt Cloud.
3. **Repo.** Push this project to GitHub, connect it in dbt Cloud.
4. **Deploy.** Create a deployment environment, run `dbt build` once to
   materialize the marts.
5. **Enable Semantic Layer.** Account settings → Projects → your project →
   Semantic Layer section. Pick the deployment environment.
6. **Service token.** Account settings → API tokens → service tokens. Create
   one with `Semantic Layer Only` + `Metadata Only` permissions. Save the
   token, environment ID, and GraphQL host.

## Metrics defined

Simple: `revenue`, `cost`, `gross_profit`, `orders`, `customers`,
`items_sold`, `items_returned`.

Ratio: `gross_margin_pct`, `average_order_value`, `return_rate`.

## Test from CLI before wiring up the agent

```bash
dbt deps
dbt build
mf list metrics
mf list dimensions --metrics revenue
mf query --metrics revenue,orders --group-by metric_time__month --order metric_time__month
mf query --metrics gross_margin_pct --group-by product_category --order -gross_margin_pct --limit 10
mf query --metrics return_rate --group-by user_country --where "{{ Dimension('order_items__user_country') }} in ('United States','Brazil','China')"
```

## GraphQL test from the dbt Cloud Semantic Layer

```graphql
mutation {
  createQuery(
    environmentId: <YOUR_ENV_ID>
    metrics: [{name: "revenue"}, {name: "average_order_value"}]
    groupBy: [{name: "metric_time", grain: MONTH}]
    orderBy: [{descending: false, groupBy: {name: "metric_time", grain: MONTH}}]
  ) { queryId }
}
```

Then poll with `query { query(environmentId: ..., queryId: "...") { status sql jsonResult } }`.

## Agent

`agent/metrics_agent.py` — LangGraph ReAct agent with three tools backed by
`agent/semantic_layer_client.py`:

- `list_metrics` — calls the GraphQL metrics query for catalog discovery
- `list_dimensions_for_metric` — what dimensions a metric supports
- `query_metric` — `createQuery` + poll for results

Model: Gemini 2.5 Pro via Vertex AI (swap in `metrics_agent.py` if you prefer
Claude or another provider).

### Environment

```bash
export DBT_SL_HOST="semantic-layer.cloud.getdbt.com"   # from dbt Cloud
export DBT_SL_ENV_ID="123456"                          # numeric env id
export DBT_SL_TOKEN="dbts_..."                         # service token
export GCP_PROJECT="your-gcp-project"
export GCP_LOCATION="us-central1"
gcloud auth application-default login
```

### Install and run

```bash
cd agent
pip install -r requirements.txt
python metrics_agent.py "what was revenue by product category last quarter?"
```

## Eval harness

`eval/run_eval.py` runs 20 questions in `eval/eval_cases.py` through the agent
and scores three things per case:

- did it call the expected metric(s) and nothing extra
- did it use the expected dimension(s) in `group_by` or `where`
- for out-of-scope questions, did it correctly NOT call `query_metric`

```bash
cd eval
python run_eval.py                       # full set
python run_eval.py --ids Q01 Q07 Q16     # subset
```

Results land in `eval/results/` as JSONL (full traces) + CSV (summary).

Categories covered:
- simple metric + time filter
- categorical & time grouping
- ratio metrics (must use `average_order_value`, not hand-compute)
- multi-metric queries
- filter vs group_by disambiguation
- ambiguous queries (should clarify)
- out-of-scope (LTV, NPS — should refuse, not invent)
- subtle traps (items_sold vs orders)
