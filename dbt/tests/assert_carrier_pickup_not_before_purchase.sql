-- Known source issue: 166 orders show the carrier receiving the parcel
-- before the customer placed the order. Kept as a warning so it stays visible.
-- It does not affect our delivery metrics, which use purchase and customer
-- delivery dates only.
{{ config(severity = 'warn') }}

select order_id, purchased_at, delivered_to_carrier_at
from {{ ref('stg_orders') }}
where delivered_to_carrier_at < purchased_at
