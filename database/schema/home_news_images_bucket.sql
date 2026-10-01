-- ============================================================================
-- Supabase Storage bucket for proxied article images.
-- The Home News writer downloads each article's og:image and re-uploads it here
-- so the Streamlit app serves images from your own origin (no hotlink failures).
-- Run this once in the Supabase SQL editor.
-- ============================================================================

-- 1) Create a PUBLIC bucket (public means objects are readable without auth).
INSERT INTO storage.buckets (id, name, public)
VALUES ('home-news-images', 'home-news-images', true)
ON CONFLICT (id) DO UPDATE SET public = true;

-- 2) Policies on storage.objects so the anon key (used by the pipeline) can
--    read/write objects in this bucket. Read is also implicitly available via
--    the bucket's `public=true` flag, but an explicit SELECT policy makes the
--    intent obvious.

DROP POLICY IF EXISTS "home_news_images_read"  ON storage.objects;
DROP POLICY IF EXISTS "home_news_images_write" ON storage.objects;
DROP POLICY IF EXISTS "home_news_images_update" ON storage.objects;

CREATE POLICY "home_news_images_read"
    ON storage.objects FOR SELECT
    TO anon, authenticated
    USING (bucket_id = 'home-news-images');

CREATE POLICY "home_news_images_write"
    ON storage.objects FOR INSERT
    TO anon, authenticated
    WITH CHECK (bucket_id = 'home-news-images');

CREATE POLICY "home_news_images_update"
    ON storage.objects FOR UPDATE
    TO anon, authenticated
    USING (bucket_id = 'home-news-images')
    WITH CHECK (bucket_id = 'home-news-images');
