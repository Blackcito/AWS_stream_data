SELECT
    station_id,
    quality_status,
    COUNT(*) AS event_count,
    COUNT(DISTINCT piece_id) AS piece_count
FROM processed_events
GROUP BY station_id, quality_status
ORDER BY station_id, quality_status