"""Run by cron/scheduler: python delinquency_job.py. Dry-run by default."""
import argparse
from app import app,get_db_connection

def run(commit=False):
    with app.app_context():
        db=get_db_connection(autocommit=False)
        try:
            with db.cursor() as c:
                c.execute("SELECT setting_value FROM hoa_settings WHERE setting_key='delinquency_unpaid_months'")
                threshold=int((c.fetchone() or {}).get('setting_value',5))
                c.execute("""SELECT u.id,COUNT(d.id) unpaid_months,COALESCE(SUM(d.amount),0) balance FROM users u LEFT JOIN monthly_dues d ON d.user_id=u.id AND d.status='Unpaid' WHERE u.role='Homeowner' GROUP BY u.id""")
                records=c.fetchall()
                if commit:
                    for r in records:
                        classification='For Review' if r['unpaid_months']>=threshold else 'Clear'
                        c.execute("""INSERT INTO delinquency_reviews(user_id,unpaid_months,outstanding_balance,classification) VALUES(%s,%s,%s,%s) ON DUPLICATE KEY UPDATE unpaid_months=VALUES(unpaid_months),outstanding_balance=VALUES(outstanding_balance),classification=VALUES(classification),reviewed_at=NOW()""",(r['id'],r['unpaid_months'],r['balance'],classification))
                        if classification=='For Review':
                            from datetime import date
                            period=date.today().strftime('%Y-%m')
                            c.execute("INSERT IGNORE INTO delinquency_notices(user_id,period_key,channel,status) VALUES(%s,%s,'in-app','pending')",(r['id'],period))
                            if c.rowcount:
                                c.execute("INSERT INTO alerts(user_id,text) VALUES(%s,%s)",(r['id'],f"Monthly dues notice: {r['unpaid_months']} unpaid months. Contact the Treasurer to verify your balance and settle payments in person."))
                                c.execute("UPDATE delinquency_notices SET status='sent',attempts=1 WHERE user_id=%s AND period_key=%s AND channel='in-app'",(r['id'],period))
                    db.commit()
                return {'evaluated':len(records),'flagged':sum(r['unpaid_months']>=threshold for r in records),'committed':commit}
        except Exception:
            db.rollback();raise
        finally:db.close()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--commit',action='store_true');args=parser.parse_args();print(run(args.commit))
