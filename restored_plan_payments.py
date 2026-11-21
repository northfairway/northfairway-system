"""Treasurer cash-only monthly dues allocation; payment and plan progress in one transaction."""
from decimal import Decimal
from datetime import datetime
from whole_peso import whole


def overview(c, homeowner_id):
    c.execute("SELECT id FROM users WHERE id=%s AND role='Homeowner'",(homeowner_id,))
    if not c.fetchone():return None
    c.execute("""SELECT d.id,d.amount,d.due_month,COALESCE(a.paid,0) paid,c.plan_id
       FROM monthly_dues d LEFT JOIN monthly_dues_plan_coverage c ON c.monthly_due_id=d.id
       LEFT JOIN (SELECT x.monthly_due_id,SUM(x.amount) paid FROM monthly_dues_allocations x
         JOIN monthly_dues_payments p ON p.id=x.payment_id WHERE p.voided_at IS NULL GROUP BY x.monthly_due_id) a ON a.monthly_due_id=d.id
       WHERE d.user_id=%s AND d.due_month<=CURRENT_DATE() ORDER BY d.due_month,d.id""",(homeowner_id,))
    bills=c.fetchall(); unpaid=[]
    for b in bills:
        remainder=Decimal(str(b['amount']))-Decimal(str(b['paid']))
        if remainder<0:raise ValueError('Overallocated monthly dues need reconciliation')
        if remainder:unpaid.append((b,remainder))
    c.execute("""SELECT id,total_amount,installment_count,status FROM monthly_dues_payment_plans
       WHERE user_id=%s AND status IN ('Active','Partially Paid','Overdue') ORDER BY id DESC LIMIT 1""",(homeowner_id,))
    plan=c.fetchone();plan_data=None;plan_id=plan['id'] if plan else None
    if plan:
        c.execute("SELECT installment_number,due_date,amount,paid_amount FROM monthly_dues_plan_installments WHERE plan_id=%s ORDER BY installment_number",(plan_id,))
        inst=c.fetchall();due=[x for x in inst if Decimal(str(x['amount']))>Decimal(str(x['paid_amount']))]
        covered=sum((v for b,v in unpaid if b['plan_id']==plan_id),Decimal('0'))
        plan_data={'id':plan_id,'status':plan['status'],'original':str(plan['total_amount']),'duration':plan['installment_count'],
           'remaining':str(covered),'verified_paid':str(Decimal(str(plan['total_amount']))-covered),
           'installment':str(Decimal(str(due[0]['amount']))-Decimal(str(due[0]['paid_amount']))) if due else '0',
           'next_due':str(due[0]['due_date']) if due else None,'remaining_installments':len(due)}
    today=datetime.now().date().replace(day=1)
    current=sum((v for b,v in unpaid if b['due_month']==today and b['plan_id']!=plan_id),Decimal('0'))
    outstanding=sum((v for _,v in unpaid),Decimal('0'))
    installment=Decimal(str(plan_data['installment'])) if plan_data else Decimal('0')
    return {'outstanding':str(outstanding),'unpaid_months':len(unpaid),'current_regular':str(current),
            'combined_suggested':str(min(outstanding,current+installment)),'plan':plan_data}


