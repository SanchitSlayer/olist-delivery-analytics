-- Two categories used in the products table are missing from the source
-- translation file, so they are added here by hand.
select
    product_category_name          as category_name_pt,
    product_category_name_english  as category_name,
    false                          as is_manual_translation
from {{ source('raw', 'category_translation') }}

union all

select category_name_pt, category_name, true
from (
    values
        ('pc_gamer', 'pc_gamer'),
        ('portateis_cozinha_e_preparadores_de_alimentos', 'portable_kitchen_and_food_preparers')
) as missing(category_name_pt, category_name)
