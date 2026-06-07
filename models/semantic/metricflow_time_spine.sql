{{ config(materialized='table') }}

with days as (
  select date_day
  from unnest(
    generate_date_array(
      date('2015-01-01'),
      date('2035-12-31'),
      interval 1 day
    )
  ) as date_day
)

select date_day
from days
