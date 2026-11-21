"""Missing dues plan created in same transaction as billing adjustment."""
from datetime import date
from calendar import monthrange
from decimal import Decimal
from whole_peso import whole,installments

def schedule(total,count,first_due):
    if isinstance(first_due,str): first_due=date.fromisoformat(first_due)
    amounts=installments(total,count)
    result=[]
    for i,amount in enumerate(amounts):
        index=first_due.month-1+i
        year=first_due.year+index//12
        month=index%12+1
        result.append((i+1,date(year,month,min(first_due.day,monthrange(year,month)[1])),amount))
    return result

def create_plan(cur,user_id,count,start,actor,latest,months):
    if date.fromisoformat(start)<date.today(): raise ValueError('First installment due date cannot be in the past')
    cur.execute("SELECT id FROM monthly_dues_payment_plans WHERE user_id=%s AND status IN ('Active','Partially Paid','Overdue') FOR UPDATE",(user_id,))
    if cur.fetchone(): raise ValueError('Homeowner already has an active payment plan')
    cur.execute("""SELECT d.id,d.amount,COALESCE(a.paid,0) paid,COALESCE(x.discount,0) discount FROM monthly_dues d
        LEFT JOIN (SELECT a.monthly_due_id,SUM(a.amount) paid FROM monthly_dues_allocations a JOIN monthly_dues_payments p ON p.id=a.payment_id WHERE p.voided_at IS NULL GROUP BY a.monthly_due_id) a ON a.monthly_due_id=d.id
        LEFT JOIN (SELECT monthly_due_id,SUM(discount_amount) discount FROM nfh_advance_periods GROUP BY monthly_due_id) x ON x.monthly_due_id=d.id
        LEFT JOIN monthly_dues_plan_coverage c ON c.monthly_due_id=d.id
        WHERE d.user_id=%s AND d.due_month<=CURRENT_DATE() AND c.monthly_due_id IS NULL ORDER BY d.due_month""",(user_id,))
    covered=[]
    for row in cur.fetchall():
        remaining=Decimal(str(row['amount']))-Decimal(str(row['paid']))-Decimal(str(row['discount']))
        if remaining>0: covered.append((row['id'],whole(remaining,positive=True)))
    total=sum(amt for _,amt in covered)
    rows=schedule(total,count,start)
    remarks=f'{months} newly applied missing months through {latest}; payment plan total PHP {total}; {count} monthly installments, starting {start}. Whole-peso allocations: '+', '.join(str(a) for _,_,a in rows)
    cur.execute("INSERT INTO monthly_dues_payment_plans(user_id,total_amount,installment_count,status,created_by,remarks) VALUES (%s,%s,%s,'Active',%s,%s)",(user_id,total,count,actor,remarks[:1000]))
    plan_id=cur.lastrowid
    for due_id,amount in covered:
        cur.execute('INSERT INTO monthly_dues_plan_coverage(plan_id,monthly_due_id,original_covered_amount) VALUES (%s,%s,%s)',(plan_id,due_id,amount))
    for n,d,amount in rows:
        cur.execute('INSERT INTO monthly_dues_plan_installments(plan_id,installment_number,due_date,amount,paid_amount) VALUES (%s,%s,%s,%s,0)',(plan_id,n,d,amount))
    return {'id':plan_id,'total':total,'schedule':[{'installment':n,'due_date':str(d),'amount':a} for n,d,a in rows]}
