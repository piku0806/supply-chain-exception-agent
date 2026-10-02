-- Stock position per warehouse and SKU, flagged when at or below the reorder point.
select
    warehouse, sku, cast(on_hand as integer) as on_hand, cast(reorder_point as integer) as reorder_point,
    cast(on_hand as integer) <= cast(reorder_point as integer) as below_reorder_point
from {{ ref('raw_inventory') }}
