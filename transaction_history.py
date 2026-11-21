"""Shared cash-basis payment history for authorized Admin and Treasurer users.

No payment mutations occur here. Monthly dues cash receipts include advances once,
not their subsequent allocations; external historical 'Paid' claims do not count.
"""
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape as xml_escape
from flask import Blueprint, jsonify, request, session, send_file
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, LongTable
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape

bp = Blueprint('shared_transaction_history', __name__)
connection = None
SQL = """
SELECT x.transaction_id,x.user_id,x.paid_at,x.category,x.description,x.amount,x.reference,x.source,
       u.homeowner_public_id,CONCAT(u.first_name,' ',u.last_name) AS homeowner,u.block,u.lot
FROM (
 SELECT CONCAT('REQ-',pt.id) transaction_id,pt.user_id,pt.payment_date paid_at,
 'Request Fee' category,COALESCE(r.request_type,'Document request') description,
 pt.amount,NULLIF(TRIM(pt.official_receipt_no),'') reference,
 'Treasurer Record Payment' source
 FROM payment_transactions pt JOIN requests r ON r.id=pt.request_id AND r.user_id=pt.user_id
 UNION ALL
 SELECT CONCAT('DUES-',dp.id),dp.user_id,DATE(dp.received_at),'Monthly Dues',
 'Monthly dues cash receipt',dp.amount,
 COALESCE(NULLIF(TRIM(pr.reference_no),''),NULLIF(TRIM(adv.payment_reference),'')) reference,
 CASE WHEN adv.payment_id IS NOT NULL THEN 'Advance Payment'
 WHEN pr.payment_id IS NOT NULL THEN 'Payment Plan Installment'
 ELSE 'Monthly Dues Payment' END
 FROM monthly_dues_payments dp
 LEFT JOIN nfh_advance_transactions adv ON adv.payment_id=dp.id
 LEFT JOIN nfh_plan_cash_receipts pr ON pr.payment_id=dp.id
 WHERE dp.voided_at IS NULL
 UNION ALL
 SELECT CONCAT('HIST-',hr.id),hr.user_id,hr.received_on,'Request Fee',h.request_type,
 hr.amount,NULLIF(TRIM(hr.receipt_no),''),'Historical SOA Verified Receipt'
 FROM nfh_historical_fee_receipts hr JOIN nfh_historical_request_fees h ON h.id=hr.fee_id AND h.user_id=hr.user_id
 UNION ALL
 SELECT CONCAT('HSOA-',rc.id,'-',a.category),rc.user_id,rc.received_on,
 CASE WHEN a.category='Request' THEN 'Request Fee' WHEN a.category='Others' THEN 'Others' ELSE 'Monthly Dues' END,
 GROUP_CONCAT(e.description ORDER BY e.id SEPARATOR '; '),SUM(a.amount),NULLIF(TRIM(rc.receipt_no),''),rc.source
 FROM nfh_historical_cash_receipts rc
 JOIN nfh_historical_cash_allocations a ON a.receipt_id=rc.id
 JOIN nfh_historical_import_entries e ON e.id=a.import_entry_id
 GROUP BY rc.id,rc.user_id,rc.received_on,a.category,rc.receipt_no,rc.source
) x JOIN users u ON u.id=x.user_id
WHERE u.role='Homeowner'
"""

def authorized():
    return session.get('user_id') and session.get('role') in ('Admin','Treasurer')

def params():
    q=(request.args.get('q') or '').strip()[:100]
    homeowner_id=request.args.get('homeowner_id',type=int)
    if request.args.get('homeowner_id') and (not homeowner_id or homeowner_id<1): raise ValueError('Invalid homeowner ID')
    category=request.args.get('category','all')
    if category not in ('all','Request Fee','Monthly Dues','Others'): raise ValueError('Invalid transaction category')
    order=request.args.get('sort','desc').lower()
    if order not in ('asc','desc'): raise ValueError('Invalid sorting order')
    kind=request.args.get('date_filter','all')
    if kind not in ('all','day','month','year','range'): raise ValueError('Invalid date filter')
    val=request.args.get('date','')
    lo=hi=None
    if kind=='day':lo=hi=date.fromisoformat(val)
    elif kind=='month':
        lo=date.fromisoformat(val+'-01');hi=date(lo.year+1,1,1) if lo.month==12 else date(lo.year,lo.month+1,1)
        hi=date.fromordinal(hi.toordinal()-1)
    elif kind=='year':
        year=int(val)
        if not 1900<=year<=2100:raise ValueError('Invalid year')
        lo=date(year,1,1);hi=date(year,12,31)
    elif kind=='range':
        lo=date.fromisoformat(request.args.get('start',''));hi=date.fromisoformat(request.args.get('end',''))
    if lo and hi and lo>hi:raise ValueError('Date range is reversed')
    page=max(1,request.args.get('page',1,type=int) or 1)
    if page>100000:raise ValueError('Page exceeds limit')
    return dict(q=q,homeowner_id=homeowner_id,category=category,order=order,kind=kind,date=val,lo=lo,hi=hi,page=page)

def clause(p):
    sql=SQL
    args=[]
    if p['homeowner_id']:
        sql+=' AND x.user_id=%s';args.append(p['homeowner_id'])
    if p['q']:
        sql+=" AND (CONCAT(u.first_name,' ',u.last_name) LIKE %s OR u.homeowner_public_id LIKE %s OR u.block LIKE %s OR u.lot LIKE %s)"
        like='%'+p['q'].replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        args += [like]*4
    if p['category']!='all':sql+=' AND x.category=%s';args.append(p['category'])
    if p['lo']:sql+=' AND x.paid_at >= %s';args.append(p['lo'])
    if p['hi']:sql+=' AND x.paid_at <= %s';args.append(p['hi'])
    return sql,args

