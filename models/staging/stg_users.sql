with src as (
    select * from {{ source('thelook', 'users') }}
)

select
    id as user_id,
    first_name,
    last_name,
    email,
    age,
    gender,
    state,
    city,
    country,
    traffic_source,
    cast(created_at as timestamp) as created_at
from src
