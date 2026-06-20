-- ============================================================
-- Fix tweet_digest display path
-- 1. Ensure tweet_digest has display metric config.
-- 2. Backfill missing items_content rows for existing tweet_digest raw_items.
-- ============================================================

BEGIN;

INSERT INTO display_metrics_configs (content_type, metrics)
VALUES (
    'tweet_digest',
    '[{"label":"🐦 推文","key":"tweet_count","format":"number"},{"label":"❤️ 点赞","key":"likes","format":"number"},{"label":"🔁 转发","key":"retweets","format":"number"}]'::jsonb
)
ON CONFLICT (content_type) DO UPDATE
SET metrics = EXCLUDED.metrics,
    updated_at = now();

INSERT INTO items_content (item_id, raw_body)
SELECT
    r.id,
    COALESCE(
        NULLIF(
            string_agg(
                concat_ws(
                    ': ',
                    '@' || NULLIF(t.elem->>'author', ''),
                    NULLIF(t.elem->>'text', '')
                ),
                E'\n\n'
                ORDER BY t.ord
            ),
            ''
        ),
        r.title
    ) AS raw_body
FROM raw_items r
LEFT JOIN LATERAL jsonb_array_elements(
    CASE
        WHEN jsonb_typeof(r.extra->'tweets') = 'array' THEN r.extra->'tweets'
        ELSE '[]'::jsonb
    END
) WITH ORDINALITY AS t(elem, ord) ON true
WHERE r.content_type = 'tweet_digest'
GROUP BY r.id, r.title
ON CONFLICT (item_id) DO UPDATE
SET raw_body = EXCLUDED.raw_body,
    updated_at = now()
WHERE items_content.raw_body IS NULL;

COMMIT;
