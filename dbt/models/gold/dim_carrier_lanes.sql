select origin, destination, carrier, cast(cost_per_mile_usd as double) as cost_per_mile_usd,
       cast(expedite_days as integer) as expedite_days
from {{ ref('raw_carrier_lanes') }}
