-- PROPOSED ONLY. DO NOT APPLY to production.
--
-- hercule.dev owns public.leads (PR 192, db/migrations/026_leads.sql), and that
-- migration is still changing. This function is the scraper/cleaner write path
-- once that table exists. It is not registered with Supabase by this change.
--
-- The conflict target is an argument so shared/central_leads.py LEADS_CONFLICT_TARGET
-- is the only place to edit when the final unique key lands. Column names below
-- are the current writer contract and will be aligned with the final 026 file.

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
  IF p_conflict_target IS NULL OR p_conflict_target !~ '^[a-z0-9_,() ]+$' THEN
    RAISE EXCEPTION 'unsupported leads conflict target: %', p_conflict_target;
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
        category text,
        status text,
        source text,
        source_id text,
        instantly_lead_id text,
        instantly_list_id text,
        list_id uuid,
        created_at timestamptz,
        updated_at timestamptz
      )
    ),
    incoming AS (
      SELECT DISTINCT ON (lower(btrim(email)))
        lower(btrim(email)) AS email,
        coalesce(first_name, '') AS first_name,
        coalesce(last_name, '') AS last_name,
        coalesce(company, '') AS company,
        coalesce(website, '') AS website,
        coalesce(phone, '') AS phone,
        category,
        coalesce(nullif(btrim(status), ''), 'uncleaned') AS status,
        coalesce(nullif(btrim(source), ''), 'outscraper') AS source,
        coalesce(source_id, '') AS source_id,
        instantly_lead_id,
        instantly_list_id,
        list_id,
        coalesce(created_at, now()) AS created_at,
        coalesce(updated_at, now()) AS updated_at
      FROM raw
      WHERE position('@' in lower(btrim(coalesce(email, '')))) > 0
      ORDER BY lower(btrim(email))
    ),
    upserted AS (
      INSERT INTO public.%1$I (
        email, first_name, last_name, company, website, phone,
        category, status, source, source_id,
        instantly_lead_id, instantly_list_id, list_id,
        created_at, updated_at
      )
      SELECT
        email, first_name, last_name, company, website, phone,
        category, status, source, source_id,
        instantly_lead_id, instantly_list_id, list_id,
        created_at, updated_at
      FROM incoming
      ON CONFLICT %2$s DO UPDATE SET
        category = CASE
          WHEN %1$I.category IS NULL OR btrim(%1$I.category) = '' THEN EXCLUDED.category
          ELSE %1$I.category
        END,
        first_name = COALESCE(NULLIF(btrim(%1$I.first_name), ''), EXCLUDED.first_name),
        last_name = COALESCE(NULLIF(btrim(%1$I.last_name), ''), EXCLUDED.last_name),
        company = COALESCE(NULLIF(btrim(%1$I.company), ''), EXCLUDED.company),
        website = COALESCE(NULLIF(btrim(%1$I.website), ''), EXCLUDED.website),
        phone = COALESCE(NULLIF(btrim(%1$I.phone), ''), EXCLUDED.phone),
        updated_at = now()
      WHERE
        (%1$I.category IS NULL OR btrim(%1$I.category) = '')
        OR NULLIF(btrim(%1$I.first_name), '') IS NULL
        OR NULLIF(btrim(%1$I.last_name), '') IS NULL
        OR NULLIF(btrim(%1$I.company), '') IS NULL
        OR NULLIF(btrim(%1$I.website), '') IS NULL
        OR NULLIF(btrim(%1$I.phone), '') IS NULL
      RETURNING (xmax = 0) AS inserted
    )
    SELECT jsonb_build_object(
      'inserted', count(*) FILTER (WHERE inserted),
      'updated', count(*) FILTER (WHERE NOT inserted)
    )
    FROM upserted
  $q$, p_table, p_conflict_target);

  EXECUTE sql INTO result USING p_rows;
  RETURN coalesce(result, jsonb_build_object('inserted', 0, 'updated', 0));
END;
$$;

-- Status is absent from DO UPDATE, so an existing status is never downgraded.
-- Install this with the final 026_leads.sql. Do not run it against production now.
