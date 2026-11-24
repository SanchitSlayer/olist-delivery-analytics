with products as (
    select * from {{ source('raw', 'products') }}
),

translation as (
    select * from {{ ref('stg_category_translation') }}
)

select
    products.product_id,
    products.product_category_name                              as category_name_pt,
    -- 610 products have no category in the source
    coalesce(translation.category_name, 'unknown')              as category_name,
    cast(products.product_name_lenght as integer)               as name_length,
    cast(products.product_description_lenght as integer)        as description_length,
    cast(products.product_photos_qty as integer)                as photos_qty,
    cast(products.product_weight_g as double)                   as weight_g,
    cast(products.product_length_cm as double)                  as length_cm,
    cast(products.product_height_cm as double)                  as height_cm,
    cast(products.product_width_cm as double)                   as width_cm
from products
left join translation
    on products.product_category_name = translation.category_name_pt
