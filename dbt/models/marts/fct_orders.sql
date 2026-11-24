-- One row per order: value, items, payment, delivery and review in one place.
-- Orders with no items (775, mostly unavailable or canceled) are kept, with
-- zero value and no main seller or category.
with orders as (
    select * from {{ ref('stg_orders') }}
),

customers as (
    select * from {{ ref('stg_customers') }}
),

sellers as (
    select * from {{ ref('stg_sellers') }}
),

items as (
    select * from {{ ref('int_order_items_summary') }}
),

payments as (
    select * from {{ ref('int_order_payments_summary') }}
),

delivery as (
    select * from {{ ref('int_order_delivery') }}
),

reviews as (
    select * from {{ ref('stg_order_reviews') }}
)

select
    orders.order_id,
    orders.customer_id,
    customers.customer_unique_id,
    customers.state                                      as customer_state,
    orders.order_status,
    orders.purchased_at,
    cast(date_trunc('month', orders.purchased_at) as date) as purchase_month,

    coalesce(items.item_count, 0)                        as item_count,
    coalesce(items.seller_count, 0)                      as seller_count,
    coalesce(items.items_value, 0)                       as items_value,
    coalesce(items.freight_value, 0)                     as freight_value,
    coalesce(items.items_value, 0) + coalesce(items.freight_value, 0) as order_value,
    items.total_weight_g,
    items.total_volume_cm3,
    items.main_seller_id,
    sellers.state                                        as seller_state,
    customers.state = sellers.state                      as is_same_state,
    items.main_category,

    payments.main_payment_type                           as payment_type,
    payments.payment_count,
    payments.payment_total,
    payments.max_installments,

    delivery.estimated_delivery_date,
    orders.delivered_to_customer_at,
    delivery.is_delivered,
    delivery.promised_days,
    delivery.delivery_days,
    delivery.days_late,
    delivery.is_late,

    reviews.review_score,
    reviews.has_comment                                  as review_has_comment
from orders
left join customers using (customer_id)
left join items using (order_id)
left join sellers on items.main_seller_id = sellers.seller_id
left join payments using (order_id)
left join delivery using (order_id)
left join reviews using (order_id)
