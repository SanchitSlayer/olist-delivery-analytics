-- Monthly KPIs by purchase month. Delivery and late metrics belong to the
-- month the order was placed, not the month it arrived. Revenue excludes
-- canceled and unavailable orders.
select
    purchase_month                                              as month,
    count(*)                                                    as orders,
    sum(order_value) filter (where order_status not in ('canceled', 'unavailable')) as revenue,
    count(*) filter (where is_delivered)                        as delivered_orders,
    avg(delivery_days)                                          as avg_delivery_days,
    count(*) filter (where is_late)                             as late_orders,
    count(*) filter (where is_late) / nullif(count(*) filter (where is_delivered), 0) as late_rate,
    avg(review_score)                                           as avg_review_score
from {{ ref('fct_orders') }}
group by purchase_month
order by purchase_month