def fetch(p,paginated=True):
    conn=connection()
    try:
        with conn.cursor() as cur:
            sql,args=clause(p)
            cur.execute('SELECT category,COALESCE(SUM(amount),0) total,COUNT(*) count FROM ('+sql+') summary GROUP BY category',args)
            totals={r['category']:Decimal(str(r['total'])) for r in cur.fetchall()}
            summary={'request_fee':totals.get('Request Fee',Decimal(0)), 'monthly_dues':totals.get('Monthly Dues',Decimal(0)), 'others':totals.get('Others',Decimal(0))}
            summary['overall']=summary['request_fee']+summary['monthly_dues']+summary['others']
            sql+=' ORDER BY x.paid_at '+p['order'].upper()+', x.transaction_id '+p['order'].upper()
            if paginated:sql+=' LIMIT %s OFFSET %s';args=args+[25,(p['page']-1)*25]
            cur.execute(sql,args);rows=cur.fetchall()
        for row in rows:
            row['paid_at']=row['paid_at'].isoformat() if hasattr(row['paid_at'],'isoformat') else str(row['paid_at'])
            row['amount']=str(row['amount'])
            # Do not substitute internal payment IDs for missing physical receipts.
            row['reference']=str(row.get('reference') or 'Not Recorded')
        return rows,{k:str(v) for k,v in summary.items()}
    finally:conn.close()

@bp.get('/api/transaction-history')
def history():
    if not authorized():return jsonify(error='Access denied'),403
    try:
        p=params();rows,totals=fetch(p)
        return jsonify(items=rows,totals=totals,page=p['page'],has_more=len(rows)==25)
    except ValueError as ex:return jsonify(error=str(ex)),400
    except Exception:return jsonify(error='Transaction report unavailable; verify payment schema and database connection'),503

@bp.get('/api/transaction-history/pdf')
def history_pdf():
    if not authorized():return jsonify(error='Access denied'),403
    try:
        p=params();rows,totals=fetch(p,paginated=False)
        if len(rows)>10000:return jsonify(error='Report exceeds 10,000 rows. Narrow filters.'),400
        styles=getSampleStyleSheet();story=[]
        story.append(Paragraph('NORTH FAIRWAY HOMES HOMEOWNERS ASSOCIATION INC.',styles['Heading2']))
        story.append(Paragraph('TRANSACTION HISTORY REPORT'+(' — ALL HOMEOWNERS' if not p['homeowner_id'] else ''),styles['Heading1']))
        scope='All Homeowners'
        if p['homeowner_id']:
            conn=connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT CONCAT_WS(' ',first_name,middle_name,last_name,suffix) name,homeowner_public_id,block,lot FROM users WHERE id=%s AND role='Homeowner'",(p['homeowner_id'],))
                    u=cur.fetchone()
                if not u:return jsonify(error='Selected homeowner not found'),404
                scope=u['name']+' | '+(u['homeowner_public_id'] or 'ID '+str(p['homeowner_id']))+' | Block '+str(u['block'] or '—')+', Lot '+str(u['lot'] or '—')
            finally: conn.close()
        story.append(Paragraph('Scope: '+xml_escape(scope),styles['Normal']))
        story.append(Paragraph('Generated: '+datetime.now().strftime('%Y-%m-%d %H:%M')+' | Text search: '+xml_escape(p['q'] or 'None')+' | Category: '+p['category']+' | Period: '+str(p['lo'] or 'All')+' to '+str(p['hi'] or 'All')+' | Sort: '+p['order'].upper(),styles['Normal']))
        story.append(Spacer(1,12))
        for name,key in [('Request Fee','request_fee'),('Monthly Dues','monthly_dues'),('Others','others')]:
            story.append(Paragraph(name+': PHP '+format(Decimal(totals[key]),',.2f'),styles['Normal']))
        story.append(Spacer(1,12))
        from nfh_report_layout import report_table, page_footer
        printable=landscape(A4)[0]-64
        data=[[str(r['transaction_id']),r['paid_at'],str(r['homeowner']),r['category'],str(r['description']),
               format(Decimal(r['amount']),',.2f'),str(r['reference'])] for r in rows]
        t=report_table(['Transaction ID','Date Paid','Homeowner','Type','Description','Amount (PHP)','Official Receipt Number'],
                       data,[78,65,106,72,150,80,printable-551],money_columns=(5,))
        story.append(t);buf=BytesIO()
        doc=SimpleDocTemplate(buf,pagesize=landscape(A4),leftMargin=32,rightMargin=32,topMargin=36,bottomMargin=36)
        doc.build(story,onFirstPage=page_footer,onLaterPages=page_footer);buf.seek(0)
        return send_file(buf,mimetype='application/pdf',as_attachment=True,download_name=('Transaction_History_'+('All_Homeowners' if not p['homeowner_id'] else (u['homeowner_public_id'] or str(p['homeowner_id'])).replace('/','-'))+'_'+date.today().isoformat()+'.pdf'))
    except ValueError as ex:return jsonify(error=str(ex)),400
    except Exception:return jsonify(error='Could not generate transaction history PDF'),503
