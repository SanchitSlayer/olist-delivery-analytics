-- Some orders have more than one review. We keep the most recently answered
-- one per order and record how many there were, so the dedup is visible.
with reviews as (
    select
        review_id,
        order_id,
        cast(review_score as integer)               as review_score,
        review_comment_title                        as comment_title,
        review_comment_message                      as comment_message,
        cast(review_creation_date as timestamp)     as review_sent_at,
        cast(review_answer_timestamp as timestamp)  as review_answered_at
    from {{ source('raw', 'order_reviews') }}
),

ranked as (
    select
        *,
        count(*) over (partition by order_id) as reviews_for_order,
        row_number() over (
            partition by order_id
            order by review_answered_at desc, review_sent_at desc, review_id
        ) as review_rank
    from reviews
)

select
    order_id,
    review_id,
    review_score,
    comment_title,
    comment_message,
    comment_message is not null as has_comment,
    review_sent_at,
    review_answered_at,
    reviews_for_order
from ranked
where review_rank = 1
