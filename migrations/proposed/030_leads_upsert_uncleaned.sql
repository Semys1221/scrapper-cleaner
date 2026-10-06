-- PROPOSED ONLY. DO NOT APPLY from this repository.
--
-- Apply on hercule.dev AFTER db/migrations/026_leads.sql (PR 192).
-- 026 creates public.leads, email_normalized, and lead_status_rank(text).
-- This function is the scraper/cleaner upsert. It does not create the table.
--
-- Conflict target: UNIQUE (email_normalized). email_normalized is generated
-- (lower(btrim(email))) and is not written.
--
-- status_source:
--   scraped inserts use 'list_payload' (this pipeline chose the initial status).
--   ON CONFLICT copies status_source only when status moves up
--   (lead_status_rank(incoming) > lead_status_rank(existing)).
--   The cleaner sets status_source to 'manual' in its own status update.
--
-- source for scraped rows is 'scrape' (free text; hercule imports use
-- 'instantly_import' and 'campaign'). source_name is 'outscraper'.
-- payload JSONB is merged: existing keys stay, empty incoming values do not
-- blank them, new keys are filled.
--
-- An identical re-scrape is a no-op: a column is updated only when the stored
-- value is empty AND the incoming value is non-empty. updated_at stays put
-- and the row is not counted as updated.
--
-- instantly_lead_id collisions (another email already owns that id, or the
-- same batch repeats it) do not abort the batch. The id is omitted and a
-- WARNING is raised. The email row is still inserted or merged.

CREATE OR REPLACE FUNCTION public.leads_note_instantly_id_skip(p_email text, p_lead_id text)
RETURNS text
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE WARNING 'leads_upsert_uncleaned: skipped instantly_lead_id % for % (collision)', p_lead_id, p_email;
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION public.leads_upsert_uncleaned(
  p_rows jsonb,
  p_conflict_target text,
  p_table text
) RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  sql text;
  result jsonb;
