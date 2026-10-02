-- Shipments with carrier names normalized (carrier APIs send "GLOBALFREIGHT", "Global Freight", ...).
with src as (
    select *, upper(replace(carrier_name, ' ', '')) as carrier_key
    from {{ ref('raw_shipments') }}
)
select
    shipment_id,
    order_id,
    case carrier_key
        when 'GLOBALFREIGHT'    then 'GlobalFreight'
        when 'SWIFTHAUL'        then 'SwiftHaul'
        when 'BLUELINEEXPRESS'  then 'BlueLine Express'
        when 'BLUELINE'         then 'BlueLine Express'
        when 'PRAIRIELOGISTICS' then 'Prairie Logistics'
        else carrier_name
    end                                     as carrier,
    origin,
    destination,
    cast(shipped_at as timestamp)           as shipped_at,
    tracking_number
from src
