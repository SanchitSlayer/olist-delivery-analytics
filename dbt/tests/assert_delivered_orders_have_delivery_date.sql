-- Known source issue: 8 orders have status "delivered" but no delivery date.
-- They are treated as not delivered (is_late is null) rather than guessed.
{{ config(severity = 'warn') }}

select order_id, order_status, delivered_to_customer_at
from {{ ref('stg_orders') }}
where order_status = 'delivered' and delivered_to_customer_at is null
