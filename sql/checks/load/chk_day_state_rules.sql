-- The state and the band of a series-day are what the rule of D04 and D13 gives for its stored flag and discount: the same rule as
-- promolift.days.day_state and day_band, written in SQL. The thresholds come from [days]; :band_edges is the JSON list of the edges between bands
-- (the interior ones) between :band_first_edge (exclusive) and :band_last_edge (inclusive): a discount outside them has no band, as in days.band_of;
-- :edge_tolerance is days.EDGE_TOLERANCE (the float32 noise of the real discounts, D13's note of 2026-11-17).
SELECT series_key, date_key, day_state, expected_state, band, expected_band
FROM (
    SELECT series_key, date_key, day_state, band, expected_state,
           CASE WHEN expected_state IN ('promo', 'unflagged_cut') AND discount > :band_first_edge AND discount <= :band_last_edge
                THEN (SELECT COUNT(*) FROM json_each(:band_edges) WHERE value <= discount + :edge_tolerance)
           END AS expected_band
    FROM (
        SELECT series_key, date_key, day_state, band, discount,
               CASE WHEN discount <= :anomalous_max_discount OR discount > :anomalous_min_discount THEN 'anomalous'
                    WHEN activity_flag = 1 THEN 'promo'
                    WHEN discount + :edge_tolerance >= :regular_min_discount THEN 'regular'
                    ELSE 'unflagged_cut'
               END AS expected_state
        FROM series_days
    )
)
WHERE day_state IS NOT expected_state OR band IS NOT expected_band;
