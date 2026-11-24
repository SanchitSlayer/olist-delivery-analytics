-- One row per seller with delivery performance. A seller "handled" an order
-- if they shipped at least one item in it, so an order with two sellers
-- counts for both. (fct_orders uses one main seller per order instead.)
with seller_orders as (
    select
        seller_id,
        order_id,
        sum(price) as seller_items_value
    from {{ ref('stg_order_items') }}
    group by seller_id, order_id
),

seller_order_outcomes as (
    select
        seller_orders.seller_id,
        seller_orders.order_id,
        seller_orders.seller_items_value,
        delivery.is_delivered,
        delivery.is_late,
        delivery.delivery_days,
        reviews.review_score
    from seller_orders
    left join {{ ref('int_order_delivery') }} as delivery using (order_id)
    left join {{ ref('stg_order_reviews') }} as reviews using (order_id)
),

seller_stats as (
    select
        seller_id,
        count(*)                                    as orders_handled,
        count(*) filter (where is_delivered)        as delivered_orders,
        count(*) filter (where is_late)             as late_orders,
        avg(delivery_days)                          as avg_delivery_days,
        avg(review_score)                           as avg_review_score,
        count(review_score)                         as reviewed_orders,
        sum(seller_items_value)                     as items_revenue
    from seller_order_outcomes
    group by seller_id
)

select
    sellers.seller_id,
    sellers.zip_code_prefix,
    sellers.city,
    sellers.state,
    coalesce(seller_stats.orders_handled, 0)    as orders_handled,
    coalesce(seller_stats.delivered_orders, 0)  as delivered_orders,
    coalesce(seller_stats.late_orders, 0)       as late_orders,
    seller_stats.late_orders / nullif(seller_stats.delivered_orders, 0) as late_rate,
    seller_stats.avg_delivery_days,
    seller_stats.avg_review_score,
    coalesce(seller_stats.reviewed_orders, 0)   as reviewed_orders,
    coalesce(seller_stats.items_revenue, 0)     as items_revenue
from {{ ref('stg_sellers') }} as sellers
left join seller_stats using (seller_id)
