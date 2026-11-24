-- One row per real customer (customer_unique_id). Location comes from the
-- customer's most recent order, since a person can move between orders.
with customer_orders as (
    select
        customers.customer_unique_id,
        customers.zip_code_prefix,
        customers.city,
        customers.state,
        orders.order_id,
        orders.purchased_at
    from {{ ref('stg_customers') }} as customers
    inner join {{ ref('stg_orders') }} as orders using (customer_id)
),

latest_location as (
    select customer_unique_id, zip_code_prefix, city, state
    from customer_orders
    qualify row_number() over (
        partition by customer_unique_id order by purchased_at desc, order_id
    ) = 1
),

order_stats as (
    select
        customer_unique_id,
        count(*)           as order_count,
        min(purchased_at)  as first_order_at,
        max(purchased_at)  as last_order_at
    from customer_orders
    group by customer_unique_id
)

select
    latest_location.customer_unique_id,
    latest_location.zip_code_prefix,
    latest_location.city,
    latest_location.state,
    order_stats.order_count,
    order_stats.order_count > 1 as is_repeat_customer,
    order_stats.first_order_at,
    order_stats.last_order_at
from latest_location
inner join order_stats using (customer_unique_id)
