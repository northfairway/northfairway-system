"""Annual advance-payment incentive; only verified, non-voided advance allocations count."""
from datetime import date, datetime
import secrets
from zoneinfo import ZoneInfo

CERTIFICATES = frozenset({'Proof of Residency', 'Certificate of Improvement', 'Certificate of Membership'})


def raffle_tickets(coverage_year, completed_on):
    """January 31 is inclusive; certificates have no such cutoff."""
    return 12 if completed_on <= date(int(coverage_year), 1, 31) else 0


def ensure_award_codes(cur, award_id, homeowner, year):
    """Idempotently issue 4 codes, preserving prior legacy certificate redemptions.

    Called while the homeowner/award is locked in an open database transaction.
    """
    cur.execute('SELECT id FROM nfh_promo_codes WHERE award_id=%s ORDER BY id FOR UPDATE',(award_id,))
    existing=[r['id'] for r in cur.fetchall()]
    if len(existing)>4: raise ValueError('Promo award contains more than four codes')
    for _ in range(4-len(existing)):
        for attempt in range(8):
            code=f"NFH{str(year)[-2:]}-{secrets.token_hex(8).upper()}"
            try:
                cur.execute("""INSERT INTO nfh_promo_codes
                    (award_id,user_id,coverage_year,code,expires_at)
                    VALUES (%s,%s,%s,%s,%s)""",
                    (award_id,homeowner,year,code,datetime(year+1,1,1)))
                break
            except Exception as exc:
                if getattr(exc,'args',[None])[0] != 1062 or attempt==7: raise
    # Legacy requests already consumed credits; retain those associations.
    cur.execute("""SELECT red.request_id,red.created_at FROM nfh_advance_promo_redemptions red
        JOIN requests r ON r.id=red.request_id
        WHERE red.award_id=%s AND r.status NOT IN ('Cancelled','Rejected')
        ORDER BY red.id""",(award_id,))
    prior=cur.fetchall()
    if len(prior)>4: raise ValueError('Legacy promo award exceeds four active redemptions')
    for r in prior:
        cur.execute('SELECT id FROM nfh_promo_codes WHERE redeemed_request_id=%s',(r['request_id'],))
        if cur.fetchone():continue
        cur.execute("""SELECT id FROM nfh_promo_codes
            WHERE award_id=%s AND redeemed_request_id IS NULL AND revoked_at IS NULL
            ORDER BY id LIMIT 1 FOR UPDATE""",(award_id,))
        available=cur.fetchone()
        if not available:raise ValueError('No code slot available for historical redemption')
        cur.execute('UPDATE nfh_promo_codes SET redeemed_request_id=%s,redeemed_at=%s WHERE id=%s',
                    (r['request_id'],r['created_at'],available['id']))


def valid_coverage_months(cur, homeowner, year):
    """Revalidate full Jan–Dec advance coverage, excluding voided payments."""
    cur.execute("""SELECT COUNT(DISTINCT MONTH(ap.due_month)) n
      FROM nfh_advance_periods ap
      JOIN nfh_advance_transactions t ON t.id=ap.transaction_id
      JOIN monthly_dues_payments p ON p.id=t.payment_id
      WHERE t.user_id=%s AND ap.due_month >= %s AND ap.due_month < %s
      AND p.voided_at IS NULL AND ap.gross_amount=ap.cash_amount+ap.discount_amount""",
      (homeowner,date(year,1,1),date(year+1,1,1)))
    return int(cur.fetchone()['n'])


def award_annual_promo(cur, homeowner, year, actor):
    """Run inside the existing locked homeowner advance-payment transaction.

    Requires every Jan-Dec period to be covered by a verified, non-voided
    advance payment, including any authorized discount allocated to its month.
    """
    cur.execute("""SELECT ap.due_month, p.received_at, ap.gross_amount, ap.cash_amount,
                          ap.discount_amount, p.voided_at
        FROM nfh_advance_periods ap
        JOIN nfh_advance_transactions t ON t.id=ap.transaction_id
        JOIN monthly_dues_payments p ON p.id=t.payment_id
        WHERE t.user_id=%s AND ap.due_month >= %s AND ap.due_month < %s
        ORDER BY ap.due_month""", (homeowner, date(year,1,1), date(year+1,1,1)))
    rows=cur.fetchall()
    eligible={}
    for r in rows:
        if r['voided_at'] is not None:continue
        m=r['due_month']
        if isinstance(m,str):m=date.fromisoformat(m[:10])
        if m.year!=year:continue
        from decimal import Decimal
        if Decimal(str(r['cash_amount']))+Decimal(str(r['discount_amount'])) != Decimal(str(r['gross_amount'])):continue
        eligible[m.month]=r
    if len(eligible)!=12:return None
    completed=max(r['received_at'].date() if hasattr(r['received_at'],'date') else date.fromisoformat(str(r['received_at'])[:10]) for r in eligible.values())
    tickets=raffle_tickets(year,completed)
    cur.execute("""INSERT INTO nfh_advance_promo_awards
        (user_id,coverage_year,qualifying_paid_at,raffle_tickets,certificate_credits,awarded_by)
        VALUES (%s,%s,%s,%s,4,%s)
        ON DUPLICATE KEY UPDATE id=id""", (homeowner,year,completed,tickets,actor))
    cur.execute('SELECT id,raffle_tickets,certificate_credits FROM nfh_advance_promo_awards WHERE user_id=%s AND coverage_year=%s FOR UPDATE', (homeowner,year))
    award = cur.fetchone()
    # Existing award/year uniqueness and locked homeowner prevent duplicate issuance.
    ensure_award_codes(cur, award['id'], homeowner, year)
    return {'raffle_tickets':award['raffle_tickets'], 'certificate_credits':award['certificate_credits']}


