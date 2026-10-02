-- Typed, standardized customer orders.
select
    order_id,
    customer_id,
    customer_name,
    lower(trim(customer_tier))                      as customer_tier,
    sku,
    cast(quantity as integer)                       as quantity,
    cast(order_value as decimal(12, 2))             as order_value,
    cast(promised_delivery_at as timestamp)         as promised_delivery_at
from {{ ref('raw_orders') }}
