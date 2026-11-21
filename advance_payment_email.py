"""Read-only advance payment email. Uses transaction allocations, never edits payments."""
from decimal import Decimal
from datetime import date, datetime
from html import escape
from financial_notice_email import money, display_date


def prepare_advance_email(cur, transaction_id):
    cur.execute("""SELECT t.id,t.user_id,t.gross_amount,t.cash_received,t.payment_method,
           t.payment_reference,t.processed_by,p.received_at,p.voided_at,
           CONCAT(u.first_name,' ',u.last_name) homeowner
        FROM nfh_advance_transactions t
        JOIN monthly_dues_payments p ON p.id=t.payment_id
        JOIN users u ON u.id=t.user_id
        WHERE t.id=%s""", (transaction_id,))
    tx=cur.fetchone()
    if not tx or tx['voided_at'] is not None:
        raise ValueError('No verified active advance payment for this transaction')
    cur.execute("""SELECT ap.due_month,d.amount assessed,
           COALESCE(SUM(CASE WHEN p.voided_at IS NULL THEN al.amount ELSE 0 END),0) verified_paid,
           ap.cash_amount current_allocation
        FROM nfh_advance_periods ap
        JOIN nfh_advance_transactions t ON t.id=ap.transaction_id
        JOIN monthly_dues d ON d.id=ap.monthly_due_id
        LEFT JOIN monthly_dues_allocations al ON al.monthly_due_id=d.id
        LEFT JOIN monthly_dues_payments p ON p.id=al.payment_id
        WHERE ap.transaction_id=%s
        GROUP BY ap.id,ap.due_month,d.amount,ap.cash_amount
        ORDER BY ap.due_month,ap.id""", (transaction_id,))
    ledger=cur.fetchall() or []
    if not ledger:raise ValueError('Advance payment has no monthly allocation ledger')
    amount=lambda n: Decimal(str(n or 0))
    total_assessed=sum((amount(r['assessed']) for r in ledger), Decimal(0))
    total_verified=sum((amount(r['verified_paid']) for r in ledger), Decimal(0))
    current_allocated=sum((amount(r['current_allocation']) for r in ledger), Decimal(0))
    if current_allocated != amount(tx['cash_received']):
        raise ValueError('Transaction allocations do not reconcile with cash received')
    months=[date.fromisoformat(str(r['due_month'])[:10]) for r in ledger]
    coverage=(display_date(months[0],True) if len(months)==1 else
              f'{display_date(months[0],True)} – {display_date(months[-1],True)}')
    # Qualification reads the actual recorded annual award, not assumptions based on amount.
    years=sorted({m.year for m in months})
    promos=[]
    for year in years:
        cur.execute("""SELECT a.coverage_year,a.raffle_tickets,a.certificate_credits,
                (SELECT COUNT(*) FROM nfh_advance_promo_redemptions red
                 JOIN requests req ON req.id=red.request_id
                 WHERE red.award_id=a.id AND req.status NOT IN ('Cancelled','Rejected')) used,
                dis.tickets_distributed,dis.confirmed_at
            FROM nfh_advance_promo_awards a
            LEFT JOIN nfh_advance_promo_distributions dis ON dis.award_id=a.id
            WHERE a.user_id=%s AND a.coverage_year=%s""", (tx['user_id'],year))
        award=cur.fetchone()
        if award:promos.append(award)
    cur.execute("""SELECT pc.code,pc.coverage_year,pc.expires_at
        FROM nfh_promo_codes pc JOIN nfh_advance_promo_awards a ON a.id=pc.award_id
        WHERE a.user_id=%s AND a.coverage_year IN ("""+','.join(['%s']*len(years))+""")
        ORDER BY pc.coverage_year,pc.id""",(tx['user_id'],*years))
    issued_codes=cur.fetchall()
    name=tx['homeowner']
    pairs=[('Homeowner Name',name),('Homeowner ID',str(tx['user_id'])),('Transaction Reference',tx['payment_reference'] or f'Advance #{tx["id"]}'),
           ('Date of Payment',display_date(tx['received_at'])),('Advance Payment Coverage',coverage),
           ('Number of Months Covered',str(len(months))),
           ('Total Advance Payment',money(tx['gross_amount'])),('Verified Payment',money(tx['cash_received'])),
           ('Current Transaction Allocated',money(current_allocated)),
           ('Remaining Balance for Covered Months',money(sum((max(Decimal(0),amount(r['assessed'])-amount(r['verified_paid'])) for r in ledger), Decimal(0)))),
           ('Payment Status','Verified'),('Payment Method',tx['payment_method']),('Processed By',tx['processed_by'])]
    if len({amount(r['assessed']) for r in ledger})==1:
        pairs.insert(5,('Monthly Association Dues',money(ledger[0]['assessed'])))
    grid=[[display_date(r['due_month'],True),money(r['assessed']),money(r['current_allocation']),
           money(max(Decimal(0),amount(r['assessed'])-amount(r['verified_paid'])))] for r in ledger]
    grid.append(['Total',money(total_assessed),money(current_allocated),money(sum((max(Decimal(0),amount(r['assessed'])-amount(r['verified_paid'])) for r in ledger), Decimal(0)))])
    promo_lines=[];promo_rows=[]
    for a in promos:
        year=int(a['coverage_year']); tickets=int(a['raffle_tickets']); credits=int(a['certificate_credits'])
        remaining=max(0,credits-int(a['used']))
        issued=int(a['tickets_distributed'] or 0)
        status=(f'{issued} raffle tickets physically distributed and confirmed by the Treasurer' if issued
                else 'Eligible raffle tickets pending physical distribution at the HOA office' if tickets
                else 'Not eligible for raffle tickets; January 31 deadline passed')
        promo_rows += [('Coverage year',str(year)),('Raffle tickets',str(tickets)),
                       ('Free certificate requests granted',str(credits)),('Remaining certificate credits',str(remaining)),
                       ('Raffle distribution',status),('Raffle deadline',f'January 31, {year}')]
        promo_lines += [f'{year}: {tickets} raffle tickets; {credits} free certificate requests; {remaining} remaining. {status}.']
    if issued_codes:
        promo_lines += ['Your promotional codes (single use; expires at 12:00 AM Asia/Manila):']
        promo_lines += [f"{x['code']} | {x['coverage_year']} | {str(x['expires_at'])[:10]}" for x in issued_codes]
        promo_rows += [('Promo codes issued',str(len(issued_codes)))]
    if not promo_lines:
        promo_lines=['This transaction does not meet the full-year Advance Payment Promo requirements.']
    footer=('For concerns, payment discrepancies, or questions regarding your advance payment and promotional benefits, '
            'please coordinate directly with the HOA Treasurer. Thank you for your continued cooperation and support '
            'of North Fairway Homes Homeowners\' Association.')
    text=['NFH-HOA · Treasurer\'s Office','',f'Dear {name},','',
          'Your monthly association dues advance payment has been received, verified, and recorded.',
          '', 'ADVANCE PAYMENT SUMMARY']
    text.extend(f'{k}: {v}' for k,v in pairs)
    text += ['','MONTHLY DUES ADVANCE PAYMENT LEDGER',
             'Billing Month | Monthly Dues | Current Transaction Allocation | Remaining Balance']
    text.extend(' | '.join(row) for row in grid)
    text+=(['','ADVANCE PAYMENT PROMO BENEFITS']+promo_lines+
         ['','Codes may be redeemed once per qualifying certificate request by the owning homeowner only.',
          'Unused codes expire at 12:00 AM Asia/Manila on the listed date.',
          'Free certificates require normal approval and physical claiming at the HOA office.',
          footer,'','Respectfully,','North Fairway Homes Homeowners\' Association','Treasurer\'s Office'])
    esc=lambda s:escape(str(s),quote=True)
    def table(headers,rows):
        head=''.join(f'<th style="background:#1B4332;color:#fff;text-align:{"left" if i==0 else "right"};padding:9px 7px;font-size:12px;border:1px solid #E2EBE2">{esc(x)}</th>' for i,x in enumerate(headers))
        body=''.join('<tr>'+''.join(f'<td style="padding:9px 7px;border:1px solid #E2EBE2;background:{"#F4F9F4" if j%2 else "#fff"};color:#2D312E;font-size:13px;text-align:{"left" if i==0 else "right"};overflow-wrap:anywhere">{esc(x)}</td>' for i,x in enumerate(row))+'</tr>' for j,row in enumerate(rows))
        return f'<table role="table" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;width:100%;"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
    def h(title):return f'<h2 style="color:#2D6A4F;font-size:17px;margin:24px 0 12px">{esc(title)}</h2>'
    # Each label/value pair is left-aligned in the compact summary table.
    summary=table(['Description','Details'],pairs)
    promo=table(['Promotional Benefit','Entitlement'],promo_rows) if promo_rows else '<p>This transaction does not meet the full-year Advance Payment Promo requirements.</p>'
    codes_html = table(['Promo Code','Coverage Year','Expiration Date'],
        [[r['code'],str(r['coverage_year']),str(r['expires_at'])[:10]] for r in issued_codes]) if issued_codes else ''
    html=f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Advance Payment Confirmation</title></head>
    <body style="margin:0;background:#F4F9F4;font-family:Arial,Helvetica,sans-serif;color:#2D312E;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:15px 6px">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;background:white;border:1px solid #E2EBE2">
    <tr><td style="padding:20px;background:#1B4332;color:#fff;font-size:21px;font-weight:bold">NFH-HOA · Treasurer's Office</td></tr>
    <tr><td style="padding:18px;font-size:15px;line-height:1.6"><p>Dear {esc(name)},</p><p>Your monthly association dues advance payment has been received, verified, and recorded.</p>
    {h('Advance Payment Summary')}{summary}
    {h('Monthly Dues Advance Payment Ledger')}{table(['Billing Month','Monthly Dues','Current Allocation','Remaining Balance'],grid)}
    <p style="font-size:12px;color:#5F6B63">Allocated amounts shown are from this transaction only. Remaining balances include all verified allocations for these billing periods.</p>
    {h('Advance Payment Promo Benefits')}{promo}
    {h('Your Unique Promo Codes') if issued_codes else ''}{codes_html}
    <p>Each code is single-use, belongs to the registered homeowner, and expires at 12:00 AM Asia/Manila on the listed date. To redeem, choose a qualifying certificate in your homeowner account and select Apply Promo Code (Optional).</p>
    <p>Free certificates require the normal request and approval process, followed by physical claiming at the HOA office.</p>
    <p>{esc(footer)}</p><p>Respectfully,<br><strong>North Fairway Homes Homeowners' Association</strong><br>Treasurer's Office</p>
    </td></tr></table></td></tr></table></body></html>"""
    return '\n'.join(text),html
