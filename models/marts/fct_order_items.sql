with order_items as (
    select * from {{ ref('stg_order_items') }}
),

products as (
    select * from {{ ref('stg_products') }}
),

users as (
    select * from {{ ref('stg_users') }}
)

select
    oi.order_item_id,
    oi.order_id,
    oi.user_id,
    oi.product_id,
    oi.status as item_status,
    oi.created_at as order_created_at,
    oi.shipped_at,
    oi.delivered_at,
    oi.returned_at,
    oi.sale_price,
    p.cost as product_cost,
    p.retail_price,
    p.product_name,
    p.brand,
    p.category as product_category,
    p.department as product_department,
    u.country as user_country,
    u.state as user_state,
    u.city as user_city,
    u.gender as user_gender,
    u.age as user_age,
    u.traffic_source,
    -- derived
    oi.sale_price - p.cost as gross_profit,
    case when oi.returned_at is not null then 1 else 0 end as is_returned
from order_items oi
left join products p on oi.product_id = p.product_id
left join users u on oi.user_id = u.user_id
