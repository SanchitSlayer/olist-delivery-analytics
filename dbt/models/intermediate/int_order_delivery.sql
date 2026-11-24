-- Delivery timing per order. All day counts compare calendar dates, because
-- the promised (estimated) date has no time of day. An order delivered at 3pm
-- on its promised date is on time, not late.
with orders as (
    select * from {{ ref('stg_orders') }}
),

delivered as (
    select
        *,
        order_status = 'delivered' and delivered_to_customer_at is not null as is_delivered
    from orders
)

select
    order_id,
    order_status,
    purchased_at,
    delivered_to_customer_at,
    estimated_delivery_date,
    is_delivered,
    date_diff('day', cast(purchased_at as date), estimated_delivery_date) as promised_days,
    case when is_delivered
        then date_diff('day', cast(purchased_at as date), cast(delivered_to_customer_at as date))
    end as delivery_days,
    case when is_delivered
        then date_diff('day', estimated_delivery_date, cast(delivered_to_customer_at as date))
    end as days_late,
    case when is_delivered
        then cast(delivered_to_customer_at as date) > estimated_delivery_date
    end as is_late
from delivered
