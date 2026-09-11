WITH ordered_events AS (
    SELECT
        piece_id,
        station_id,
        event_timestamp,
        cycle_time_seconds,
        LAG(station_id) OVER (
            PARTITION BY piece_id
            ORDER BY event_timestamp
        ) AS previous_station_id,
        LAG(event_timestamp) OVER (
            PARTITION BY piece_id
            ORDER BY event_timestamp
        ) AS previous_event_timestamp
    FROM processed_events
),
station_metrics AS (
    SELECT
        station_id,
        COUNT(*) AS event_count,
        AVG(cycle_time_seconds) AS average_cycle_time_seconds,
        STDDEV_POP(cycle_time_seconds) AS cycle_time_stddev_seconds,
        AVG(
            CASE
                WHEN previous_event_timestamp IS NOT NULL
                THEN date_diff('second', previous_event_timestamp, event_timestamp)
            END
        ) AS average_elapsed_seconds_from_previous_station
    FROM ordered_events
    GROUP BY station_id
)
SELECT
    station_id,
    event_count,
    ROUND(average_cycle_time_seconds, 2) AS average_cycle_time_seconds,
    ROUND(cycle_time_stddev_seconds, 2) AS cycle_time_stddev_seconds,
    ROUND(average_elapsed_seconds_from_previous_station, 2)
        AS average_elapsed_seconds_from_previous_station
FROM station_metrics
ORDER BY station_id
