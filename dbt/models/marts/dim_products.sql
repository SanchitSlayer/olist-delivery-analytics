with products as (
    select * from {{ ref('stg_products') }}
),

sales as (
    select
        product_id,
        count(*)                  as items_sold,
        count(distinct order_id)  as orders_with_product,
        sum(price)                as items_revenue
    from {{ ref('stg_order_items') }}
    group by product_id
)

select
    products.product_id,
    products.category_name,
    products.category_name_pt,
    products.weight_g,
    products.length_cm,
    products.height_cm,
    products.width_cm,
    products.length_cm * products.height_cm * products.width_cm as volume_cm3,
    products.photos_qty,
    coalesce(sales.items_sold, 0)           as items_sold,
    coalesce(sales.orders_with_product, 0)  as orders_with_product,
    coalesce(sales.items_revenue, 0)        as items_revenue
from products
left join sales using (product_id)
