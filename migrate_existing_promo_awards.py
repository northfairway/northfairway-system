"""One-time idempotent Batch 3 migration after database/NFH_PROMO_CODES_BATCH3.sql.

Run from the System folder: python migrate_existing_promo_awards.py
Takes a database backup first; never changes finance amounts or historic requests.
"""
from app import get_db_connection
from advance_promo import ensure_award_codes, valid_coverage_months


def main():
    conn=get_db_connection(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id,user_id,coverage_year FROM nfh_advance_promo_awards ORDER BY user_id,coverage_year')
            awards=cur.fetchall()
            for award in awards:
                cur.execute('SELECT id FROM users WHERE id=%s FOR UPDATE',(award['user_id'],))
                if valid_coverage_months(cur,award['user_id'],award['coverage_year'])!=12:
                    # Invalid/voided awards must not gain new redeemable codes.
                    continue
                ensure_award_codes(cur,award['id'],award['user_id'],award['coverage_year'])
        conn.commit()
        print('Reconciled qualifying existing award records:',len(awards))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__=='__main__': main()
