"""
Evaluation set for the metrics agent.

Each case has:
  question        the natural-language input
  expected_metrics  metric names the agent SHOULD call (any order)
  expected_dims    dimension names (without the order_items__ prefix) the agent
                   should group or filter by; [] if none required
  category        what this case is testing
  notes           why it's interesting; what failure modes it catches
  out_of_scope    if True, the right behavior is to NOT call query_metric and
                   instead clarify or refuse
"""

EVAL_CASES = [
    # --- simple metric retrieval ---
    {
        "id": "Q01",
        "question": "What was our total revenue last year?",
        "expected_metrics": ["revenue"],
        "expected_dims": [],
        "category": "simple_metric_with_time_filter",
        "notes": "Tests basic metric pick + relative time filter resolution.",
    },
    {
        "id": "Q02",
        "question": "How many distinct customers bought from us in 2024?",
        "expected_metrics": ["customers"],
        "expected_dims": [],
        "category": "simple_metric_with_time_filter",
        "notes": "Should NOT pick items_sold or orders. Distinct-count metric.",
    },
    {
        "id": "Q03",
        "question": "How many orders did we have in Q1 2025?",
        "expected_metrics": ["orders"],
        "expected_dims": [],
        "category": "simple_metric_with_time_filter",
        "notes": "Quarter-grain filter; should not return items_sold.",
    },

    # --- grouping ---
    {
        "id": "Q04",
        "question": "Show me revenue by month for the last 12 months.",
        "expected_metrics": ["revenue"],
        "expected_dims": ["metric_time"],
        "category": "time_grouping",
        "notes": "Tests month grain selection.",
    },
    {
        "id": "Q05",
        "question": "Which product categories generated the most revenue?",
        "expected_metrics": ["revenue"],
        "expected_dims": ["product_category"],
        "category": "categorical_grouping",
        "notes": "Should add an order_by + limit on its own.",
    },
    {
        "id": "Q06",
        "question": "Break down orders by traffic source.",
        "expected_metrics": ["orders"],
        "expected_dims": ["traffic_source"],
        "category": "categorical_grouping",
        "notes": "Straightforward grouping.",
    },

    # --- ratio metrics (semantic-layer-native, must not be hand-computed) ---
    {
        "id": "Q07",
        "question": "What's our average order value?",
        "expected_metrics": ["average_order_value"],
        "expected_dims": [],
        "category": "ratio_metric",
        "notes": "MUST use AOV metric, not revenue/orders division.",
    },
    {
        "id": "Q08",
        "question": "What's the gross margin percentage by product category?",
        "expected_metrics": ["gross_margin_pct"],
        "expected_dims": ["product_category"],
        "category": "ratio_metric",
        "notes": "Must use gross_margin_pct, not compute it manually.",
    },
    {
        "id": "Q09",
        "question": "What's our return rate by department?",
        "expected_metrics": ["return_rate"],
        "expected_dims": ["product_department"],
        "category": "ratio_metric",
        "notes": "return_rate metric exists; agent shouldn't divide returns/items.",
    },

    # --- multi-metric ---
    {
        "id": "Q10",
        "question": "Show revenue and gross profit by month for 2024.",
        "expected_metrics": ["revenue", "gross_profit"],
        "expected_dims": ["metric_time"],
        "category": "multi_metric",
        "notes": "One query, two metrics; tests batching.",
    },
    {
        "id": "Q11",
        "question": "How do AOV and orders compare across traffic sources?",
        "expected_metrics": ["average_order_value", "orders"],
        "expected_dims": ["traffic_source"],
        "category": "multi_metric",
        "notes": "Multi-metric with grouping.",
    },

    # --- filtering ---
    {
        "id": "Q12",
        "question": "What was revenue in the United States last quarter?",
        "expected_metrics": ["revenue"],
        "expected_dims": ["user_country"],
        "category": "filter",
        "notes": "user_country filter, not group_by. Tests where-clause syntax.",
    },
    {
        "id": "Q13",
        "question": "Top 10 product categories by revenue in 2024.",
        "expected_metrics": ["revenue"],
        "expected_dims": ["product_category"],
        "category": "filter_plus_limit",
        "notes": "Should set limit=10 and order by revenue desc.",
    },

    # --- ambiguity / disambiguation ---
    {
        "id": "Q14",
        "question": "How are we doing this month?",
        "expected_metrics": [],
        "expected_dims": [],
        "category": "ambiguous",
        "notes": "Agent should clarify which metric, not silently pick one.",
        "out_of_scope": True,
    },
    {
        "id": "Q15",
        "question": "Show me sales.",
        "expected_metrics": ["revenue"],
        "expected_dims": [],
        "category": "ambiguous_resolvable",
        "notes": "Acceptable to map 'sales' to revenue; clarification also OK.",
    },

    # --- out of scope (must NOT invent) ---
    {
        "id": "Q16",
        "question": "What's our customer lifetime value?",
        "expected_metrics": [],
        "expected_dims": [],
        "category": "out_of_scope",
        "notes": "LTV is not defined; agent must refuse, not approximate.",
        "out_of_scope": True,
    },
    {
        "id": "Q17",
        "question": "What's the average time from order to delivery?",
        "expected_metrics": [],
        "expected_dims": [],
        "category": "out_of_scope",
        "notes": "Not defined as a metric; agent must not invent SQL.",
        "out_of_scope": True,
    },
    {
        "id": "Q18",
        "question": "Tell me net promoter score by region.",
        "expected_metrics": [],
        "expected_dims": [],
        "category": "out_of_scope",
        "notes": "Wrong domain. Must refuse, not pick a similar-sounding metric.",
        "out_of_scope": True,
    },

    # --- subtle traps ---
    {
        "id": "Q19",
        "question": "How many items did we sell vs how many distinct orders did we get last year?",
        "expected_metrics": ["items_sold", "orders"],
        "expected_dims": [],
        "category": "metric_disambiguation",
        "notes": "Must NOT use orders for both. Tests items_sold vs orders.",
    },
    {
        "id": "Q20",
        "question": "What is our revenue by brand for women's products only?",
        "expected_metrics": ["revenue"],
        "expected_dims": ["brand", "product_department"],
        "category": "group_plus_filter",
        "notes": "brand in group_by; product_department in where clause.",
    },
]