def promo_status(row, now=None):
    now = now or datetime.now(ZoneInfo("Asia/Manila")).replace(tzinfo=None)
    if row.get('redeemed_request_id') and row.get('request_status') not in ('Cancelled','Rejected'):
        return 'Used'
    if row.get('revoked_at') is not None or row.get('valid_months',12)<12: return 'Inactive'
    expiry = row['expires_at']
    if isinstance(expiry,str): expiry=datetime.fromisoformat(expiry)
    if now >= expiry: return 'Expired'
    return 'Active'


def list_codes(cur, homeowner=None, status=None, search=None, year=None, limit=2000):
    sql = """SELECT pc.*, r.status request_status,
       CONCAT(u.first_name,' ',u.last_name) homeowner_name,
       a.qualifying_paid_at payment_date,
       (SELECT COUNT(DISTINCT MONTH(ap2.due_month))
          FROM nfh_advance_periods ap2
          JOIN nfh_advance_transactions t2 ON t2.id=ap2.transaction_id
          JOIN monthly_dues_payments p2 ON p2.id=t2.payment_id
          WHERE t2.user_id=pc.user_id
          AND ap2.due_month >= MAKEDATE(pc.coverage_year,1)
          AND ap2.due_month < MAKEDATE(pc.coverage_year+1,1)
          AND p2.voided_at IS NULL
          AND ap2.gross_amount=ap2.cash_amount+ap2.discount_amount) valid_months,
       (SELECT MIN(t.id) FROM nfh_advance_transactions t
          JOIN nfh_advance_periods ap ON ap.transaction_id=t.id
          WHERE t.user_id=pc.user_id AND YEAR(ap.due_month)=pc.coverage_year) payment_id
       FROM nfh_promo_codes pc
       JOIN users u ON u.id=pc.user_id
       JOIN nfh_advance_promo_awards a ON a.id=pc.award_id
       LEFT JOIN requests r ON r.id=pc.redeemed_request_id WHERE 1=1"""
    params=[]
    if homeowner is not None:sql+=' AND pc.user_id=%s';params.append(homeowner)
    if year is not None:sql+=' AND pc.coverage_year=%s';params.append(year)
    if search:
        sql+=" AND (pc.code LIKE %s OR CONCAT(u.first_name,' ',u.last_name) LIKE %s OR CAST(pc.user_id AS CHAR) LIKE %s)"
        params.extend(['%'+search+'%']*3)
    sql+=' ORDER BY pc.coverage_year DESC,pc.created_at DESC,pc.id DESC'
    if limit is not None:
        sql+=' LIMIT %s';params.append(int(limit))
    cur.execute(sql,tuple(params))
    rows=[]
    for row in cur.fetchall():
        item=dict(row);item['status']=promo_status(item)
        if status and item['status']!=status:continue
        for k in ('expires_at','created_at','redeemed_at','payment_date'):
            if item.get(k) is not None:item[k]=str(item[k])
        rows.append(item)
    return rows


def redeem_code(cur, homeowner, request_id, request_type, code, original_fee):
    if request_type not in CERTIFICATES or float(original_fee)<=0:raise ValueError('Promo code is not eligible for this request fee')
    cur.execute("""SELECT pc.*,r.status request_status FROM nfh_promo_codes pc
        LEFT JOIN requests r ON r.id=pc.redeemed_request_id
        WHERE pc.code=%s AND pc.user_id=%s FOR UPDATE""",(code,homeowner))
    item=cur.fetchone()
    if not item or promo_status(item)!='Active' or valid_coverage_months(cur,homeowner,item['coverage_year'])!=12:
        raise ValueError('Promo code is unavailable, expired, used, or not assigned to this homeowner')
    # Locking and unique request ownership prevent concurrent double redemption.
    cur.execute("""UPDATE nfh_promo_codes SET redeemed_request_id=%s,redeemed_at=NOW(),original_request_fee=%s
        WHERE id=%s AND revoked_at IS NULL""",(request_id,original_fee,item['id']))
    cur.execute('INSERT INTO nfh_advance_promo_redemptions(award_id,request_id) VALUES (%s,%s)',
                (item['award_id'],request_id))
    return True


def promo_summary(cur, homeowner):
    cur.execute("""SELECT a.coverage_year,a.qualifying_paid_at,a.raffle_tickets,a.certificate_credits,
       (SELECT COUNT(*) FROM nfh_advance_promo_redemptions red JOIN requests r ON r.id=red.request_id
        WHERE red.award_id=a.id AND r.status NOT IN ('Cancelled','Rejected')) used
       FROM nfh_advance_promo_awards a WHERE a.user_id=%s ORDER BY a.coverage_year DESC""",(homeowner,))
    return [dict(coverage_year=r['coverage_year'],payment_date=str(r['qualifying_paid_at']),
        deadline=f"{r['coverage_year']}-01-31",raffle_tickets=int(r['raffle_tickets']),
        certificate_credits=int(r['certificate_credits']),used=int(r['used']),
        remaining=max(0,int(r['certificate_credits'])-int(r['used'])),
        status='Qualified' if r['raffle_tickets'] else 'Qualified for certificates only') for r in cur.fetchall()]