def record_payment(conn,user_id,amount,actor,paid_date,reference,request_key):
    amount=whole(amount,positive=True)
    with conn.cursor() as c:
        c.execute("SELECT id FROM users WHERE id=%s AND role='Homeowner' FOR UPDATE",(user_id,))
        if not c.fetchone():raise ValueError('Homeowner not found')
        c.execute("SELECT payment_id FROM nfh_plan_cash_receipts WHERE request_key=%s",(request_key,))
        found=c.fetchone()
        if found:return {'duplicate':True,'payment_id':found['payment_id']}
        c.execute("SELECT id FROM monthly_dues WHERE user_id=%s AND due_month<=CURRENT_DATE() FOR UPDATE",(user_id,))
        c.fetchall()
        # overview is computed under the same homeowner lock.
        summary=overview(c,user_id)
        outstanding=Decimal(summary['outstanding'])
        if Decimal(amount)>outstanding:raise ValueError('Cash received exceeds outstanding dues')
        c.execute("""SELECT d.id,d.due_month,d.amount,COALESCE(a.paid,0) paid,pc.plan_id FROM monthly_dues d
          LEFT JOIN monthly_dues_plan_coverage pc ON pc.monthly_due_id=d.id
          LEFT JOIN (SELECT x.monthly_due_id,SUM(x.amount) paid FROM monthly_dues_allocations x JOIN monthly_dues_payments p ON p.id=x.payment_id WHERE p.voided_at IS NULL GROUP BY x.monthly_due_id) a ON a.monthly_due_id=d.id
          WHERE d.user_id=%s AND d.due_month<=CURRENT_DATE() ORDER BY d.due_month,d.id""",(user_id,))
        bills=c.fetchall();today=datetime.now().date().replace(day=1)
        pid=summary['plan']['id'] if summary['plan'] else None
        bills.sort(key=lambda b:(0 if b['due_month']==today and b['plan_id']!=pid else 1 if pid and b['plan_id']==pid else 2,b['due_month'],b['id']))
        c.execute("INSERT INTO monthly_dues_payments(user_id,amount,received_at,verified_by,unapplied_amount) VALUES (%s,%s,%s,%s,0)",(user_id,amount,paid_date,actor))
        payment_id=c.lastrowid;remaining=Decimal(amount);plan_paid=Decimal('0')
        allocations=[]
        for b in bills:
            owing=Decimal(str(b['amount']))-Decimal(str(b['paid']))
            paid=min(owing,remaining)
            if paid>0:
                c.execute("INSERT INTO monthly_dues_allocations(payment_id,monthly_due_id,amount) VALUES(%s,%s,%s)",(payment_id,b['id'],paid))
                if paid==owing:c.execute("UPDATE monthly_dues SET status='Paid',settled_at=COALESCE(settled_at,NOW()),settled_by=%s WHERE id=%s",(actor,b['id']))
                allocations.append((b['id'],str(paid)))
                if pid and b['plan_id']==pid:plan_paid+=paid
                remaining-=paid
            if remaining==0:break
        if remaining:raise ValueError('Unallocated cash is not permitted')
        if plan_paid:
            c.execute("SELECT id,amount,paid_amount FROM monthly_dues_plan_installments WHERE plan_id=%s ORDER BY installment_number FOR UPDATE",(pid,))
            installment_rows=c.fetchall();to_apply=plan_paid
            for x in installment_rows:
                used=min(to_apply,Decimal(str(x['amount']))-Decimal(str(x['paid_amount'])))
                if used>0:c.execute("UPDATE monthly_dues_plan_installments SET paid_amount=paid_amount+%s WHERE id=%s",(used,x['id']));to_apply-=used
                if to_apply==0:break
            if to_apply:raise ValueError('Plan schedule and dues ledger require reconciliation')
            c.execute("""UPDATE monthly_dues_payment_plans SET status=CASE WHEN NOT EXISTS(
              SELECT 1 FROM monthly_dues_plan_installments WHERE plan_id=%s AND paid_amount<amount)
              THEN 'Completed' ELSE 'Partially Paid' END WHERE id=%s""",(pid,pid))
        c.execute("INSERT INTO nfh_plan_cash_receipts(payment_id,user_id,request_key,reference_no) VALUES(%s,%s,%s,%s)",(payment_id,user_id,request_key,reference or None))
        c.execute("INSERT INTO audit_logs(username,role,action,item,prev_val,new_val) VALUES(%s,'Treasurer','Verified Dues Cash Payment',%s,%s,%s)",(actor,str(user_id),str(outstanding),str(outstanding-Decimal(amount))))
        return {'duplicate':False,'payment_id':payment_id,'allocations':allocations,'remaining_balance':str(outstanding-Decimal(amount))}
