-- Carrier tracking events: statuses upper-cased, duplicate API retries removed.
select distinct
    shipment_id,
    upper(trim(event_status))       as event_status,
    cast(event_at as timestamp)     as event_at,
    location
from {{ ref('raw_carrier_events') }}
