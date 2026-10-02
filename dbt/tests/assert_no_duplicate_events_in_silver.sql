-- Fails if the silver layer still contains duplicate carrier events.
select shipment_id, event_status, event_at, count(*) as n
from {{ ref('stg_carrier_events') }}
group by shipment_id, event_status, event_at
having count(*) > 1
