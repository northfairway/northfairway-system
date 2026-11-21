"""Shared, read-only financial ledger projections.

The ledger deliberately does not infer verified cash from spreadsheet metadata.
Queries fail closed if migration tables are missing; no fabricated zero balances.
"""
from datetime import date, datetime
from decimal import Decimal

ZERO = Decimal('0')
def dec(x):
    return Decimal(str(x or 0))
def iso(x):
    return x.isoformat()[:10] if hasattr(x, 'isoformat') else (str(x)[:10] if x else '')
VALID_KINDS = {'all': None, 'monthly_dues': 'Monthly Dues', 'request_fee': 'Request Fee', 'others': 'Others'}
VALID_STATUSES = {'all', 'paid', 'unpaid', 'partially_paid'}

def snapshot(cur, homeowner_id, start=None, end=None, transaction_type='all', payment_status='all'):
    if transaction_type not in VALID_KINDS: raise ValueError('Invalid transaction type filter')
    if payment_status not in VALID_STATUSES: raise ValueError('Invalid payment status filter')
    cur.execute("SELECT id,homeowner_public_id,CONCAT(first_name,' ',last_name) AS name,block,lot FROM users WHERE id=%s AND role='Homeowner'",(homeowner_id,))
    user=cur.fetchone()
    if not user: raise ValueError('Homeowner not found')
    cur.execute("""SELECT md.id, md.due_month AS covered_month,
        COALESCE((SELECT e.transaction_date FROM nfh_historical_import_entries e
                  WHERE e.homeowner_id=md.user_id AND e.transaction_type='Monthly Dues'
                  AND YEAR(e.transaction_date)=YEAR(md.due_month)
                  AND MONTH(e.transaction_date)=MONTH(md.due_month)
                  ORDER BY e.id LIMIT 1), DATE(md.created_at)) AS occurred, md.amount AS assessed,
        COALESCE(SUM(CASE WHEN p.voided_at IS NULL THEN a.amount ELSE 0 END),0) AS paid
        FROM monthly_dues md LEFT JOIN monthly_dues_allocations a ON a.monthly_due_id=md.id
        LEFT JOIN monthly_dues_payments p ON p.id=a.payment_id
        WHERE md.user_id=%s GROUP BY md.id,md.due_month,md.created_at,md.amount ORDER BY md.due_month""",(homeowner_id,))
    dues=cur.fetchall()
    cur.execute("""SELECT a.monthly_due_id AS id, SUM(a.amount) paid FROM nfh_historical_cash_allocations a
        JOIN nfh_historical_cash_receipts h ON h.id=a.receipt_id
        WHERE h.user_id=%s AND a.category='Monthly Dues' GROUP BY a.monthly_due_id""",(homeowner_id,))
    hist_dues_paid={r['id']:dec(r['paid']) for r in cur.fetchall()}
    for d in dues:d['paid']=dec(d['paid'])+hist_dues_paid.get(d['id'],ZERO)
    cur.execute("""SELECT r.id, r.request_type AS type,r.date_submitted AS occurred,r.fee AS assessed,
        COALESCE(SUM(pt.amount),0) AS paid FROM requests r
        LEFT JOIN payment_transactions pt ON pt.request_id=r.id AND pt.user_id=r.user_id
        WHERE r.user_id=%s AND r.fee>0 AND r.status IN ('Approved','Awaiting Payment Verification','Ready for Payment & Release','Paid - Awaiting Release','Ready for Release','Issued / Completed','Paid and Approved')
        GROUP BY r.id,r.request_type,r.date_submitted,r.fee ORDER BY r.date_submitted""",(homeowner_id,))
    requests=cur.fetchall()
    cur.execute("""SELECT h.id,h.request_type AS type,h.request_date AS occurred,h.amount AS assessed,
        COALESCE(SUM(hr.amount),0) AS paid,h.external_ref
        FROM nfh_historical_request_fees h
        LEFT JOIN nfh_historical_fee_receipts hr ON hr.fee_id=h.id
        WHERE h.user_id=%s
        GROUP BY h.id,h.request_type,h.request_date,h.amount,h.external_ref ORDER BY h.request_date""",(homeowner_id,))
    historical=cur.fetchall()
    cur.execute("""SELECT a.historical_fee_id AS id,SUM(a.amount) paid FROM nfh_historical_cash_allocations a
        JOIN nfh_historical_cash_receipts h ON h.id=a.receipt_id
        WHERE h.user_id=%s AND a.category='Request' GROUP BY a.historical_fee_id""",(homeowner_id,))
    hist_fee_paid={r['id']:dec(r['paid']) for r in cur.fetchall()}
    for h in historical:h['paid']=dec(h['paid'])+hist_fee_paid.get(h['id'],ZERO)
    cur.execute("""SELECT id,transaction_type AS kind,description,transaction_date AS occurred,amount AS assessed
        FROM nfh_historical_import_entries WHERE homeowner_id=%s AND transaction_type='Others'""",(homeowner_id,))
    other_charges=cur.fetchall()
    records=[]
    for r in dues:
        records.append(dict(id='D'+str(r['id']),kind='Monthly Dues',description='Monthly Dues — '+iso(r['covered_month'])[:7],date=iso(r['occurred']),assessed=dec(r['assessed']),paid=dec(r['paid']),source='Monthly dues'))
    for r in requests:
        records.append(dict(id='R'+str(r['id']),kind='Request Fee',description=r['type'],date=iso(r['occurred']),assessed=dec(r['assessed']),paid=dec(r['paid']),source='Approved/system request'))
    for r in historical:
        records.append(dict(id='H'+str(r['id']),kind='Request Fee',description=r['type'],date=iso(r['occurred']),assessed=dec(r['assessed']),paid=dec(r['paid']),source='Historical import',reference=r['external_ref']))
    for r in other_charges:
        records.append(dict(id='O'+str(r['id']),kind='Others',description=r['description'],date=iso(r['occurred']),assessed=dec(r['assessed']),paid=ZERO,source='Historical import'))
    cur.execute("""SELECT a.import_entry_id AS id,SUM(a.amount) paid FROM nfh_historical_cash_allocations a
        JOIN nfh_historical_cash_receipts h ON h.id=a.receipt_id
        WHERE h.user_id=%s AND a.category='Others' GROUP BY a.import_entry_id""",(homeowner_id,))
    other_paid={r['id']:dec(r['paid']) for r in cur.fetchall()}
    for r in records:
        if r['kind']=='Others':r['paid']=other_paid.get(int(r['id'][1:]),ZERO)
    # Actual receipt metadata, attached to each obligation through verified allocation keys.
    # A payment date must never be inferred from its assessment date.
    receipt_queries = [
        ("""SELECT a.monthly_due_id AS entry_id, p.received_at AS payment_date,
                    NULL AS or_number FROM monthly_dues_allocations a
             JOIN monthly_dues_payments p ON p.id=a.payment_id
             WHERE p.user_id=%s AND p.voided_at IS NULL""", 'D'),
        ("""SELECT pt.request_id AS entry_id, pt.payment_date,
                    pt.official_receipt_no AS or_number FROM payment_transactions pt
             WHERE pt.user_id=%s""", 'R'),
        ("""SELECT hr.fee_id AS entry_id, hr.received_on AS payment_date,
                    hr.receipt_no AS or_number FROM nfh_historical_fee_receipts hr
             WHERE hr.user_id=%s""", 'H'),
        ("""SELECT a.monthly_due_id AS entry_id, h.received_on AS payment_date,
                    h.receipt_no AS or_number FROM nfh_historical_cash_allocations a
             JOIN nfh_historical_cash_receipts h ON h.id=a.receipt_id
             WHERE h.user_id=%s AND a.category='Monthly Dues' AND a.monthly_due_id IS NOT NULL""", 'D'),
        ("""SELECT a.historical_fee_id AS entry_id, h.received_on AS payment_date,
                    h.receipt_no AS or_number FROM nfh_historical_cash_allocations a
             JOIN nfh_historical_cash_receipts h ON h.id=a.receipt_id
             WHERE h.user_id=%s AND a.category='Request' AND a.historical_fee_id IS NOT NULL""", 'H'),
        ("""SELECT a.import_entry_id AS entry_id, h.received_on AS payment_date,
                    h.receipt_no AS or_number FROM nfh_historical_cash_allocations a
             JOIN nfh_historical_cash_receipts h ON h.id=a.receipt_id
             WHERE h.user_id=%s AND a.category='Others'""", 'O'),
    ]
    receipt_info={}
    for sql,prefix in receipt_queries:
        cur.execute(sql,(homeowner_id,))
        for item in cur.fetchall():
            key=prefix+str(item['entry_id'])
            meta=receipt_info.setdefault(key,{'dates':set(),'ors':set()})
            if item.get('payment_date'):meta['dates'].add(iso(item['payment_date']))
            if item.get('or_number'):meta['ors'].add(str(item['or_number']))
    for r in records:
        info=receipt_info.get(r['id'],{})
        dates=sorted(info.get('dates',()))
        r['payment_date']=dates[-1] if dates else None
        r['or_number']=', '.join(sorted(info.get('ors',()))) or None
    records.sort(key=lambda r:(r['date'],r['id']))
    start=iso(start) if start else None;end=iso(end) if end else None
    if start and end and start>end: raise ValueError('Start date must precede end date')
    # Record-level paid allocations are known, but dates of dues cash payments must
    # be used for period-sensitive cash basis accounting. Do not fabricate period totals.
    cur.execute("""SELECT received_at AS occurred,amount, id FROM monthly_dues_payments
        WHERE user_id=%s AND voided_at IS NULL ORDER BY received_at""",(homeowner_id,))
    dues_payments=cur.fetchall()
    cur.execute("""SELECT payment_date AS occurred,amount, id FROM payment_transactions
        WHERE user_id=%s ORDER BY payment_date""",(homeowner_id,))
    request_payments=cur.fetchall()
    cur.execute("""SELECT hr.id,hr.received_on AS occurred,hr.amount
        FROM nfh_historical_fee_receipts hr
        WHERE hr.user_id=%s ORDER BY hr.received_on""", (homeowner_id,))
    historical_payments=cur.fetchall()
    cur.execute('SELECT id,received_on AS occurred FROM nfh_historical_cash_receipts WHERE user_id=%s',(homeowner_id,))
    cash_receipts=cur.fetchall()
    cur.execute('SELECT receipt_id,category,amount FROM nfh_historical_cash_allocations WHERE receipt_id IN (SELECT id FROM nfh_historical_cash_receipts WHERE user_id=%s)',(homeowner_id,))
    allocations=cur.fetchall()
    alloc_map={}
    for a in allocations:alloc_map.setdefault(a['receipt_id'],[]).append(a)
    imported_payments=[dict(date=iso(x['occurred']),amount=sum((dec(a['amount']) for a in alloc_map.get(x['id'],[]) if a['category']==category),ZERO),id='HSOA-'+str(x['id'])+'-'+category,kind={'Request':'Request Fee','Monthly Dues':'Monthly Dues','Others':'Others'}[category]) for x in cash_receipts for category in ('Request','Monthly Dues','Others') if any(a['category']==category for a in alloc_map.get(x['id'],[]))]
    payments=sorted(imported_payments+[dict(date=iso(x['occurred']),amount=dec(x['amount']),id=str(x['id']),kind=kind) for kind,rows in [('Monthly Dues',dues_payments),('Request Fee',request_payments),('Historical Request Fee',historical_payments)] for x in rows],key=lambda x:x['date'])
    opening=sum((r['assessed'] for r in records if start and r['date']<start and (VALID_KINDS[transaction_type] is None or r['kind']==VALID_KINDS[transaction_type])),ZERO)-sum((x['amount'] for x in payments if start and x['date']<start and (VALID_KINDS[transaction_type] is None or x['kind']==VALID_KINDS[transaction_type] or (transaction_type=='request_fee' and x['kind']=='Historical Request Fee'))),ZERO)
    def record_status(r):
        remaining = max(ZERO, r['assessed'] - r['paid'])
        return 'Paid' if remaining == 0 else ('Partially Paid' if r['paid'] > 0 else 'Unpaid')
    selected=[r for r in records if (not start or r['date']>=start) and (not end or r['date']<=end)
              and (VALID_KINDS[transaction_type] is None or r['kind']==VALID_KINDS[transaction_type])
              and (payment_status=='all' or record_status(r).lower().replace(' ','_')==payment_status)]
    cash=[x for x in payments if (not start or x['date']>=start) and (not end or x['date']<=end)]
    # Category-specific payment history must not include unrelated cash entries.
    # The historical receipt amount is split by its verified allocation categories.
    if transaction_type != 'all':
        selected_kind=VALID_KINDS[transaction_type]
        cash=[x for x in cash if x['kind']==selected_kind or (selected_kind=='Request Fee' and x['kind']=='Historical Request Fee')]
    # Payment status refers to obligations, not payment receipts. Hide unrelated
    # payment history rather than pretending that it can be matched row-by-row.
    if payment_status != 'all': cash=[]
    charges=sum((x['assessed'] for x in selected),ZERO)
    paid=sum((x['amount'] for x in cash),ZERO)
    closing=opening+charges-paid
    def encode(row):
        r=dict(row)
        for key in ('assessed','paid','amount'):
            if key in r:r[key]=str(r[key])
        if 'assessed' in row:
            remaining=max(ZERO,row['assessed']-row['paid'])
            r['remaining']=str(remaining)
            r['status']='Paid' if remaining==0 else ('Partially Paid' if row['paid']>0 else 'Unpaid')
        return r
    filtered_assessed=sum((r['assessed'] for r in selected), ZERO)
    filtered_paid=sum((min(r['assessed'],r['paid']) for r in selected), ZERO)
    filtered_remaining=sum((max(ZERO,r['assessed']-r['paid']) for r in selected), ZERO)
    return dict(transaction_type=transaction_type,payment_status=payment_status,
                filtered_assessed=str(filtered_assessed),filtered_paid=str(filtered_paid),
                filtered_remaining=str(filtered_remaining),homeowner=user,opening_balance=str(opening),charges=str(charges),payments_during_period=str(paid),closing_balance=str(closing),monthly_dues=[encode(x) for x in selected if x['kind']=='Monthly Dues'],request_fees=[encode(x) for x in selected if x['kind']=='Request Fee'],other_charges=[encode(x) for x in selected if x['kind']=='Others'],payment_history=[encode(x) for x in cash],start=start,end=end,as_of=iso(date.today()),note='Ledger dates are original obligation/transaction dates. Filtered applied payments represent allocations to selected obligations; cash payment history uses receipt dates. Unverified imported payments are excluded.')
