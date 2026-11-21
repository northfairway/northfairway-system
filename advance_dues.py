"""Treasurer-only face-to-face advance dues service. Caller owns transaction."""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from whole_peso import whole, authorized_discount
from dateutil.relativedelta import relativedelta

CENT=Decimal('0.01')
def cents(v):
    d=Decimal(str(v)).quantize(CENT, rounding=ROUND_HALF_UP)
    if not d.is_finite(): raise ValueError('Invalid amount')
    return d

def month_first(value):
    d=date.fromisoformat(value+'-01')
    return d

def periods(start,count,today):
    if not isinstance(count,int) or not 1<=count<=60: raise ValueError('Select 1 to 60 months')
    first=month_first(start)
    if first<=today.replace(day=1) and not (count == 12 and first == date(today.year,1,1)):
        raise ValueError('Only future billing months are eligible, except a current-year January–December promo payment')
    return [first+relativedelta(months=i) for i in range(count)]

def calculate_discount(cur, policy_id, count, gross, today):
    if not policy_id: return Decimal('0.00'), None
    cur.execute('''SELECT * FROM nfh_advance_discount_policies WHERE id=%s AND active=1
       AND effective_date<=%s AND (expiration_date IS NULL OR expiration_date>=%s)
       AND min_months<=%s AND (max_months IS NULL OR max_months>=%s)''',
       (policy_id,today,today,count,count))
    policy=cur.fetchone()
    if not policy: raise ValueError('Discount policy is unavailable or not approved for this coverage')
    if not policy['resolution_reference'] or not policy['authorized_by']:
        raise ValueError('Discount requires approved HOA resolution and authorized approver')
    value=cents(policy['discount_value'])
    if policy['discount_type']=='Percentage':
        if value<0 or value>100:raise ValueError('Invalid percentage discount')
        discount=Decimal(authorized_discount(whole(gross), 'Percentage', value))
    elif policy['discount_type']=='Fixed': discount=Decimal(authorized_discount(whole(gross),'Fixed',value))
    else: raise ValueError('Unsupported discount type')
    if discount<0 or discount>=gross:raise ValueError('Discount must be less than gross dues')
    return discount,policy

def resolve_manual_policy(cur, count, gross, discount, today):
    """Choose a uniquely authorized policy for manually entered discount; reject ambiguity."""
    if discount == 0:
        return None
    cur.execute("""SELECT id FROM nfh_advance_discount_policies
       WHERE active=1 AND effective_date<=%s AND (expiration_date IS NULL OR expiration_date>=%s)
       AND min_months<=%s AND (max_months IS NULL OR max_months>=%s)
       AND resolution_reference IS NOT NULL AND resolution_reference<>''
       AND authorized_by IS NOT NULL AND authorized_by<>''""",(today,today,count,count))
    allowed=[]
    for policy in cur.fetchall():
        limit,_=calculate_discount(cur,policy['id'],count,gross,today)
        if discount<=limit:allowed.append(policy['id'])
    if len(allowed)!=1:
        raise ValueError('Manual discount must be covered by exactly one authorized HOA policy')
    return allowed[0]

