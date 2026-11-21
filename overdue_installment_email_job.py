"""Daily, one-time 5-calendar-day overdue notices for payment plan installments.

Run: python overdue_installment_email_job.py --once
No server-side web request or browser login is needed. SMTP and database settings use app.py.
"""
import argparse
from datetime import datetime, timedelta, date
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

MANILA = ZoneInfo('Asia/Manila')
SUBJECT = 'NFH-HOA | Overdue Payment Plan Installment Reminder'


def amount(value):
    value = Decimal(str(value or 0))
    if value != value.to_integral_value():
        raise ValueError('Fractional legacy amount: manual reconciliation required before whole-peso email')
    return f'₱{int(value):,}'


def eligible(due_date, paid, assessed, today):
    return due_date + timedelta(days=5) <= today and Decimal(str(paid)) < Decimal(str(assessed))


def ledger(cursor, user_id, plan_id):
    # A billing obligation appears once in assessed totals, even when covered by a plan.
    cursor.execute("""SELECT d.id,d.amount,d.status,COALESCE(a.paid,0) paid,pc.plan_id
      FROM monthly_dues d
      LEFT JOIN monthly_dues_plan_coverage pc ON pc.monthly_due_id=d.id
      LEFT JOIN (SELECT x.monthly_due_id,SUM(x.amount) paid FROM monthly_dues_allocations x
        JOIN monthly_dues_payments p ON p.id=x.payment_id WHERE p.voided_at IS NULL
        GROUP BY x.monthly_due_id) a ON a.monthly_due_id=d.id
      WHERE d.user_id=%s AND d.due_month<=CURRENT_DATE()""", (user_id,))
    total = Decimal(0); regular = Decimal(0); covered = Decimal(0)
    rows = cursor.fetchall()
    for r in rows:
        # Legacy Paid entries may predate allocations; preserve their settled status.
        outstanding = Decimal(0) if r['status']=='Paid' else max(Decimal(0),Decimal(str(r['amount']))-Decimal(str(r['paid'])))
        total += outstanding
        if r['plan_id']==plan_id: covered += outstanding
        else: regular += outstanding
    return {'total':total,'regular':regular,'plan':covered}


def compose(user, installment, plan, summary, today):
    name=f"{user['first_name']} {user['last_name']}".strip()
    due=installment['due_date']; assessed=Decimal(str(installment['amount'])); paid=Decimal(str(installment['paid_amount']))
    remaining=assessed-paid; days=(today-due).days
    rows=[('Payment plan reference',str(plan['id'])),('Installment',f"{installment['installment_number']} of {plan['installment_count']}"),
          ('Scheduled due date',due.strftime('%B %d, %Y')),('Original installment',amount(assessed)),
          ('Verified installment paid',amount(paid)),('Remaining installment balance',amount(remaining)),
          ('Days overdue',str(days)),('Notification date',today.strftime('%B %d, %Y')),('Status','Overdue')]
    summary_rows=[('Monthly association dues', amount(summary['monthly_rate'])),
       ('Regular outstanding dues outside plan', amount(summary['regular'])),
       ('Remaining payment plan balance', amount(summary['plan'])),
       ('Currently overdue installment', amount(remaining)),
       ('Total outstanding monthly dues', amount(summary['total']))]
    text=['Dear '+name+',','','Our records indicate that a scheduled installment remains unpaid after the five-day grace period.','',
      'OVERDUE INSTALLMENT DETAILS']+[f'{k}: {v}' for k,v in rows]+['','MONTHLY DUES SUMMARY']+[f'{k}: {v}' for k,v in summary_rows]+[
      '', 'The overdue installment is part of the remaining payment plan balance and is not an additional charge.',
      'Please settle your payment in person with the NFH-HOA Treasurer. Online payments are not supported.',
      'If you have already paid, please contact the Treasurer to verify your recorded payment.',
      'This email is generated from current recorded financial information.','','North Fairway Homes Homeowners\' Association']
    def table(title, pairs):
        return '<h3 style="color:#2D6A4F;margin:24px 0 9px">'+escape(title)+'</h3><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">'+''.join('<tr><td style="padding:10px;border-bottom:1px solid #E2EBE2">'+escape(k)+'</td><td style="padding:10px;border-bottom:1px solid #E2EBE2;text-align:right;font-weight:bold">'+escape(v)+'</td></tr>' for k,v in pairs)+'</table>'
    html=('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;background:#F4F9F4;font-family:Arial,Helvetica,sans-serif;color:#2D312E"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:20px 10px"><table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:640px;background:white"><tr><td style="background:#1B4332;color:white;padding:22px;font-size:20px;font-weight:bold">North Fairway Homes Homeowners\' Association</td></tr><tr><td style="padding:22px"><h2 style="color:#1B4332">Payment Plan Installment Overdue Notice</h2><p>Dear '+escape(name)+',</p><p>Our records indicate that a scheduled installment remains unpaid after the five-day grace period.</p><p><b>Homeowner ID:</b> '+escape(str(user.get('homeowner_public_id') or user['id']))+' · <b>Block/Lot:</b> '+escape(str(user.get('block') or '-'))+'/'+escape(str(user.get('lot') or '-'))+'</p>'+table('Overdue Installment Details',rows)+table('Monthly Dues Summary',summary_rows)+'<p>The overdue installment is part of the remaining payment plan balance and is not an additional charge.</p><p>Settle the payment in person with the NFH-HOA Treasurer. Online payments are not supported.</p><p>If you have already paid, contact the Treasurer to verify your transaction.</p><p><small>This notification is automatically generated from recorded financial information.</small></p></td></tr><tr><td style="padding:18px;text-align:center;background:#F4F9F4;color:#2D312E">North Fairway Homes Homeowners\' Association · Treasurer\'s Office</td></tr></table></td></tr></table></body></html>')
    return '\n'.join(text), html


