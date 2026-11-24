-- Kept as a typed copy of the source. It has many duplicate rows per zip
-- prefix and is not used downstream: the analysis works at state level.
select
    geolocation_zip_code_prefix          as zip_code_prefix,
    cast(geolocation_lat as double)      as latitude,
    cast(geolocation_lng as double)      as longitude,
    geolocation_city                     as city,
    geolocation_state                    as state
from {{ source('raw', 'geolocation') }}
