-- PREVIEW ONLY: run after nfh_property_owners are verified.
-- Monthly dues with zero or multiple verified property matches MUST NOT auto-migrate.
SELECT d.id AS legacy_due_id,d.user_id,d.due_month,d.amount,d.status,
       COUNT(DISTINCT o.property_id) AS verified_property_matches
FROM monthly_dues d
LEFT JOIN nfh_property_owners o ON o.homeowner_id=d.user_id
  AND o.verified_at IS NOT NULL
  AND o.effective_from<=d.due_month
  AND (o.effective_to IS NULL OR o.effective_to>=d.due_month)
GROUP BY d.id,d.user_id,d.due_month,d.amount,d.status
HAVING COUNT(DISTINCT o.property_id)<>1
ORDER BY d.user_id,d.due_month;

-- Identify duplicate ownership/location registrations for manual investigation.
SELECT subdivision,block,lot,COUNT(*) AS property_records
FROM nfh_properties GROUP BY subdivision,block,lot HAVING COUNT(*)>1;

-- IMPORTANT: Do not run old and new monthly-billing jobs in parallel.
-- Legacy charges, allocations, SOA imports, payment plans, and advances must
-- be reconciled into an approved property mapping before activating new billing.
