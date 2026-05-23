-- One-shot cleanup: remove gov.uk noise URLs that were ingested by the
-- HMRC/TPR/ICO atom watchers before the URL blocklist was added.
--
-- USAGE on the VM:
--   1) PREVIEW (no changes) — see what would be deleted:
--      docker exec askai-postgres psql -U askai -d askai -c "$(sed -n '/-- PREVIEW START/,/-- PREVIEW END/p' /path/to/cleanup_govuk_noise.sql)"
--   2) RUN the actual cleanup:
--      docker exec -i askai-postgres psql -U askai -d askai < scripts/cleanup_govuk_noise.sql

\set ON_ERROR_STOP on

BEGIN;

-- -- PREVIEW START
SELECT
  d.doc_type,
  count(*) AS to_delete,
  min(d.created_at) AS earliest,
  max(d.created_at) AS latest
FROM documents d
WHERE d.source_uri ~* '/(government/(statistics|news|speeches|people|ministers|case-studies|world-location-news|collections|topical-events|foi-releases|correspondence))(/|$)'
GROUP BY d.doc_type
ORDER BY to_delete DESC;
-- -- PREVIEW END

-- Capture the IDs we're about to nuke so we can cascade through dependents
-- without relying on FK ON DELETE CASCADE being set on every child table.
CREATE TEMP TABLE _docs_to_delete AS
SELECT d.id, d.source_uri
FROM documents d
WHERE d.source_uri ~* '/(government/(statistics|news|speeches|people|ministers|case-studies|world-location-news|collections|topical-events|foi-releases|correspondence))(/|$)';

SELECT format('Will delete %s document(s)', count(*)) FROM _docs_to_delete;

-- Detach watcher events so we don't lose the event row itself (it's
-- useful provenance) — just clear the linkage and mark un-ingested.
UPDATE watcher_events
SET document_id = NULL, ingested = false,
    notification_error = 'cleaned: gov.uk noise URL pattern'
WHERE document_id IN (SELECT id FROM _docs_to_delete);

-- Delete dependent rows. Order matters: chunks → ingestion_jobs → documents.
DELETE FROM chunks WHERE document_id IN (SELECT id FROM _docs_to_delete);
UPDATE ingestion_jobs SET document_id = NULL
  WHERE document_id IN (SELECT id FROM _docs_to_delete);
DELETE FROM documents WHERE id IN (SELECT id FROM _docs_to_delete);

SELECT format('Deleted %s document row(s)', count(*)) FROM _docs_to_delete;

DROP TABLE _docs_to_delete;

-- Comment the next line out and re-run with COMMIT to actually apply.
-- COMMIT;
ROLLBACK;