BEGIN
  IF p_table IS NULL OR p_table !~ '^[a-z_][a-z0-9_]*$' THEN
    RAISE EXCEPTION 'unsupported leads table: %', p_table;
  END IF;
  IF p_conflict_target IS DISTINCT FROM 'email_normalized' THEN
    RAISE EXCEPTION 'leads conflict target must be email_normalized, got %', p_conflict_target;
  END IF;

  sql := format($q$
    WITH raw AS (
      SELECT *
      FROM jsonb_to_recordset($1) AS x(
        email text,
        first_name text,
        last_name text,
        company text,
        website text,
        phone text,
        job_title text,
        category text,
        niche_slug text,
        source_name text,
        source text,
        source_id text,
        status text,
        status_source text,
        instantly_lead_id text,
        instantly_list_id text,
        list_id text,
        payload jsonb,
        created_at timestamptz,
        updated_at timestamptz
      )
    ),
    incoming AS (
      SELECT DISTINCT ON (lower(btrim(email)))
        lower(btrim(email)) AS email,
        nullif(btrim(first_name), '') AS first_name,
        nullif(btrim(last_name), '') AS last_name,
        nullif(btrim(company), '') AS company,
        nullif(btrim(website), '') AS website,
        nullif(btrim(phone), '') AS phone,
        nullif(btrim(job_title), '') AS job_title,
        nullif(btrim(category), '') AS category,
        nullif(btrim(niche_slug), '') AS niche_slug,
        nullif(btrim(source_name), '') AS source_name,
        coalesce(nullif(btrim(source), ''), 'scrape') AS source,
        nullif(btrim(source_id), '') AS source_id,
        coalesce(nullif(btrim(status), ''), 'uncleaned') AS status,
        coalesce(nullif(btrim(status_source), ''), 'list_payload') AS status_source,
        nullif(btrim(instantly_lead_id), '') AS instantly_lead_id,
        nullif(btrim(instantly_list_id), '') AS instantly_list_id,
        nullif(btrim(list_id), '') AS list_id,
        coalesce(payload, '{}'::jsonb) AS payload,
        coalesce(created_at, now()) AS created_at,
        coalesce(updated_at, now()) AS updated_at
      FROM raw
      WHERE position('@' in lower(btrim(coalesce(email, '')))) > 0
      ORDER BY lower(btrim(email))
    ),
    prepared AS (
      SELECT
        i.*,
        row_number() OVER (
          PARTITION BY i.instantly_lead_id
          ORDER BY i.email
        ) AS instantly_id_rank
      FROM incoming i
    ),
    safe AS (
      SELECT
        p.*,
        CASE
          WHEN p.instantly_lead_id IS NULL THEN NULL
          WHEN p.instantly_id_rank > 1 THEN public.leads_note_instantly_id_skip(p.email, p.instantly_lead_id)
          WHEN EXISTS (
            SELECT 1
            FROM public.%1$I existing
            WHERE existing.instantly_lead_id = p.instantly_lead_id
              AND existing.email_normalized IS DISTINCT FROM p.email
          ) THEN public.leads_note_instantly_id_skip(p.email, p.instantly_lead_id)
          WHEN EXISTS (
            SELECT 1
            FROM public.%1$I existing
            WHERE existing.instantly_lead_id = p.instantly_lead_id
              AND existing.email_normalized = p.email
          ) THEN NULL
          ELSE p.instantly_lead_id
        END AS safe_instantly_lead_id
      FROM prepared p
    ),
    upserted AS (
      INSERT INTO public.%1$I (
        email, first_name, last_name, company, website, phone, job_title,
        category, niche_slug, source_name, source, source_id,
        status, status_source,
        instantly_lead_id, instantly_list_id, list_id,
        payload, created_at, updated_at
      )
      SELECT
        email, first_name, last_name, company, website, phone, job_title,
        category, niche_slug, source_name, source, source_id,
        status, status_source,
        safe_instantly_lead_id, instantly_list_id, list_id,
        payload, created_at, updated_at
      FROM safe
      ON CONFLICT (email_normalized) DO UPDATE SET
        status = CASE
          WHEN public.lead_status_rank(EXCLUDED.status) > public.lead_status_rank(%1$I.status)
          THEN EXCLUDED.status
          ELSE %1$I.status
        END,
        status_source = CASE
          WHEN public.lead_status_rank(EXCLUDED.status) > public.lead_status_rank(%1$I.status)
          THEN EXCLUDED.status_source
          ELSE %1$I.status_source
        END,
        category = CASE
          WHEN %1$I.category IS NULL OR btrim(%1$I.category) = '' THEN EXCLUDED.category
          ELSE %1$I.category
        END,
        first_name = COALESCE(NULLIF(btrim(%1$I.first_name), ''), EXCLUDED.first_name),
        last_name = COALESCE(NULLIF(btrim(%1$I.last_name), ''), EXCLUDED.last_name),
        company = COALESCE(NULLIF(btrim(%1$I.company), ''), EXCLUDED.company),
        website = COALESCE(NULLIF(btrim(%1$I.website), ''), EXCLUDED.website),
        phone = COALESCE(NULLIF(btrim(%1$I.phone), ''), EXCLUDED.phone),
        job_title = COALESCE(NULLIF(btrim(%1$I.job_title), ''), EXCLUDED.job_title),
        niche_slug = COALESCE(NULLIF(btrim(%1$I.niche_slug), ''), EXCLUDED.niche_slug),
        source_name = COALESCE(NULLIF(btrim(%1$I.source_name), ''), EXCLUDED.source_name),
        source_id = COALESCE(NULLIF(btrim(%1$I.source_id), ''), EXCLUDED.source_id),
        payload = COALESCE(%1$I.payload, '{}'::jsonb) || COALESCE((
          SELECT jsonb_object_agg(e.key, e.value)
          FROM jsonb_each(COALESCE(EXCLUDED.payload, '{}'::jsonb)) AS e(key, value)
          WHERE jsonb_typeof(e.value) <> 'null'
            AND e.value <> '""'::jsonb
            AND (
              %1$I.payload -> e.key IS NULL
              OR jsonb_typeof(%1$I.payload -> e.key) = 'null'
              OR %1$I.payload -> e.key = '""'::jsonb
            )
        ), '{}'::jsonb),
        updated_at = now()
      WHERE
        public.lead_status_rank(EXCLUDED.status) > public.lead_status_rank(%1$I.status)
        OR (
          (%1$I.category IS NULL OR btrim(%1$I.category) = '')
          AND EXCLUDED.category IS NOT NULL
        )
        OR (NULLIF(btrim(%1$I.first_name), '') IS NULL AND EXCLUDED.first_name IS NOT NULL)
        OR (NULLIF(btrim(%1$I.last_name), '') IS NULL AND EXCLUDED.last_name IS NOT NULL)
        OR (NULLIF(btrim(%1$I.company), '') IS NULL AND EXCLUDED.company IS NOT NULL)
        OR (NULLIF(btrim(%1$I.website), '') IS NULL AND EXCLUDED.website IS NOT NULL)
        OR (NULLIF(btrim(%1$I.phone), '') IS NULL AND EXCLUDED.phone IS NOT NULL)
        OR (NULLIF(btrim(%1$I.job_title), '') IS NULL AND EXCLUDED.job_title IS NOT NULL)
        OR (NULLIF(btrim(%1$I.niche_slug), '') IS NULL AND EXCLUDED.niche_slug IS NOT NULL)
        OR (NULLIF(btrim(%1$I.source_name), '') IS NULL AND EXCLUDED.source_name IS NOT NULL)
        OR (NULLIF(btrim(%1$I.source_id), '') IS NULL AND EXCLUDED.source_id IS NOT NULL)
        OR EXISTS (
          SELECT 1
          FROM jsonb_each(COALESCE(EXCLUDED.payload, '{}'::jsonb)) AS e(key, value)
          WHERE jsonb_typeof(e.value) <> 'null'
            AND e.value <> '""'::jsonb
            AND (
              %1$I.payload -> e.key IS NULL
              OR jsonb_typeof(%1$I.payload -> e.key) = 'null'
              OR %1$I.payload -> e.key = '""'::jsonb
            )
        )
      RETURNING (xmax = 0) AS inserted
    )
    SELECT jsonb_build_object(
      'inserted', count(*) FILTER (WHERE inserted),
      'updated', count(*) FILTER (WHERE NOT inserted)
    )
    FROM upserted
  $q$, p_table);

  EXECUTE sql INTO result USING p_rows;
  RETURN coalesce(result, jsonb_build_object('inserted', 0, 'updated', 0));
END;
$$;

REVOKE ALL ON FUNCTION public.leads_note_instantly_id_skip(text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.leads_note_instantly_id_skip(text, text) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.leads_note_instantly_id_skip(text, text) TO service_role;

REVOKE ALL ON FUNCTION public.leads_upsert_uncleaned(jsonb, text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.leads_upsert_uncleaned(jsonb, text, text) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.leads_upsert_uncleaned(jsonb, text, text) TO service_role;
