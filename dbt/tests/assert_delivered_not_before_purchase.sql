-- A customer cannot receive an order before buying it.
select order_id, purchased_at, delivered_to_customer_at
from {{ ref('stg_orders') }}
where delivered_to_customer_at < purchased_at
