-- Item-level data rolled up to one row per order. When an order has items
-- from several sellers or categories, the "main" one is the one with the
-- highest item value in that order.
with items as (
    select
        items.*,
        products.category_name,
        products.weight_g,
        products.length_cm * products.height_cm * products.width_cm as volume_cm3
    from {{ ref('stg_order_items') }} as items
    left join {{ ref('stg_products') }} as products using (product_id)
),

seller_ranked as (
    select
        order_id,
        seller_id,
        row_number() over (
            partition by order_id
            order by sum(price) desc, count(*) desc, seller_id
        ) as seller_rank
    from items
    group by order_id, seller_id
),

category_ranked as (
    select
        order_id,
        category_name,
        row_number() over (
            partition by order_id
            order by sum(price) desc, count(*) desc, category_name
        ) as category_rank
    from items
    group by order_id, category_name
),

totals as (
    select
        order_id,
        count(*)                   as item_count,
        count(distinct seller_id)  as seller_count,
        sum(price)                 as items_value,
        sum(freight_value)         as freight_value,
        sum(weight_g)              as total_weight_g,
        sum(volume_cm3)            as total_volume_cm3
    from items
    group by order_id
)

select
    totals.*,
    seller_ranked.seller_id         as main_seller_id,
    category_ranked.category_name   as main_category
from totals
left join seller_ranked
    on totals.order_id = seller_ranked.order_id and seller_ranked.seller_rank = 1
left join category_ranked
    on totals.order_id = category_ranked.order_id and category_ranked.category_rank = 1
