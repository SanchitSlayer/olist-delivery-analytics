-- Order value (items plus freight) must never be negative.
select order_id, items_value, freight_value, order_value
from {{ ref('fct_orders') }}
where order_value < 0 or items_value < 0 or freight_value < 0
