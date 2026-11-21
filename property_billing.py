"""Batch 12 isolated property ledger billing engine.

IMPORTANT: This engine writes only to nfh_property_monthly_dues. The existing
homeowner ledger remains authoritative until an approved reconciliation and a
system-wide cutover (SOA, payments, dashboards, fees, reports) are complete.
Do not run this in parallel with homeowner-based billing in production.
"""
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

MANILA = ZoneInfo('Asia/Manila')


def period_start(value):
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        raise TypeError('Expected date')
    return value.replace(day=1)


def choose_payer(owner_id, agreements, period):
    """Choose the verified agreement effective on the first of the billing month.

    Reject multiple applicable agreements rather than guessing ownership or payer.
    SQL retrieval must be scoped to a single property and verified renter.
    """
    month = period_start(period)
    matching = []
    for a in agreements:
        start = a['effective_from']
        end = a['ends_on']
        if isinstance(start, datetime): start = start.date()
        if isinstance(end, datetime): end = end.date()
        starts_on = a['starts_on']
        if isinstance(starts_on, datetime): starts_on = starts_on.date()
        if a['verification_status'] == 'Verified' and start <= month <= end and starts_on <= month:
            matching.append(a)
    if len(matching) > 1:
        raise ValueError('Conflicting verified rental agreements for billing period')
    if matching:
        agreement = matching[0]
        if int(agreement['homeowner_id']) != int(owner_id):
            raise ValueError('Agreement owner differs from verified property owner')
        if agreement['payer_type'] == 'Renter':
            return ('Renter', int(agreement['renter_id']), int(agreement['id']))
        return ('Homeowner', int(owner_id), int(agreement['id']))
    return ('Homeowner', int(owner_id), None)


def bill_property_month(conn, property_id, month, amount):
    """Atomic idempotent single-property insertion; caller commits after success.

    Concurrency is guarded by UNIQUE(property_id,billing_period). An unverified
    owner or agreement conflict aborts rather than silently charging someone.
    """
    month = period_start(month)
    amount = Decimal(str(amount))
    if amount < 0:
        raise ValueError('Negative monthly dues amount')
    with conn.cursor() as cur:
        cur.execute('SELECT id,billing_start,status FROM nfh_properties WHERE id=%s FOR UPDATE', (property_id,))
        prop = cur.fetchone()
        if not prop or prop['status'] != 'Active':
            raise ValueError('Property not active or not found')
        if period_start(prop['billing_start']) > month:
            raise ValueError('Billing period precedes property start')
        cur.execute('''SELECT homeowner_id FROM nfh_property_owners
                       WHERE property_id=%s AND verified_at IS NOT NULL
                         AND effective_from<=%s AND (effective_to IS NULL OR effective_to>=%s)
                       FOR UPDATE''', (property_id, month, month))
        owners = cur.fetchall()
        if len(owners) != 1:
            raise ValueError('Exactly one verified property owner is required')
        owner = int(owners[0]['homeowner_id'])
        cur.execute('''SELECT a.* FROM nfh_rental_agreements a
                       JOIN nfh_renters r ON r.id=a.renter_id
                       WHERE a.property_id=%s AND a.verification_status='Verified'
                         AND r.verification_status='Verified'
                         AND a.effective_from<=%s AND a.ends_on>=%s AND a.starts_on<=%s
                       FOR UPDATE''', (property_id, month, month, month))
        payer_type, payer_id, agreement_id = choose_payer(owner, cur.fetchall(), month)
        cur.execute('''INSERT INTO nfh_property_monthly_dues
                       (property_id,billing_period,amount_due,homeowner_id,payer_type,responsible_payer_id,rental_agreement_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE id=id''',
                    (property_id,month,amount,owner,payer_type,payer_id,agreement_id))
        return cur.rowcount == 1


def outstanding_balance(conn, property_id):
    """Property balance counts only unvoided receipts, not duplicate owner views."""
    with conn.cursor() as cur:
        cur.execute('''SELECT d.id, d.billing_period, d.amount_due,
                       COALESCE(SUM(CASE WHEN r.voided_at IS NULL THEN r.amount ELSE 0 END),0) paid
                       FROM nfh_property_monthly_dues d
                       LEFT JOIN nfh_property_due_receipts r ON r.obligation_id=d.id
                       WHERE d.property_id=%s GROUP BY d.id,d.billing_period,d.amount_due
                       ORDER BY d.billing_period''', (property_id,))
        rows = cur.fetchall()
    return [{**r, 'balance': max(Decimal('0'),Decimal(str(r['amount_due']))-Decimal(str(r['paid'])))} for r in rows]
