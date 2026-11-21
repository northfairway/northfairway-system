"""Read-only, email-only rendering for NFH-HOA Treasurer financial notices."""
from decimal import Decimal
from datetime import date, datetime
from html import escape


def money(value):
    return f'₱{Decimal(str(value or 0)):,.2f}'


def display_date(value, month_only=False):
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, (date, datetime)):
        return value.strftime('%B %Y' if month_only else '%b %d, %Y')
    return str(value or '—')


def prepare_financial_notice(cur, user_id, name, newly_applied, contact, plan_id=None, reason=None):
    """Use verified allocations and recorded discounts; never change ledger records."""
    cur.execute('''SELECT d.id, d.due_month, d.amount, COALESCE(a.paid,0) AS paid,
         COALESCE(x.discount,0) AS discount
         FROM monthly_dues d
         LEFT JOIN (SELECT a.monthly_due_id, SUM(a.amount) paid FROM monthly_dues_allocations a
             JOIN monthly_dues_payments p ON p.id=a.payment_id
             WHERE p.voided_at IS NULL GROUP BY a.monthly_due_id) a ON a.monthly_due_id=d.id
         LEFT JOIN (SELECT monthly_due_id,SUM(discount_amount) discount FROM nfh_advance_periods
             GROUP BY monthly_due_id) x ON x.monthly_due_id=d.id
         WHERE d.user_id=%s ORDER BY d.due_month,d.id''', (user_id,))
    ledger = cur.fetchall() or []
    assessed = sum((Decimal(str(x['amount'])) for x in ledger), Decimal('0'))
    paid = sum((Decimal(str(x['paid'])) for x in ledger), Decimal('0'))
    discounts = sum((Decimal(str(x['discount'])) for x in ledger), Decimal('0'))
    outstanding = Decimal('0')
    unpaid_months = 0
    now_month = date.today().replace(day=1)
    current_regular = Decimal('0')
    for r in ledger:
        remaining = max(Decimal('0'), Decimal(str(r['amount'])) - Decimal(str(r['paid'])) - Decimal(str(r['discount'])))
        r['remaining_email'] = remaining
        if remaining > 0:
            unpaid_months += 1
        outstanding += remaining
        period = r['due_month']
        if isinstance(period, datetime): period=period.date()
        if isinstance(period, str): period=date.fromisoformat(period[:10])
        if period == now_month and not plan_id:
            current_regular += remaining

    plan = None
    if plan_id is None:
        cur.execute('''SELECT id,status,installment_count,total_amount FROM monthly_dues_payment_plans
                       WHERE user_id=%s AND status IN ('Active','Partially Paid','Overdue')
                       ORDER BY id DESC LIMIT 1''', (user_id,))
    else:
        cur.execute('''SELECT id,status,installment_count,total_amount FROM monthly_dues_payment_plans
                       WHERE id=%s AND user_id=%s''', (plan_id,user_id))
    plan = cur.fetchone()
    installments = []
    if plan:
        # Current regular dues are outside the active plan's coverage.
        cur.execute('SELECT monthly_due_id FROM monthly_dues_plan_coverage WHERE plan_id=%s', (plan['id'],))
        covered_ids={r['monthly_due_id'] for r in (cur.fetchall() or [])}
        current_regular=sum((r['remaining_email'] for r in ledger
                             if (r['due_month'].date() if isinstance(r['due_month'],datetime) else
                                 date.fromisoformat(str(r['due_month'])[:10])) == now_month
                             and r['id'] not in covered_ids), Decimal('0'))
    if plan:
        cur.execute('''SELECT installment_number,due_date,amount,paid_amount FROM monthly_dues_plan_installments
                       WHERE plan_id=%s ORDER BY installment_number''', (plan['id'],))
        installments = cur.fetchall() or []
        # Only explicitly verified installment paid_amount is shown as paid.
        for r in installments:
            r['remaining_email'] = max(Decimal('0'), Decimal(str(r['amount'])) - Decimal(str(r['paid_amount'])))
        next_due = next((r for r in installments if r['remaining_email'] > 0), None)
        suggested = (next_due['remaining_email'] if next_due else Decimal('0')) + current_regular
    else:
        next_due = None
        suggested = current_regular

    pairs = [
        ('Newly applied dues',money(newly_applied)),
        ('Total assessed monthly dues',money(assessed)),
        ('Total verified payments',money(paid)),
    ]
    if discounts:
        pairs.append(('Applied discounts',money(discounts)))
    pairs += [('Remaining outstanding balance',money(outstanding)),
              ('Unpaid billing periods',str(unpaid_months)),
              ('Current regular monthly dues',money(current_regular))]
    if plan:
        pairs += [('Combined suggested payment',money(min(outstanding,suggested))),
                  ('Payment plan status',str(plan['status'])),
                  ('Payment plan duration',f"{plan['installment_count']} months"),
                  ('Monthly installment',money(next_due['amount']) if next_due else money(0)),
                  ('Next installment due',display_date(next_due['due_date']) if next_due else 'All installments paid'),
                  ('Next installment balance',money(next_due['remaining_email']) if next_due else money(0))]

    intro = ('A payment plan has been established for your outstanding association dues.'
             if plan_id else 'Missing monthly association dues have been applied to your account by the HOA Treasurer.')
    details = f'Reason on file: {reason}' if reason else ''
    notice = ('Installments are scheduled payments, not individual billing months. '
              'Only Treasurer-verified amounts are shown as paid.')
    text = ['NFH-HOA · Treasurer’s Office', '',f'Dear {name},','',intro]
    if details: text += ['',details]
    text += ['', 'MONTHLY DUES SUMMARY']
    text += [f'{k}: {v}' for k,v in pairs]
    text += ['','MONTHLY DUES LEDGER','Billing Month | Assessed | Verified Paid | Remaining Balance']
    text += [f"{display_date(r['due_month'],True)} | {money(r['amount'])} | {money(r['paid'])} | {money(r['remaining_email'])}" for r in ledger]
    if installments:
        text += ['', 'PAYMENT PLAN SCHEDULE', notice,
                 'Installment | Amount | Due Date | Verified Paid | Remaining Balance']
        text += [f"{r['installment_number']} | {money(r['amount'])} | {display_date(r['due_date'])} | {money(r['paid_amount'])} | {money(r['remaining_email'])}" for r in installments]
    text += ['','Please settle payments in person with the HOA Treasurer. For questions or discrepancies, contact:',
             f"{contact['name']} | {contact['phone']} | {contact['email']}", '',
             'Respectfully,','North Fairway Homes Homeowners’ Association','Treasurer’s Office']

    esc=lambda x: escape(str(x), quote=True)
    def section(label):
        return f'<h2 style="font-size:17px;color:#2D6A4F;margin:26px 0 10px;font-weight:700;">{esc(label)}</h2>'
    def table(headers, rows, highlight=None):
        th=''.join(f'<th scope="col" style="text-align:{"right" if i else "left"};padding:10px 8px;background:#1B4332;color:#FFFFFF;font-size:12px;line-height:1.4;border:1px solid #E2EBE2;">{esc(h)}</th>' for i,h in enumerate(headers))
        body=''
        for idx,row in enumerate(rows):
            cells=''
            for i,val in enumerate(row):
                emph = highlight is not None and row[0]==highlight
                cells += f'<td style="padding:10px 8px;text-align:{"right" if i else "left"};vertical-align:top;border:1px solid #E2EBE2;background:{"#E2EBE2" if emph else ("#F4F9F4" if idx%2 else "#FFFFFF")};color:#2D312E;font-size:13px;line-height:1.5;overflow-wrap:anywhere;">{esc(val)}</td>'
            body+=f'<tr>{cells}</tr>'
        return f'<table role="table" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:collapse;table-layout:auto;">' + f'<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'
    summary_html=table(['Description','Amount / Details'],pairs,'Remaining outstanding balance')
    ledger_html=table(['Billing Month','Assessed','Verified Paid','Remaining Balance'],
                       [[display_date(r['due_month'],True),money(r['amount']),money(r['paid']),money(r['remaining_email'])] for r in ledger])
    plan_html=''
    if installments:
        plan_html=section('Payment Plan Schedule')+f'<p style="font-size:13px;line-height:1.6;color:#5F6B63;">{esc(notice)}</p>'+table(
            ['Installment','Amount (Payment Plan)','Due Date (Payment Plan)','Verified Paid','Remaining Installment Balance'],
            [[r['installment_number'],money(r['amount']),display_date(r['due_date']),money(r['paid_amount']),money(r['remaining_email'])] for r in installments])
    html_doc=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NFH-HOA Treasurer Notice</title>
    <style>@media(max-width:600px){{.content{{padding:16px!important}} .financial-table{{font-size:12px!important}}}}</style></head>
    <body style="margin:0;padding:0;background:#F4F9F4;color:#2D312E;font-family:Arial,Helvetica,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F4F9F4;"><tr><td align="center" style="padding:18px 8px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;width:100%;background:#FFFFFF;border:1px solid #E2EBE2;">
    <tr><td style="background:#1B4332;color:white;padding:20px 22px;font-size:21px;font-weight:bold;">NFH-HOA · Treasurer’s Office</td></tr>
    <tr><td class="content" style="padding:24px 22px;font-size:15px;line-height:1.65;">
    <p>Dear {esc(name)},</p><p>{esc(intro)}</p>{f'<p>{esc(details)}</p>' if details else ''}
    {section('Monthly Dues Summary')}{summary_html}
    {section('Monthly Dues Ledger')}{ledger_html}{plan_html}
    <p style="margin-top:24px;">Please settle payments in person with the HOA Treasurer. For payment concerns or discrepancies, contact:</p>
    <p style="overflow-wrap:anywhere;">{esc(contact['name'])} · {esc(contact['phone'])} · {esc(contact['email'])}</p>
    <p style="margin-top:24px;">Respectfully,<br><strong>North Fairway Homes Homeowners’ Association</strong><br>Treasurer’s Office</p>
    </td></tr></table></td></tr></table></body></html>'''
    return '\n'.join(text),html_doc
