-- Payments rolled up to one row per order. The main payment type is the
-- method that covered the largest share of the order.
with payments as (
    select * from {{ ref('stg_order_payments') }}
),

type_ranked as (
    select
        order_id,
        payment_type,
        row_number() over (
            partition by order_id
            order by sum(payment_value) desc, min(payment_sequence)
        ) as type_rank
    from payments
    group by order_id, payment_type
),

totals as (
    select
        order_id,
        count(*)            as payment_count,
        sum(payment_value)  as payment_total,
        max(installments)   as max_installments
    from payments
    group by order_id
)

select
    totals.*,
    type_ranked.payment_type as main_payment_type
from totals
left join type_ranked
    on totals.order_id = type_ranked.order_id and type_ranked.type_rank = 1