def run_once(*, now=None, connection_factory=None, sender=None):
    from app import app, get_db_connection, mail, Message
    today=(now or datetime.now(MANILA)).astimezone(MANILA).date()
    factory=connection_factory or get_db_connection
    stats={'eligible':0,'sent':0,'failed':0,'skipped':0}
    with app.app_context():
        db=factory(autocommit=False)
        try:
            with db.cursor() as c:
                c.execute("""SELECT i.id,i.plan_id,i.installment_number,i.due_date,i.amount,i.paid_amount,
                       p.user_id,p.installment_count,p.status,u.first_name,u.last_name,u.email,
                       u.homeowner_public_id,u.block,u.lot,u.id AS homeowner_id
                    FROM monthly_dues_plan_installments i
                    JOIN monthly_dues_payment_plans p ON p.id=i.plan_id
                    JOIN users u ON u.id=p.user_id
                    WHERE p.status IN ('Active','Partially Paid','Overdue')
                      AND i.due_date<=%s AND i.amount>i.paid_amount AND u.role='Homeowner' AND u.status='Active'
                    ORDER BY i.due_date,i.id""", (today-timedelta(days=5),))
                candidate_rows=c.fetchall()
            db.commit()
            for r in candidate_rows:
                if not eligible(r['due_date'],r['paid_amount'],r['amount'],today):continue
                stats['eligible']+=1
                if not r['email']:
                    stats['skipped']+=1;continue
                try:
                    # Each claim is locked by a unique installment/type entry.
                    with db.cursor() as c:
                        c.execute("""INSERT IGNORE INTO nfh_installment_overdue_notices
                          (installment_id,plan_id,user_id,due_date,status)
                          VALUES (%s,%s,%s,%s,'Pending')""",(r['id'],r['plan_id'],r['user_id'],r['due_date']))
                    db.commit()
                    with db.cursor() as c:
                        c.execute("SELECT id,status FROM nfh_installment_overdue_notices WHERE installment_id=%s FOR UPDATE",(r['id'],))
                        notice=c.fetchone()
                        if notice['status'] in ('Sent','Sending'):
                            db.rollback();stats['skipped']+=1;continue
                        # Recheck under homeowner and installment locks before dispatch.
                        c.execute('SELECT id FROM users WHERE id=%s FOR UPDATE',(r['user_id'],));c.fetchone()
                        c.execute("SELECT amount,paid_amount,due_date FROM monthly_dues_plan_installments WHERE id=%s FOR UPDATE",(r['id'],))
                        inst=c.fetchone()
                        if not eligible(inst['due_date'],inst['paid_amount'],inst['amount'],today):
                            db.rollback();stats['skipped']+=1;continue
                        r.update(inst)
                        summary=ledger(c,r['user_id'],r['plan_id'])
                        c.execute("SELECT amount FROM fees WHERE item_name='Monthly Dues' AND status='Active' LIMIT 1")
                        setting=c.fetchone();summary['monthly_rate']=Decimal(str(setting['amount'])) if setting else Decimal(0)
                        c.execute("UPDATE nfh_installment_overdue_notices SET status='Sending',error_details=NULL WHERE id=%s",(notice['id'],))
                    db.commit()
                    text,html=compose({'id':r['user_id'],'first_name':r['first_name'],'last_name':r['last_name'],
                        'homeowner_public_id':r['homeowner_public_id'],'block':r['block'],'lot':r['lot']},r,r,summary,today)
                    if sender:sender(r['email'],SUBJECT,text,html)
                    else:
                        msg=Message(SUBJECT,recipients=[r['email']]);msg.body=text;msg.html=html;mail.send(msg)
                    with db.cursor() as c:
                        c.execute("UPDATE nfh_installment_overdue_notices SET status='Sent',sent_at=NOW(),error_details=NULL WHERE installment_id=%s",(r['id'],))
                    db.commit();stats['sent']+=1
                except Exception as e:
                    db.rollback()
                    app.logger.exception('Payment-plan overdue email failed for installment %s',r['id'])
                    with db.cursor() as c:
                        c.execute("UPDATE nfh_installment_overdue_notices SET status='Failed',error_details=%s WHERE installment_id=%s AND status!='Sent'",(str(e)[:1000],r['id']))
                    db.commit();stats['failed']+=1
        finally:db.close()
    return stats


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    print(run_once())