def pay_advance(conn, homeowner, first_month, count, policy_id, cash, method, reference, payment_day, remarks, actor, request_key, manual_discount=0):
    today=date.today()
    months=periods(first_month,int(count),today)
    if payment_day>today:raise ValueError('Payment date cannot be in the future')
    if method not in ('Cash','Bank Transfer (verified in person)','Check (cleared)'):
        raise ValueError('Invalid offline payment method')
    if not request_key or len(request_key)>80:raise ValueError('Request identifier is required')
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE id=%s AND role='Homeowner' AND status='Active' FOR UPDATE",(homeowner,))
        if not cur.fetchone(): raise ValueError('Active homeowner not found')
        cur.execute('SELECT id FROM nfh_advance_transactions WHERE request_key=%s',(request_key,))
        prior=cur.fetchone()
        if prior: return {'id':prior['id'],'duplicate':True}
        cur.execute("SELECT amount FROM fees WHERE item_name='Monthly Dues' AND status='Active' LIMIT 1")
        fee=cur.fetchone()
        if not fee:raise ValueError('Active monthly dues fee not configured')
        rate=Decimal(whole(fee['amount'],positive=True))
        gross=rate*len(months)
        # The annual advance-payment promo offers non-monetary benefits only.
        # Reject forged legacy discount submissions before any payment is recorded.
        if Decimal(whole(manual_discount)) != 0 or policy_id not in (None, '', 0):
            raise ValueError('Monetary discounts are not allowed for advance monthly dues payments')
        discount=Decimal('0.00')
        policy=None
        cash=Decimal(whole(cash,positive=True))
        if cash!=gross: raise ValueError('Cash received must equal full advance dues amount')
        # Require zero historic monthly dues outstanding, to avoid bypassing normal dues allocation rules.
        cur.execute('''SELECT d.id,d.amount,COALESCE(SUM(CASE WHEN p.voided_at IS NULL THEN a.amount ELSE 0 END),0) paid
           FROM monthly_dues d LEFT JOIN monthly_dues_allocations a ON a.monthly_due_id=d.id
           LEFT JOIN monthly_dues_payments p ON p.id=a.payment_id
           WHERE d.user_id=%s AND d.due_month<=%s AND (d.due_month<%s OR d.due_month>%s) GROUP BY d.id,d.amount''',(homeowner,today,months[0],months[-1]))
        for r in cur.fetchall():
            cur.execute('SELECT COALESCE(SUM(discount_amount),0) x FROM nfh_advance_periods WHERE monthly_due_id=%s',(r['id'],))
            d=cents(cur.fetchone()['x'])
            if cents(r['amount'])>cents(r['paid'])+d:raise ValueError('Settle outstanding dues before recording future advance payments')
        entries=[]
        for month in months:
            cur.execute('SELECT id,amount,status FROM monthly_dues WHERE user_id=%s AND due_month=%s FOR UPDATE',(homeowner,month))
            r=cur.fetchone()
            if r:
                cur.execute('SELECT COALESCE(SUM(discount_amount),0) discount FROM nfh_advance_periods WHERE monthly_due_id=%s',(r['id'],))
                d=cents(cur.fetchone()['discount'])
                cur.execute('''SELECT COALESCE(SUM(a.amount),0) paid FROM monthly_dues_allocations a
                   JOIN monthly_dues_payments p ON p.id=a.payment_id
                   WHERE a.monthly_due_id=%s AND p.voided_at IS NULL''',(r['id'],))
                paid=cents(cur.fetchone()['paid'])
                if paid+d>0 or r['status']=='Paid':raise ValueError('Selected month already has a payment or advance coverage')
                if cents(r['amount'])!=rate:raise ValueError('Existing billing amount differs from current configured rate')
            entries.append((month,r['id'] if r else None))
        cur.execute('''INSERT INTO monthly_dues_payments(user_id,amount,received_at,verified_by,unapplied_amount)
           VALUES (%s,%s,%s,%s,0)''',(homeowner,cash,datetime.combine(payment_day,datetime.min.time()),actor))
        payment_id=cur.lastrowid
        cur.execute('''INSERT INTO nfh_advance_transactions(user_id,payment_id,request_key,gross_amount,cash_received,discount_amount,
           policy_id,discount_reference,payment_method,payment_reference,remarks,processed_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
           (homeowner,payment_id,request_key,gross,cash,discount,policy['id'] if policy else None,
            policy['resolution_reference'] if policy else None,method,reference or None,remarks or None,actor))
        tx=cur.lastrowid
        # Allocate cash and discount separately, with remainder distributed in the final month.
        cash_left=cash;discount_left=discount
        for idx,(month,bill_id) in enumerate(entries):
            if bill_id is None:
                cur.execute("INSERT INTO monthly_dues(user_id,due_month,amount,status) VALUES(%s,%s,%s,'Unpaid')",(homeowner,month,rate))
                bill_id=cur.lastrowid
            d=min(discount_left, (discount/len(entries)).quantize(CENT,rounding=ROUND_HALF_UP)) if idx<len(entries)-1 else discount_left
            discount_left-=d
            paid=rate-d
            if idx==len(entries)-1: paid=cash_left
            cash_left-=paid
            if paid<0 or cash_left<0:raise ValueError('Invalid cash allocation')
            if paid:cur.execute('INSERT INTO monthly_dues_allocations(payment_id,monthly_due_id,amount) VALUES(%s,%s,%s)',(payment_id,bill_id,paid))
            cur.execute('''INSERT INTO nfh_advance_periods(transaction_id,monthly_due_id,due_month,gross_amount,cash_amount,discount_amount)
               VALUES(%s,%s,%s,%s,%s,%s)''',(tx,bill_id,month,rate,paid,d))
            cur.execute("UPDATE monthly_dues SET status='Paid',settled_at=NOW(),settled_by=%s WHERE id=%s",(actor,bill_id))
        if cash_left or discount_left:raise ValueError('Advance allocations failed to reconcile')
        # Annual promo is idempotent and awarded only after all 12 months are covered.
        from advance_promo import award_annual_promo
        covered_years={m.year for m in months}
        promo_awards={year:award_annual_promo(cur,homeowner,year,actor) for year in covered_years}
        cur.execute("INSERT INTO audit_logs(username,role,action,item,prev_val,new_val) VALUES (%s,'Treasurer','Advance Dues Payment',%s,%s,%s)",
           (actor,str(homeowner),'',f'Transaction {tx}: gross={gross}, cash={cash}, discount={discount}, months={first_month}/{count}'))
    return {'id':tx,'duplicate':False,'gross':str(gross),'cash_received':str(cash),'discount':str(discount),'covered':[m.isoformat() for m in months], 'promo':{str(y):dict(a) for y,a in promo_awards.items() if a}}
