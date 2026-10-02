-- Open exceptions the operations agent must triage. Delivered shipments are history, not exceptions.
with classified as (
    select *,
        case
            when current_status = 'DAMAGED'                                        then 'DAMAGED'
            when current_status = 'ADDRESS_EXCEPTION'                              then 'ADDRESS_ISSUE'
            when hours_since_last_scan > {{ var('stuck_after_hours') }}            then 'STUCK_IN_TRANSIT'
            when hours_past_promise > 0                                            then 'LATE_IN_TRANSIT'
            when hours_past_promise > -24 and hours_since_last_scan > 24           then 'AT_RISK'
        end as exception_type
    from {{ ref('fct_shipment_status') }}
    where delivered_at is null
)
select
    shipment_id, order_id, customer_id, customer_name, customer_tier, carrier, origin, destination, sku,
    quantity, order_value, promised_delivery_at, current_status, last_scan_at, hours_since_last_scan,
    hours_past_promise, exception_type,
    -- Priority: money at risk, weighted up for strategic customers and harder failures
    round(order_value
          * case when customer_tier = 'strategic' then 1.5 else 1.0 end
          * case exception_type when 'DAMAGED' then 1.3 when 'STUCK_IN_TRANSIT' then 1.2 else 1.0 end, 2)
                                                                             as priority_score
from classified
where exception_type is not null
