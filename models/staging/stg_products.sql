with src as (
    select * from {{ source('thelook', 'products') }}
)

select
    id as product_id,
    name as product_name,
    brand,
    category,
    department,
    cost,
    retail_price,
    sku
from src
