"""Transactional monthly billing and verified advance-payment allocations for NFH-HOA."""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta

MANILA = ZoneInfo('Asia/Manila')
CENT = Decimal('0.01')

def money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)

def first_of_month(d):
    return d.replace(day=1)

def payment_state(month, amount, applied, today):
    remaining = money(amount) - money(applied)
    if remaining <= 0:
        return 'Paid in Advance' if month > first_of_month(today) else 'Paid'
    if applied > 0:
        return 'Partially Paid'
    if month > first_of_month(today):
        return 'Upcoming'
    return 'Overdue' if today.day > 5 or month < first_of_month(today) else 'Unpaid'

def generate_bills(conn, through=None):
    """Idempotent catch-up; earliest bill starts at homeowner activation/creation month."""
    today = datetime.now(MANILA).date()
    if through is not None and through > today:
        raise ValueError('Refusing to generate future monthly dues during regular billing')
    through = first_of_month(through or today)
    inserted = 0
    with conn.cursor() as cur:
        cur.execute("SELECT amount FROM fees WHERE item_name='Monthly Dues' AND status='Active' LIMIT 1")
        fee = cur.fetchone()
        if not fee:
            raise RuntimeError('Active Monthly Dues fee configuration missing')
        amount = money(fee['amount'])
        cur.execute("SELECT id, created_at FROM users WHERE role='Homeowner' AND status='Active'")
        users = cur.fetchall()
        for user in users:
            start = first_of_month(user['created_at'].date() if hasattr(user['created_at'], 'date') else user['created_at'])
            month = start
            while month <= through:
                cur.execute("INSERT IGNORE INTO monthly_dues (user_id,due_month,amount,status) VALUES (%s,%s,%s,'Unpaid')", (user['id'], month, amount))
                inserted += cur.rowcount
                month += relativedelta(months=1)
    conn.commit()
    return inserted

def allocate_payment(conn, homeowner_id, amount, actor, *, preview=False, received_at=None):
    """Lock homeowner, allocate oldest-first and then future months; leave remainder as credit.

    This routine requires the additive migration; caller owns rollback on failure.
    """
    amount = money(amount)
    if amount <= 0:
        raise ValueError('Payment must be positive')
    today = (received_at or __import__('datetime').datetime.now(MANILA)).date()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE id=%s AND role='Homeowner' FOR UPDATE", (homeowner_id,))
        if not cur.fetchone():
            raise ValueError('Homeowner not found')
        cur.execute("SELECT amount FROM fees WHERE item_name='Monthly Dues' AND status='Active' LIMIT 1")
        fee = cur.fetchone()
        if not fee:
            raise ValueError('Monthly Dues fee not configured')
        rate = money(fee['amount'])
        if rate <= 0:
            raise ValueError('Invalid monthly dues rate')
        cur.execute("SELECT id,due_month,amount FROM monthly_dues WHERE user_id=%s ORDER BY due_month FOR UPDATE", (homeowner_id,))
        bills = cur.fetchall()
        cur.execute("SELECT a.monthly_due_id,COALESCE(SUM(a.amount),0) paid FROM monthly_dues_allocations a JOIN monthly_dues_payments p ON p.id=a.payment_id WHERE p.user_id=%s AND p.voided_at IS NULL GROUP BY a.monthly_due_id", (homeowner_id,))
        paid = {r['monthly_due_id']:money(r['paid']) for r in cur.fetchall()}
        remaining = amount
        allocations = []
        for bill in bills:
            outstanding = max(Decimal('0'), money(bill['amount'])-paid.get(bill['id'], Decimal('0')))
            used = min(outstanding, remaining)
            if used:
                allocations.append((bill['id'], bill['due_month'], used))
                remaining -= used
            if remaining == 0:
                break
        future_month = first_of_month(today) + relativedelta(months=1)
        known_months = {b['due_month'] for b in bills}
        while remaining > 0 and len(allocations) < 240:
            if future_month not in known_months:
                used = min(rate, remaining)
                allocations.append((None, future_month, used))
                remaining -= used
            future_month += relativedelta(months=1)
        if preview:
            conn.rollback()
            return {'allocations': [(str(m),str(v)) for _,m,v in allocations], 'unapplied_credit':str(remaining)}
        cur.execute("INSERT INTO monthly_dues_payments (user_id,amount,received_at,verified_by,unapplied_amount) VALUES (%s,%s,%s,%s,%s)", (homeowner_id,amount,received_at or __import__('datetime').datetime.now(MANILA).replace(tzinfo=None),actor,remaining))
        payment_id = cur.lastrowid
        for bill_id,month,used in allocations:
            if bill_id is None:
                cur.execute("INSERT INTO monthly_dues (user_id,due_month,amount,status) VALUES (%s,%s,%s,'Unpaid') ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)", (homeowner_id,month,rate))
                bill_id = cur.lastrowid
            cur.execute("INSERT INTO monthly_dues_allocations (payment_id,monthly_due_id,amount) VALUES (%s,%s,%s)", (payment_id,bill_id,used))
            cur.execute("SELECT amount FROM monthly_dues WHERE id=%s", (bill_id,))
            due = money(cur.fetchone()['amount'])
            cur.execute("SELECT COALESCE(SUM(a.amount),0) paid FROM monthly_dues_allocations a JOIN monthly_dues_payments p ON p.id=a.payment_id WHERE a.monthly_due_id=%s AND p.voided_at IS NULL", (bill_id,))
            paid_total = money(cur.fetchone()['paid'])
            if paid_total >= due:
                cur.execute("UPDATE monthly_dues SET status='Paid',settled_at=COALESCE(settled_at,NOW()),settled_by=%s WHERE id=%s", (actor,bill_id))
        cur.execute("INSERT INTO audit_logs (username,role,action,item,prev_val,new_val) VALUES (%s,'Treasurer','Advance Monthly Dues Payment',%s,%s,%s)", (actor,str(homeowner_id),'',f'Payment {payment_id}: {amount}'))
    conn.commit()
    return {'payment_id':payment_id,'allocations':[(str(m),str(v)) for _,m,v in allocations], 'unapplied_credit':str(remaining)}
