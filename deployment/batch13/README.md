# Batch 13: PostgreSQL and Vercel migration preparation

**STATUS: AUDIT / EXPORT FOUNDATION ONLY. NOT POSTGRESQL-COMPATIBLE, NOT VERCEL-READY.**

## Tools added

- `../../batch13_audit.py`: scans Python and SQL for database-specific constructs and serverless blockers. `python batch13_audit.py --out deployment/batch13/BATCH13_SOURCE_INVENTORY.json`
- `export_mysql_snapshot.py`: makes a **read-only transactionally consistent** JSONL snapshot of InnoDB tables and records row counts and SHA256 hashes. Requires existing PyMySQL and a MySQL user with read privileges. This does not create or modify PostgreSQL records. Backup with `mysqldump --single-transaction --routines --triggers --events` separately; verify restoration in staging.
- `verify_snapshot.py`: verifies exported file row counts and SHA256 hashes before and after transfer. `python deployment/batch13/verify_snapshot.py /secure/private/snapshot`
- `BATCH13_SOURCE_INVENTORY.json`: machine-readable audit with relevant file/line references, not an exhaustive semantic SQL correctness audit.

## Export command

```
MYSQL_HOST=127.0.0.1 MYSQL_PORT=3306 MYSQL_USER=readonly \
MYSQL_PASSWORD='...' MYSQL_DATABASE=northfairwayportal \
python deployment/batch13/export_mysql_snapshot.py --out /private/nfh_snapshot
python deployment/batch13/verify_snapshot.py /private/nfh_snapshot
```

**Confidentiality:** The snapshot includes personal, authentication and financial records. Never put it in a repository, public folder, Vercel assets, email attachment, or an AI prompt. Protect with filesystem permissions and encryption; delete it when migration verification is completed. The exporter intentionally does not print data values.

**Snapshot scope:** InnoDB consistent reads; concurrent schema changes must be blocked and nontransactional tables need special handling. JSONL is a transport/audit format, not a complete PostgreSQL migration. Sequences, constraints, indexes, triggers and application queries must be separately validated. BYTE columns are represented as `{ "_hex": "..." }` and require decoding on import.

## PostgreSQL / Vercel steps still required

1. Reconcile and approve final Batch 12 property ownership and billing cutover. Do not run both monthly dues schedulers.
2. Convert every MySQL DDL definition and apply versioned PostgreSQL migrations on a clean staging database. Verify primary keys, constraints, indexes, enum semantics and monetary types.
3. Adapt **every** Python database client, including `app.py`, CLI jobs, module imports and MySQL-specific queries. Implement parameterization, safe connection lifecycle, transaction isolation and rollback under psycopg. Verify every endpoint against PostgreSQL.
4. Implement durable OTP/password resets, file storage and import staging, protected scheduled jobs, email retry/outbox and secure session configuration.
5. Reconcile row counts, source identifiers, receipts, outstanding balances, installments, promo codes and SOA outputs between MySQL and PostgreSQL. Quarantine mismatches for manual review.
6. Only then add a production Vercel entrypoint and deployment configuration and test with a real project, hosted PostgreSQL, object storage and scheduled jobs. Test function time limits, payload limits, concurrent requests and database pooling.
7. Run authenticated cross-role tests, concurrent payment tests, backups/restoration drills, security tests and sign off before cutover.

## Rollback

Maintain the verified source MySQL backup, the original Batch 12 ZIP and a documented write-freeze / rollback window. A production cutover should switch traffic only after successful reconciliation and end-to-end tests. If validation fails, stop PostgreSQL writes, restore application routing to the untouched MySQL system, and reconcile any accepted writes before re-opening transactions. Never independently accept writes into both sources.
