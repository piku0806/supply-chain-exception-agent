-- Carrier on-time rate on delivered shipments (used by the agent to choose reroutes).
select
    carrier,
    count(*)                                                         as delivered_shipments,
    sum(case when delivered_on_time then 1 else 0 end)               as on_time_shipments,
    round(avg(case when delivered_on_time then 1.0 else 0.0 end), 3) as on_time_rate
from {{ ref('fct_shipment_status') }}
where delivered_at is not null
group by carrier
