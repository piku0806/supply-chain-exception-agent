-- One row per shipment: latest scan, delivery state and lateness against the promise date.
with ranked as (
    select *, row_number() over (partition by shipment_id order by event_at desc) as rn
    from {{ ref('stg_carrier_events') }}
),
latest as (select * from ranked where rn = 1),
delivered as (
    select shipment_id, max(event_at) as delivered_at
    from {{ ref('stg_carrier_events') }} where event_status = 'DELIVERED' group by shipment_id
)
select
    s.shipment_id, s.order_id, s.carrier, s.origin, s.destination, s.shipped_at,
    o.customer_id, o.customer_name, o.customer_tier, o.sku, o.quantity, o.order_value, o.promised_delivery_at,
    l.event_status                                                   as current_status,
    l.event_at                                                       as last_scan_at,
    d.delivered_at,
    {{ dbt.datediff('l.event_at', as_of_ts(), 'hour') }}              as hours_since_last_scan,
    case
        when d.delivered_at is not null
            then {{ dbt.datediff('o.promised_delivery_at', 'd.delivered_at', 'hour') }}
        else {{ dbt.datediff('o.promised_delivery_at', as_of_ts(), 'hour') }}
    end                                                              as hours_past_promise,
    d.delivered_at is not null
        and d.delivered_at <= o.promised_delivery_at                 as delivered_on_time
from {{ ref('stg_shipments') }} s
join {{ ref('stg_orders') }} o on o.order_id = s.order_id
left join latest l on l.shipment_id = s.shipment_id
left join delivered d on d.shipment_id = s.shipment_id
