"""Treasurer financial import: validated, homeowner-scoped and idempotent.

Requires SQL/02_nfh_hoa_existing_database_upgrade.sql before activation.
"""
import csv
import io
import json
import secrets
import hashlib
import uuid
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from flask import Blueprint, request, jsonify, session, send_file
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Protection, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.comments import Comment

bp = Blueprint('treasurer_financial', __name__)
connection = None
notification_sender = None
staged = {}  # In-process preview only; restart invalidates tokens; bounded below.
COLS = {
 'dues': ['Homeowner ID','Homeowner Name','Block','Lot','Billing Month','Billing Year','Monthly Dues Amount','Amount Paid','Remaining Due','Payment Status','Remarks'],
 'soa': ['Request ID','Type','Description','Date','Amount','Status','OR Number']
}

def guard():
    return session.get('user_id') is not None and session.get('role')=='Treasurer'

def error(msg, code=400):
    return jsonify(status='error',message=msg),code

def money(value):
    try:
        d=Decimal(str(value if value is not None else '0'))
        if not d.is_finite() or d<0 or d != d.quantize(Decimal('1')): raise ValueError()
        return d
    except (ValueError,InvalidOperation): raise ValueError('Amounts must be nonnegative whole pesos.')

def period(y,m):
    try:
        y=int(y);m=int(m)
        if not 2000 <= y <= 2100: raise ValueError()
        return date(y,m,1)
    except (ValueError,TypeError): raise ValueError('Invalid billing month or year.')

def check_homeowner(cur, public_id, selected_id):
    cur.execute("SELECT id, homeowner_public_id, first_name, last_name, block, lot, mobile, email, address_line FROM users WHERE id=%s AND role='Homeowner'",(selected_id,))
    u=cur.fetchone()
    if not u: raise ValueError('Homeowner could not be found.')
    if str(public_id).strip() != str(u['homeowner_public_id']).strip(): raise ValueError('Homeowner ID does not match the selected homeowner.')
    return u

@bp.get('/api/treasurer/homeowners/search')
def homeowners():
    if not guard(): return error('Treasurer access required.',403)
    q=(request.args.get('q') or '').strip()[:100]
    if not q: return jsonify(status='success',items=[])
    like='%'+q.replace('%','\\%').replace('_','\\_')+'%'
    conn=connection()
    try:
        with conn.cursor() as c:
            c.execute("""SELECT id,homeowner_public_id, CONCAT(first_name,' ',last_name) AS name,block,lot
                FROM users WHERE role='Homeowner' AND (homeowner_public_id LIKE %s OR CONCAT(first_name,' ',last_name) LIKE %s OR block LIKE %s OR lot LIKE %s)
                ORDER BY last_name,first_name LIMIT 40""",(like,like,like,like))
            rows=c.fetchall()
    finally:conn.close()
    return jsonify(status='success',items=rows)

@bp.get('/treasurer/api/soa/homeowners')
def soa_homeowners():
    """Independent, role-restricted homeowner search for the Treasurer SOA."""
    if not guard(): return error('Treasurer access required.',403)
    q=(request.args.get('search') or '').strip()[:100]
    if not q:return jsonify(status='success',items=[])
    like='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    conn=connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id,homeowner_public_id,CONCAT(first_name,' ',last_name) AS name,block,lot
                FROM users WHERE role='Homeowner' AND
                (LOWER(CONCAT(first_name,' ',last_name)) LIKE LOWER(%s) OR
                 LOWER(homeowner_public_id) LIKE LOWER(%s) OR
                 LOWER(COALESCE(block,'')) LIKE LOWER(%s) OR LOWER(COALESCE(lot,'')) LIKE LOWER(%s) OR
                 LOWER(CONCAT('Block ',COALESCE(block,''),' Lot ',COALESCE(lot,''))) LIKE LOWER(%s))
                ORDER BY last_name,first_name,id LIMIT 40""",(like,like,like,like,like))
            items=cur.fetchall()
        return jsonify(status='success',items=items)
    finally:conn.close()

@bp.get('/treasurer/import-template/<kind>')
def template(kind):
    if not guard(): return error('Treasurer access required.',403)
    if kind != 'soa':return error('The separate Monthly Dues import has been retired.',404)
    wb=Workbook();ws=wb.active
    if kind=='soa':
        selected=request.args.get('homeowner_id',type=int)
        if not selected:return error('Select a homeowner before downloading the SOA template.')
        conn=connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""SELECT id, homeowner_public_id, first_name,last_name,mobile,email,
                    address_line,block,lot FROM users WHERE id=%s AND role='Homeowner'""",(selected,))
                u=cur.fetchone()
        finally:conn.close()
        if not u:return error('Homeowner not found.',404)
        ws.title='Historical SOA'
        ws.merge_cells('A1:G1');ws['A1']='NORTH FAIRWAY HOMES HOMEOWNERS ASSOCIATION'
        ws.merge_cells('A2:G2');ws['A2']='STATEMENT OF ACCOUNT — HISTORICAL REQUEST SERVICE DATA IMPORT'
        info={'Name':(str(u['first_name'])+' '+str(u['last_name'])).strip(),
              'Homeowner ID':u['homeowner_public_id'] or '', 'Contact':u['mobile'] or '',
              'Email':u['email'] or '', 'Address':u['address_line'] or ('Block '+str(u['block'] or '')+' Lot '+str(u['lot'] or ''))}
        for row,(label,value) in enumerate(info.items(),4):
            ws.cell(row,1,label);ws.merge_cells(start_row=row,start_column=2,end_row=row,end_column=7)
            ws.cell(row,2,str(value))
        ws['A10']='Date Imported:';ws['B10']='Assigned by system after confirmed import'
        for col,label in enumerate(COLS['soa'],1):ws.cell(12,col,label)
        ws['C13'].comment=Comment('For Request, enter an existing HOA service type. For Others, describe the fee.','NFH-HOA')
        ws.freeze_panes='A13';ws.auto_filter.ref='A12:G212'
        widths={'A':22,'B':22,'C':39,'D':20,'E':18,'F':18,'G':26}
        for col,width in widths.items():ws.column_dimensions[col].width=width
        for row in (1,2):
            ws.row_dimensions[row].height=26
            c=ws.cell(row,1);c.fill=PatternFill('solid',fgColor='1B4332');c.font=Font(color='FFFFFF',bold=True,size=13 if row==1 else 11)
            c.alignment=Alignment(horizontal='center',vertical='center')
        for row in range(4,9):
            ws.cell(row,1).font=Font(bold=True,color='1B4332')
            ws.cell(row,2).protection=Protection(locked=True)
        for cell in ws[12]:
            cell.fill=PatternFill('solid',fgColor='1B4332');cell.font=Font(color='FFFFFF',bold=True)
            cell.alignment=Alignment(horizontal='center')
        ws.protection.sheet=True
        ws.protection.selectLockedCells=False
        ws.protection.selectUnlockedCells=False
        ws.protection.autoFilter=False
        for row in range(13,213):
            ws.cell(row,1,'AUTO');ws.cell(row,1).protection=Protection(locked=True)
            for col in (2,3,4,5,6,7):
                cell=ws.cell(row,col);cell.protection=Protection(locked=False)
                cell.fill=PatternFill('solid',fgColor='F4F9F4')
            ws.cell(row,4).number_format='yyyy-mm-dd'
            ws.cell(row,5).number_format='₱#,##0'
            ws.cell(row,7).number_format='@'
        dv=DataValidation(type='list',formula1='"Paid,Unpaid"',allow_blank=True)
        dv.error='Select Paid or Unpaid.';dv.errorTitle='Invalid status';dv.showErrorMessage=True
        ws.add_data_validation(dv);dv.add('F13:F212')
        type_dv=DataValidation(type='list',formula1='"Request,Monthly Dues,Others"',allow_blank=False)
        type_dv.error='Choose Request, Monthly Dues, or Others.';type_dv.showErrorMessage=True
        ws.add_data_validation(type_dv);type_dv.add('B13:B212')
        from openpyxl.formatting.rule import FormulaRule
        warn=PatternFill('solid',fgColor='FFE4B5')
        ws.conditional_formatting.add('G13:G212',FormulaRule(formula=['AND($F13="Paid",LEN(TRIM($G13))=0)'],fill=warn))
        ws.conditional_formatting.add('F13:G212',FormulaRule(formula=['AND($F13="Unpaid",LEN(TRIM($G13))>0)'],fill=warn))
        examples=wb.create_sheet('Examples - DO NOT IMPORT')
        examples.append(['Instructions — excluded from imports'])
        examples.append(['Use the Historical SOA worksheet only. Do not enter a Request ID.'])
        examples.append(['Paid records require a valid OR Number and Treasurer confirmation. Conflicting receipts require review.'])
        examples.append(COLS['soa'])
        examples.append(['AUTO','Request','Proof of Residency','2026-10-15',50,'Paid','OR-2026-001'])
        examples.append(['AUTO','Monthly Dues','September 2026 Monthly Dues','2026-09-01',100,'Unpaid',''])
        examples.append(['AUTO','Others','Historical HOA Fee','2026-10-18',50,'Paid','OR-2026-002'])
        for col,width in {'A':22,'B':22,'C':45,'D':20,'E':18,'F':18,'G':26}.items():examples.column_dimensions[col].width=width
        filename='SOA_Historical_Import_'+''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in str(u['homeowner_public_id'] or selected))+'.xlsx'
    else:
        ws.title='Missing Monthly Dues';ws.append(COLS[kind]);ws.freeze_panes='A2'
        from openpyxl.utils import get_column_letter
        for idx,field in enumerate(COLS[kind],1):ws.column_dimensions[get_column_letter(idx)].width=max(18,min(30,len(field)+3))
        filename='NFH_dues_import_template.xlsx'
    buf=io.BytesIO();wb.save(buf);buf.seek(0)
    return send_file(buf,as_attachment=True,download_name=filename,mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def read_rows(file,kind=None):
    filename=(file.filename or '').lower()
    raw=file.read(5*1024*1024+1)
    if len(raw)>5*1024*1024:raise ValueError('Maximum upload size is 5 MB.')
    digest=hashlib.sha256(raw).hexdigest()
    if kind=='soa':
        if not filename.endswith('.xlsx'):raise ValueError('Historical SOA requires the homeowner-specific .xlsx template.')
        w=load_workbook(io.BytesIO(raw),read_only=False,data_only=False)
        try:
            if 'Historical SOA' not in w.sheetnames:raise ValueError('Invalid Historical SOA worksheet.')
            sh=w['Historical SOA']
            header=[sh.cell(12,i).value for i in range(1,8)]
            if header!=COLS['soa']:raise ValueError('Historical SOA column headings have changed.')
            meta={str(sh.cell(row,1).value):str(sh.cell(row,2).value or '').strip() for row in range(4,9)}
            rows=[]
            for row in range(13,sh.max_row+1):
                vals=[sh.cell(row,i).value for i in range(1,8)]
                if all(v in (None,'','AUTO') for v in vals):continue
                if vals[0] not in (None,'','AUTO'):raise ValueError('Request ID is system-generated; do not edit row '+str(row)+'.')
                if any(getattr(v,'data_type',None)=='f' for v in (sh.cell(row,i) for i in range(1,8))):raise ValueError('Excel formulas are not accepted at row '+str(row)+'.')
                r=dict(zip(header,vals));r['_excel_row']=row;r['_file_hash']=digest;r['_meta']=meta
                rows.append(r)
            return rows
        finally:w.close()
    if filename.endswith('.csv'):
        decoded=raw.decode('utf-8-sig')
        return list(csv.DictReader(io.StringIO(decoded)))
    if not filename.endswith('.xlsx'):raise ValueError('Upload .xlsx or .csv only.')
    w=load_workbook(io.BytesIO(raw),read_only=True,data_only=True)
    try:
        sh=w.active; items=iter(sh.values);heads=[str(x or '').strip() for x in next(items)]
        return [dict(zip(heads,row)) for row in items if any(v not in (None,'') for v in row)]
    finally:w.close()

def validate(kind, rows, homeowner_id, cur):
    results=[];seen=set();receipt_owners={};receipt_dates={}
    for n,r in enumerate(rows,2):
        try:
            missing=[x for x in COLS[kind] if x not in r]
            if missing:raise ValueError('Missing columns: '+', '.join(missing))
            u=check_homeowner(cur,(r.get('_meta') or {}).get('Homeowner ID') if kind=='soa' else r.get('Homeowner ID'),homeowner_id)
            if kind=='dues' and (str(r.get('Block') or '').strip()!=str(u['block'] or '').strip() or str(r.get('Lot') or '').strip()!=str(u['lot'] or '').strip()):raise ValueError('Block or Lot does not match the selected homeowner.')
            full_name=(str(u['first_name'])+' '+str(u['last_name'])).strip().casefold()
            if kind=='dues' and str(r.get('Homeowner Name') or '').strip().casefold()!=full_name:raise ValueError('Homeowner name does not match the selected homeowner.')
            if kind=='dues':
                due=period(r.get('Billing Year'),r.get('Billing Month'));amount=money(r.get('Monthly Dues Amount'));paid=money(r.get('Amount Paid'));remaining=money(r.get('Remaining Due'))
                if paid+remaining!=amount:raise ValueError('Amount Paid + Remaining Due must equal the assessed amount.')
                status=str(r.get('Payment Status') or '').strip().lower()
                if status != ('paid' if remaining==0 else 'unpaid' if paid==0 else 'partial'):raise ValueError('Payment Status does not match amounts.')
                key=('dues',homeowner_id,due.isoformat())
                cur.execute('SELECT id FROM monthly_dues WHERE user_id=%s AND due_month=%s LIMIT 1',(homeowner_id,due))
                if cur.fetchone() or key in seen:raise LookupError('Monthly dues already exist for this homeowner and billing period.')
                if paid: raise ValueError('Historical payments require separate verified source references; paid or partially paid rows need manual review.')
                payload={'due':due.isoformat(),'amount':str(amount)}
            else:
                meta=r.get('_meta') or {}
                expected={'Name':full_name,'Homeowner ID':str(u['homeowner_public_id'] or ''),
                          'Contact':str(u.get('mobile') or ''),'Email':str(u.get('email') or ''),
                          'Address':str(u.get('address_line') or ('Block '+str(u['block'] or '')+' Lot '+str(u['lot'] or '')))}
                for field,actual in expected.items():
                    given=str(meta.get(field,'')).strip()
                    if given.casefold()!=actual.strip().casefold():raise ValueError(field+' does not match the selected homeowner.')
                when=r.get('Date')
                if isinstance(when,datetime):when=when.date()
                elif not isinstance(when,date):when=date.fromisoformat(str(when).strip())
                amount=money(r.get('Amount'))
                if not amount:raise ValueError('Amount must be greater than zero.')
                status=str(r.get('Status') or '').strip().lower()
                if status not in ('paid','unpaid'):raise ValueError('Status must be Paid or Unpaid.')
                description=str(r.get('Description') or '').strip()
                if not description:raise ValueError('Description is required.')
                tx_type=str(r.get('Type') or '').strip()
                if tx_type not in ('Request','Monthly Dues','Others'):
                    raise ValueError('Transaction Type is required and must be Request, Monthly Dues, or Others.')
                or_number=str(r.get('OR Number') or '').strip()
                if status=='paid' and not or_number:
                    raise ValueError('Official Receipt Number is required for Paid transactions.')
                if status=='unpaid' and or_number:
                    raise ValueError('Unpaid transactions must not contain an OR Number.')
                if or_number:
                    import re
                    if len(or_number)>120 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/._\-]*',or_number):
                        raise ValueError('Official Receipt Number has invalid characters.')
                    # One receipt can cover multiple obligations, subject to ownership and reference checks.
                    if or_number in receipt_owners and receipt_owners[or_number] != homeowner_id:
                        raise ValueError('Conflicting receipt ownership; requires manual review.')
                    receipt_owners[or_number]=homeowner_id
                    if or_number in receipt_dates and receipt_dates[or_number]!=when:
                        raise ValueError('Rows sharing one OR Number must use the same payment date; manual review required.')
                    receipt_dates[or_number]=when
                    cur.execute('SELECT id FROM payment_transactions WHERE official_receipt_no=%s LIMIT 1',(or_number,))
                    if cur.fetchone():raise ValueError('OR Number already exists in verified payments; manual review required.')
                    cur.execute('SELECT id FROM nfh_historical_fee_receipts WHERE receipt_no=%s LIMIT 1',(or_number,))
                    if cur.fetchone():raise ValueError('OR Number already exists in historical verified receipts; manual review required.')
                    cur.execute('SELECT homeowner_id FROM nfh_historical_import_entries WHERE or_number=%s LIMIT 1',(or_number,))
                    old_receipt=cur.fetchone()
                    if old_receipt: raise ValueError('OR Number was previously imported; review before reusing.')
                    cur.execute('SELECT user_id FROM nfh_historical_cash_receipts WHERE receipt_no=%s LIMIT 1',(or_number,))
                    if cur.fetchone(): raise ValueError('Official Receipt Number is already recorded; manual review required.')
                # Stable source identity avoids re-importing the same worksheet row.
                ref='HSOA-'+hashlib.sha256((r['_file_hash']+':'+str(r['_excel_row'])).encode()).hexdigest()[:32]
                key=('soa',homeowner_id,ref)
                cur.execute('SELECT id FROM nfh_historical_import_entries WHERE homeowner_id=%s AND external_ref=%s LIMIT 1',(homeowner_id,ref))
                if cur.fetchone() or key in seen:
                    raise LookupError('This exact historical template row has already been imported.')
                service_name=None
                if tx_type=='Monthly Dues':
                    due=period(when.year,when.month)
                    dues_key=('dues',homeowner_id,due.isoformat())
                    cur.execute('SELECT id FROM monthly_dues WHERE user_id=%s AND due_month=%s LIMIT 1',(homeowner_id,due))
                    if cur.fetchone() or dues_key in seen:
                        raise LookupError('Monthly dues already exist for this homeowner and billing period.')
                    seen.add(dues_key)
                elif tx_type=='Request':
                    cur.execute('SELECT service_name FROM service_types WHERE LOWER(service_name)=LOWER(%s) LIMIT 1',(description,))
                    service=cur.fetchone()
                    if not service:raise ValueError('Unknown HOA service type for Request.')
                    service_name=service['service_name']
                    cur.execute('SELECT id FROM nfh_historical_request_fees WHERE user_id=%s AND request_type=%s AND request_date=%s AND amount=%s LIMIT 1',(homeowner_id,service_name,when,amount))
                    if cur.fetchone():raise ValueError('Possible matching historical request fee: manual review required before posting.')
                payload={'date':when.isoformat(),'service':service_name,'amount':str(amount),'ref':ref,
                         'description':description,'category':tx_type,'reported_status':status,
                         'or_number':or_number,'due':period(when.year,when.month).isoformat() if tx_type=='Monthly Dues' else None}
                if status=='paid':
                    seen.add(key)
                    results.append({'row':r.get('_excel_row',n),'status':'Valid — Paid',
                        'message':'Paid transaction is valid and will be recorded as a verified historical payment upon Treasurer confirmation.',
                        'payload':payload})
                    continue
            seen.add(key)
            results.append({'row':r.get('_excel_row',n),'status':'Valid — Unpaid' if kind=='soa' else 'Valid',
                'message':'Unpaid transaction is valid and will be recorded as an outstanding homeowner obligation.' if kind=='soa' else 'Ready for import','payload':payload})
        except LookupError as e:results.append({'row':r.get('_excel_row',n),'status':'Duplicate','message':str(e)})
        except (ValueError,TypeError) as e:results.append({'row':r.get('_excel_row',n),'status':'Requires Review' if 'manual review' in str(e) else 'Invalid','message':str(e)})
    return results

@bp.post('/api/treasurer/import/preview')
def preview():
    if not guard():return error('Treasurer access required.',403)
    kind=request.form.get('kind');homeowner_id=request.form.get('homeowner_id',type=int)
    if kind != 'soa' or not homeowner_id:return error('Select a homeowner for Statement of Account import.')
    file=request.files.get('file')
    if file is None:return error('Select an import file.')
    try:
        rows=read_rows(file,kind)
        if not rows or len(rows)>2000:raise ValueError('File must contain between 1 and 2,000 data rows.')
        conn=connection()
        try:
            with conn.cursor() as c:results=validate(kind,rows,homeowner_id,c)
        finally:conn.close()
        # Preview only: this summary is not persisted as financial postings.
        preview_rows=[]
        for idx, item in enumerate(results):
            raw_row=rows[idx] if idx < len(rows) else {}
            preview_rows.append({**{k:v for k,v in item.items() if k!='payload'},
                'description':str(raw_row.get('Description') or raw_row.get('Billing Month') or ''),
                'date':str(raw_row.get('Date') or raw_row.get('Billing Year') or ''),
                'amount':str(raw_row.get('Amount') or raw_row.get('Monthly Dues Amount') or ''),
                'reported_status':str(raw_row.get('Status') or raw_row.get('Payment Status') or ''),
                'transaction_type':str(raw_row.get('Type') or ''),
                'or_number':str(raw_row.get('OR Number') or ''),
                'request_id':str(raw_row.get('Request ID') or 'AUTO')})
        token=secrets.token_urlsafe(24)
        if len(staged)>50:staged.clear()
        staged[token]={'uid':session['user_id'],'homeowner':homeowner_id,'kind':kind,'rows':rows,'created':datetime.now().timestamp(),'filename':file.filename}
        # Read-only HOA membership lookup. Inactive membership never rejects
        # historical financial transactions, alters receipts, or changes login access.
        membership_status='Active'
        check_conn=connection()
        try:
            with check_conn.cursor() as mcur:
                mcur.execute('''SELECT COALESCE(m.status,'Active') AS membership_status
                    FROM users u LEFT JOIN nfh_homeowner_membership m ON m.homeowner_id=u.id
                    WHERE u.id=%s AND u.role='Homeowner' ''',(homeowner_id,))
                mrow=mcur.fetchone()
                if mrow:membership_status=mrow['membership_status']
        finally:check_conn.close()
        return jsonify(status='success',token=token,results=preview_rows,filename=file.filename,homeowner_id=homeowner_id,
            membership_status=membership_status,
            membership_note=('Inactive HOA membership: historical SOA transactions remain eligible for import.' if membership_status=='Inactive' else 'Active HOA membership: standard historical SOA validation applies.'),
            counts={s:sum(x['status']==s for x in results) for s in ['Valid','Valid — Paid','Valid — Unpaid','Duplicate','Invalid','Requires Review']})
    except Exception as e:
        if isinstance(e,(ValueError,UnicodeError,StopIteration)):return error(str(e))
        bp.logger.exception('Import preview unavailable') if hasattr(bp,'logger') else None
        return error('Import preview failed. Check the database schema and file format.',503)

@bp.post('/api/treasurer/import/commit')
def commit():
    if not guard():return error('Treasurer access required.',403)
    info=staged.pop((request.get_json(silent=True) or {}).get('token'),None)
    if not info or info['uid']!=session['user_id'] or datetime.now().timestamp()-info['created']>900:return error('Preview expired. Revalidate the file.')
    conn=None
    try:
        conn=connection(autocommit=False)
        with conn.cursor() as c:
            c.execute('SELECT id FROM users WHERE id=%s FOR UPDATE',(info['homeowner'],))
            results=validate(info['kind'],info['rows'],info['homeowner'],c)
            accepted=0
            paid_receipts={}
            unpaid=[]
            for result in results:
                if result['status'] not in ('Valid — Paid','Valid — Unpaid'):continue
                entry=result['payload'];category=entry['category'];is_paid=result['status']=='Valid — Paid'
                obligation_id=None
                if category=='Monthly Dues':
                    c.execute("INSERT INTO monthly_dues (user_id,due_month,amount,status) VALUES (%s,%s,%s,%s)",
                              (info['homeowner'],entry['due'],entry['amount'],'Paid' if is_paid else 'Unpaid'))
                    obligation_id=c.lastrowid
                elif category=='Request':
                    c.execute("""INSERT INTO nfh_historical_request_fees
                        (user_id,request_type,request_date,amount,external_ref,description,imported_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (info['homeowner'],entry['service'],entry['date'],entry['amount'],entry['ref'],entry['description'],session['user_id']))
                    obligation_id=c.lastrowid
                c.execute("""INSERT INTO nfh_historical_import_entries
                    (homeowner_id,external_ref,transaction_type,description,transaction_date,amount,
                     reported_status,or_number,verification_status,imported_by,verified_by,verified_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (info['homeowner'],entry['ref'],category,entry['description'],entry['date'],entry['amount'],
                     'Paid' if is_paid else 'Unpaid',entry['or_number'] or None,
                     'Verified' if is_paid else 'Unpaid',session['user_id'],session['user_id'] if is_paid else None,
                     datetime.now() if is_paid else None))
                historical_id=c.lastrowid
                if is_paid:
                    receipt=entry['or_number']
                    if receipt not in paid_receipts:
                        c.execute("""INSERT INTO nfh_historical_cash_receipts
                            (user_id,receipt_no,received_on,verified_by,source)
                            VALUES (%s,%s,%s,%s,'Historical SOA Import')""",
                            (info['homeowner'],receipt,entry['date'],session['user_id']))
                        paid_receipts[receipt]=(c.lastrowid,entry['date'])
                    receipt_id,paid_date=paid_receipts[receipt]
                    if paid_date!=entry['date']:
                        raise ValueError('Rows sharing an OR Number must have the same payment date.')
                    c.execute("""INSERT INTO nfh_historical_cash_allocations
                        (receipt_id,import_entry_id,monthly_due_id,historical_fee_id,category,amount)
                        VALUES (%s,%s,%s,%s,%s,%s)""",
                        (receipt_id,historical_id,obligation_id if category=='Monthly Dues' else None,
                         obligation_id if category=='Request' else None,category,entry['amount']))
                else:
                    unpaid.append(dict(category=category,description=entry['description'],date=entry['date'],amount=entry['amount']))
                accepted+=1
            c.execute("""INSERT INTO nfh_import_batches
                (import_type,homeowner_id,source_filename,imported_by,total_rows,accepted_rows,duplicate_rows,rejected_rows,validation_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (info['kind'],info['homeowner'],str(info['filename'])[:255],session['user_id'],len(results),accepted,
                 sum(r['status']=='Duplicate' for r in results),
                 sum(r['status'] in ('Invalid','Requires Review') for r in results),
                 json.dumps([{k:v for k,v in r.items() if k!='payload'} for r in results])))
            batch_id=c.lastrowid
            for receipt_id, _ in paid_receipts.values():
                c.execute('UPDATE nfh_historical_cash_receipts SET import_batch_id=%s WHERE id=%s',(batch_id,receipt_id))
            c.execute("INSERT INTO audit_logs (username,role,action,item,new_val) VALUES (%s,'Treasurer','Historical SOA import confirmed',%s,%s)",
                      (str(session['user_id']),'SOA import batch '+str(batch_id),json.dumps({'accepted':accepted,'paid_receipts':len(paid_receipts),'unpaid':len(unpaid)})))
        conn.commit()
        # Notification delivery happens only after the financial transaction is committed.
        if unpaid:
            try: _notify_unpaid_import(info['homeowner'],batch_id,unpaid)
            except Exception:
                import logging;logging.exception('Unpaid SOA import email could not be queued')
        return jsonify(status='success',imported=accepted,results=[{k:v for k,v in r.items() if k!='payload'} for r in results])
    except Exception:
        if conn:conn.rollback()
        return error('Import failed and was rolled back. Confirm the required SQL upgrade has been installed.',503)
    finally:
        if conn:conn.close()

@bp.get('/api/admin/financial-import-audit')
def audit():
    if session.get('role')!='Admin':return error('Administrator access required.',403)
    conn=connection()
    try:
        with conn.cursor() as c:
            c.execute("""SELECT b.id,b.import_type,b.source_filename,b.created_at,b.total_rows,b.accepted_rows,b.duplicate_rows,b.rejected_rows,b.validation_json,
                CONCAT(u.first_name,' ',u.last_name) AS homeowner, CONCAT(t.first_name,' ',t.last_name) AS treasurer
                FROM nfh_import_batches b JOIN users u ON u.id=b.homeowner_id JOIN users t ON t.id=b.imported_by ORDER BY b.created_at DESC LIMIT 200""")
            rows=c.fetchall()
        for row in rows:
            row['created_at']=row['created_at'].isoformat();row['validation_json']=json.loads(row['validation_json'] or '[]')
        return jsonify(status='success',items=rows)
    except Exception:return error('Import audit requires the database upgrade.',503)
    finally:conn.close()

def _statement_data(homeowner_id):
    from financial_ledger import snapshot
    start=request.args.get('start') or None
    end=request.args.get('end') or None
    for value in (start,end):
        if value: date.fromisoformat(value)
    transaction_type=(request.args.get('transaction_type') or 'all').strip().lower()
    payment_status=(request.args.get('payment_status') or 'all').strip().lower()
    conn=connection()
    try:
        with conn.cursor() as cur:
            return snapshot(cur,homeowner_id,start,end,transaction_type,payment_status)
    finally:conn.close()

@bp.get('/api/treasurer/financial-statement/<int:homeowner_id>')
def statement(homeowner_id):
    if not guard():return error('Treasurer access required.',403)
    try:return jsonify(status='success',**_statement_data(homeowner_id))
    except ValueError as e:return error(str(e),404 if 'not found' in str(e) else 400)
    except Exception:return error('Statement unavailable: verify dues/payment tables and apply migrations.',503)

@bp.get('/api/treasurer/financial-statement/<int:homeowner_id>/pdf')
def statement_pdf(homeowner_id):
    """SOA export. Layout/section order follows NFH_SOA_7 (2).pdf."""
    if not guard():return error('Treasurer access required.',403)
    try:
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from xml.sax.saxutils import escape as xml_escape
        from nfh_report_layout import report_table, page_footer
        from datetime import datetime as dt
        result=_statement_data(homeowner_id)  # Identical filtered snapshot as on-screen SOA.
        buf=io.BytesIO()
        doc=SimpleDocTemplate(buf,pagesize=A4,leftMargin=17*mm,rightMargin=17*mm,
                              topMargin=18*mm,bottomMargin=18*mm)
        styles=getSampleStyleSheet()
        section_style=ParagraphStyle('NFHSOASection',parent=styles['Heading3'],
                                     fontName='Helvetica-BoldOblique',fontSize=11.5,
                                     leading=15,spaceBefore=15,spaceAfter=6)
        note_style=ParagraphStyle('NFHSOANote',parent=styles['Normal'],fontSize=8.5,leading=11)
        story=[Paragraph('North Fairway Homes Homeowners Association',styles['Heading2']),
               Paragraph('Statement of Account',styles['Heading1'])]
        u=result['homeowner']
        story.append(Paragraph('Homeowner: %s (%s) — Block %s / Lot %s'%tuple(
            xml_escape(str(u.get(k) or '')) for k in ('name','homeowner_public_id','block','lot')),styles['Normal']))
        def formatted_date(value):
            if not value:return 'Unavailable'
            try:return dt.strptime(str(value)[:10],'%Y-%m-%d').strftime('%b %d, %Y')
            except (ValueError,TypeError):return 'Unavailable'
        def money(value):
            try:return 'PHP {:,.2f}'.format(float(value or 0))
            except (ValueError,TypeError):return '—'
        pretty={'all':'All Transactions','monthly_dues':'Monthly Dues',
                'request_fee':'Request Fee','others':'Others'}
        story.append(Paragraph('Period: %s to %s | Generated: %s'%(
            xml_escape(result['start'] or 'Beginning'),xml_escape(result['end'] or 'Current'),
            result['as_of']),styles['Normal']))
        if result['transaction_type']!='all' or result['payment_status']!='all':
            story.append(Paragraph('Filtered Report — Transaction Type: %s | Payment Status: %s'%(
                pretty[result['transaction_type']],result['payment_status'].replace('_',' ').title()),
                styles['Normal']))
        def section(title, headers, rows, keys, widths):
            story.append(Paragraph(title,section_style))
            rendered=[]
            for row in rows:
                values=[]
                for key in keys:
                    value=row.get(key)
                    if key in ('date','payment_date'):value=formatted_date(value)
                    elif key in ('assessed','paid','remaining','amount','opening','charges','payments_during_period','closing'):value=money(value)
                    else:value=str(value) if value not in (None,'') else '—'
                    values.append(value)
                rendered.append(values)
            story.append(report_table(headers,rendered,[w*doc.width/sum(widths) for w in widths],
                          money_columns=tuple(i for i,k in enumerate(keys) if k in
                           ('assessed','paid','remaining','amount','opening','charges','payments_during_period','closing')),
                          font_size=6.5 if len(headers)==8 else 8))
        # Opening/closing are cash-based for the selected type and range. Status-filter
        # reports have no attributable receipt history, so show obligation totals
        # without suggesting they represent an account-wide balance.
        if result['payment_status']=='all':
            summary=[dict(opening=result['opening_balance'],charges=result['charges'],
                          payments_during_period=result['payments_during_period'],closing=result['closing_balance'])]
            labels=['Opening','Charges','Payments','Closing']
            fields=['opening','charges','payments_during_period','closing']
            caption='Account Summary' if result['transaction_type']=='all' else 'Account Summary — Filtered '+pretty[result['transaction_type']]
        else:
            summary=[dict(opening='—',charges=result['filtered_assessed'],
                          payments_during_period=result['filtered_paid'],closing=result['filtered_remaining'])]
            labels=['Opening','Charges','Applied Payments','Remaining']
            fields=['opening','charges','payments_during_period','closing']
            caption='Account Summary — Filtered Obligations (not a cash balance)'
        section(caption,labels,summary,fields,[1,1,1,1])
        keys=['date','description','assessed','paid','remaining','status','payment_date','or_number']
        widths=[1.55,2.45,1.02,.93,1.13,1.1,1.4,1.25]
        kind=result['transaction_type']
        if kind in ('all','monthly_dues'):
            rows=[]
            for item in result['monthly_dues']:
                r=dict(item)
                # Coverage uses the original month stored in the ledger's description.
                r['description']=str(item.get('description') or '').replace('Monthly Dues — ','')
                rows.append(r)
            section('Monthly Dues',['Transaction Date','Coverage','Assessed','Paid','Remaining','Status','Payment Date','OR Number'],rows,keys,widths)
        if kind in ('all','request_fee'):
            section('Request Fees',['Transaction Date','Request','Fee','Paid','Remaining','Status','Payment Date','OR Number'],
                    result['request_fees'],keys,widths)
        if kind in ('all','others'):
            section('Others',['Transaction Date','Description','Amount','Paid','Remaining','Status','Payment Date','OR Number'],
                    result['other_charges'],keys,widths)
        if result['payment_status']=='all' and result['payment_history']:
            section('Cash Payments',['Transaction Date','Type','Amount'],result['payment_history'],
                    ['date','kind','amount'],[2,2,1])
        elif kind=='all' and result['payment_status']=='all':
            section('Cash Payments',['Transaction Date','Type','Amount'],[],['date','kind','amount'],[2,2,1])
        story.append(Spacer(1,12))
        story.append(Paragraph('Charges and cash receipts are reported by effective date. '
                              'Unverified imported payments are excluded.',note_style))
        doc.build(story,onFirstPage=page_footer,onLaterPages=page_footer)
        buf.seek(0)
        return send_file(buf,as_attachment=True,download_name='NFH_SOA_%s.pdf'%homeowner_id,
                         mimetype='application/pdf')
    except ValueError as e:return error(str(e))
    except Exception:return error('Unable to generate Statement of Account PDF.',503)

@bp.get('/api/treasurer/transaction-history')
def transaction_history():
    if not guard():return error('Treasurer access required.',403)
    q=(request.args.get('q') or '').strip()[:100]
    page=max(1,request.args.get('page',default=1,type=int));limit=25
    conn=connection()
    try:
        with conn.cursor() as c:
            # UNION ALL: document cash receipts and dues cash receipts are distinct sources.
            sql="""SELECT x.* FROM (
                SELECT pt.id AS transaction_id,pt.user_id,pt.payment_date AS transaction_date,'Request Fee Payment' AS transaction_type,pt.amount,pt.official_receipt_no AS reference FROM payment_transactions pt
                UNION ALL
                SELECT dp.id AS transaction_id,dp.user_id,DATE(dp.received_at) AS transaction_date,'Monthly Dues Payment' AS transaction_type,dp.amount,CAST(dp.id AS CHAR) AS reference FROM monthly_dues_payments dp WHERE dp.voided_at IS NULL
                UNION ALL
                SELECT hr.id AS transaction_id,hr.user_id,hr.received_on AS transaction_date,'Historical Request Fee Payment' AS transaction_type,hr.amount,hr.receipt_no AS reference FROM nfh_historical_fee_receipts hr
            ) x JOIN users u ON u.id=x.user_id
            WHERE (%s='' OR CONCAT(u.first_name,' ',u.last_name) LIKE %s OR u.homeowner_public_id LIKE %s)
            ORDER BY x.transaction_date DESC,x.transaction_id DESC LIMIT %s OFFSET %s"""
            c.execute(sql,(q,'%'+q+'%','%'+q+'%',limit,(page-1)*limit));items=c.fetchall()
        for row in items:
            row['transaction_date']=row['transaction_date'].isoformat() if row.get('transaction_date') else None
            row['amount']=str(row['amount'])
        return jsonify(status='success',items=items,page=page,has_more=len(items)==limit)
    except Exception:return error('Transaction history unavailable; verify payment tables.',503)
    finally:conn.close()


@bp.post('/api/treasurer/historical-request-fees/<int:fee_id>/payment')
def pay_historical_fee(fee_id):
    # Record verified cash against one imported historical fee atomically.

    # Requires SQL/02_NFH_HOA_EXISTING_DATABASE_UPGRADE.sql. A repeated receipt
    # is rejected by a database unique key; no payment is inferred from uploads.
    if not guard(): return error('Treasurer access required.',403)
    payload=request.get_json(silent=True) or {}
    try:
        amount=money(payload.get('amount'))
        if amount <= 0: raise ValueError('Payment must be greater than zero.')
        receipt=str(payload.get('receipt_no') or '').strip()
        if not receipt or len(receipt)>120:raise ValueError('Official receipt number is required (maximum 120 characters).')
        received_on=date.fromisoformat(str(payload.get('received_on') or ''))
        if received_on>date.today():raise ValueError('Payment date cannot be in the future.')
    except (ValueError,TypeError) as exc:return error(str(exc))
    conn=None
    try:
        conn=connection(autocommit=False)
        with conn.cursor() as cur:
            cur.execute('SELECT id,user_id,amount FROM nfh_historical_request_fees WHERE id=%s FOR UPDATE',(fee_id,))
            fee=cur.fetchone()
            if not fee:raise ValueError('Historical fee not found.')
            cur.execute('SELECT COALESCE(SUM(amount),0) AS paid FROM nfh_historical_fee_receipts WHERE fee_id=%s',(fee_id,))
            paid=money(cur.fetchone()['paid'])
            if paid+amount>money(fee['amount']):raise ValueError('Payment exceeds the remaining request fee.')
            cur.execute('''INSERT INTO nfh_historical_fee_receipts
                (fee_id,user_id,amount,receipt_no,received_on,received_by)
                VALUES (%s,%s,%s,%s,%s,%s)''',
                (fee_id,fee['user_id'],amount,receipt,received_on,session['user_id']))
            receipt_id=cur.lastrowid
            cur.execute('''INSERT INTO audit_logs (username,role,action,item,prev_val,new_val)
                VALUES (%s,'Treasurer','Historical Request Fee Payment',%s,%s,%s)''',
                (str(session['user_id']),str(fee_id),str(paid),
                 json.dumps({'receipt_id':receipt_id,'receipt_no':receipt,'amount':str(amount),'new_paid':str(paid+amount)})))
        conn.commit()
        return jsonify(status='success',receipt_id=receipt_id,remaining=str(money(fee['amount'])-paid-amount))
    except ValueError as exc:
        if conn:conn.rollback()
        return error(str(exc),400)
    except Exception:
        if conn:conn.rollback()
        return error('Payment was not posted; verify unique receipt number and required schema.',409)
    finally:
        if conn:conn.close()


 
# Reusable owner-id autocomplete for authorized Treasurer financial views.
@bp.get('/api/treasurer/homeowners/autocomplete')
@bp.get('/api/homeowners/autocomplete')
def treasurer_homeowner_autocomplete():
    if not (session.get('user_id') and session.get('role') in ('Treasurer','Admin')): return error('Authorized financial officer access required.',403)
    term=(request.args.get('q') or '').strip()[:100]
    if len(term)<2: return jsonify(items=[])
    escaped=term.replace('\\','\\\\').replace('%',r'\%').replace('_',r'\_')
    pattern='%'+escaped+'%'
    conn=connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id,CONCAT_WS(' ',first_name,middle_name,last_name,suffix) AS name,
                      homeowner_public_id,block,lot FROM users
                      WHERE role='Homeowner' AND (CONCAT_WS(' ',first_name,middle_name,last_name,suffix) LIKE %s
                      OR CONCAT_WS(' ',first_name,last_name) LIKE %s OR first_name LIKE %s OR last_name LIKE %s
                      OR homeowner_public_id LIKE %s OR block LIKE %s OR lot LIKE %s
                      OR CONCAT('B',COALESCE(block,''),' L',COALESCE(lot,'')) LIKE %s)
                      ORDER BY last_name,first_name,id LIMIT 15""",(pattern,)*8)
            return jsonify(items=cur.fetchall())
    except Exception:
        import logging;logging.exception('Homeowner autocomplete unavailable')
        return error('Homeowner search unavailable.',503)
    finally: conn.close()

# Dedicated Treasurer Historical Payment — uses the same authoritative SOA import obligations.
@bp.get('/api/treasurer/historical-payments')
def historical_payment_records():
    if not guard(): return error('Treasurer access required.',403)
    q=(request.args.get('q') or '').strip()[:100]
    selected_user=request.args.get('homeowner_id',type=int)
    if request.args.get('homeowner_id') and (not selected_user or selected_user<1): return error('Invalid homeowner identifier.',400)
    status=request.args.get('status','Unpaid')
    category=request.args.get('type','All')
    if category not in ('All','Request','Others'):return error('Invalid transaction type.')
    sort=request.args.get('sort','desc')
    if status not in ('Unpaid','Partially Paid','Paid','All') or sort not in ('asc','desc'):
        return error('Invalid filter.')
    try:
        page=max(1,min(10000,int(request.args.get('page',1))))
        limit=20
        day=request.args.get('date','').strip()
        date_filter=request.args.get('date_filter','all')
        if date_filter not in ('all','day','month','year'): raise ValueError('Invalid date filter')
        if date_filter=='day':date.fromisoformat(day)
        elif date_filter=='month':date.fromisoformat(day+'-01')
        elif date_filter=='year' and not (day.isdigit() and 1900<=int(day)<=2100):raise ValueError('Invalid year')
    except ValueError:return error('Invalid date or page.')
    conn=connection()
    try:
        with conn.cursor() as c:
            # Import row is authoritative; no duplicate obligation joins or multiplication of allocations.
            base=""" FROM nfh_historical_import_entries e
            JOIN users u ON u.id=e.homeowner_id AND u.role='Homeowner'
            LEFT JOIN (SELECT import_entry_id,SUM(amount) AS paid FROM nfh_historical_cash_allocations GROUP BY import_entry_id) a ON a.import_entry_id=e.id
            LEFT JOIN (SELECT h.user_id,h.external_ref,SUM(r.amount) paid FROM nfh_historical_request_fees h JOIN nfh_historical_fee_receipts r ON r.fee_id=h.id GROUP BY h.user_id,h.external_ref) legacy ON legacy.user_id=e.homeowner_id AND legacy.external_ref=e.external_ref AND e.transaction_type='Request'
            WHERE e.transaction_type IN ('Request','Others') AND e.reported_status='Unpaid' """
            if category!='All':base+=' AND e.transaction_type=%s'
            args=[category] if category!='All' else []
            if selected_user:
                base += ' AND e.homeowner_id=%s';args.append(selected_user)
            if q:
                base += " AND (CONCAT(u.first_name,' ',u.last_name) LIKE %s OR u.homeowner_public_id LIKE %s OR u.block LIKE %s OR u.lot LIKE %s OR e.external_ref LIKE %s OR e.description LIKE %s OR CAST(e.id AS CHAR) LIKE %s OR EXISTS (SELECT 1 FROM nfh_historical_cash_allocations ca JOIN nfh_historical_cash_receipts cr ON cr.id=ca.receipt_id WHERE ca.import_entry_id=e.id AND cr.receipt_no LIKE %s))"
                like='%'+q.replace('%',r'\%').replace('_',r'\_')+'%';args += [like]*8
            if day and date_filter=='day':base+=' AND e.transaction_date=%s';args.append(day)
            if day and date_filter=='month':base+=' AND DATE_FORMAT(e.transaction_date,\'%Y-%m\')=%s';args.append(day)
            if day and date_filter=='year':base+=' AND YEAR(e.transaction_date)=%s';args.append(int(day))
            status_expr="CASE WHEN (COALESCE(a.paid,0)+COALESCE(legacy.paid,0))>=e.amount THEN 'Paid' WHEN (COALESCE(a.paid,0)+COALESCE(legacy.paid,0))>0 THEN 'Partially Paid' ELSE 'Unpaid' END"
            filtered=base+((' AND '+status_expr+'=%s') if status!='All' else '')
            filterargs=args+([status] if status!='All' else [])
            c.execute('SELECT COUNT(*) AS total'+filtered,filterargs);total=c.fetchone()['total']
            c.execute("""SELECT e.id,e.external_ref,e.description,e.transaction_type,e.transaction_date,e.amount,
                   (COALESCE(a.paid,0)+COALESCE(legacy.paid,0)) AS paid,GREATEST(e.amount-(COALESCE(a.paid,0)+COALESCE(legacy.paid,0)),0) AS remaining,
                   """+status_expr+""" AS payment_status,u.id AS homeowner_id,u.homeowner_public_id,
                   CONCAT(u.first_name,' ',u.last_name) AS homeowner,u.block,u.lot"""+filtered+
                   ' ORDER BY e.transaction_date '+('ASC' if sort=='asc' else 'DESC')+',e.id '+('ASC' if sort=='asc' else 'DESC')+' LIMIT %s OFFSET %s',filterargs+[limit,(page-1)*limit])
            items=c.fetchall()
            c.execute("""SELECT COALESCE(SUM(GREATEST(e.amount-(COALESCE(a.paid,0)+COALESCE(legacy.paid,0)),0)),0) unpaid,
                         COUNT(DISTINCT CASE WHEN (COALESCE(a.paid,0)+COALESCE(legacy.paid,0))<e.amount THEN e.homeowner_id END) homeowners
                         FROM nfh_historical_import_entries e
                         LEFT JOIN (SELECT import_entry_id,SUM(amount) paid FROM nfh_historical_cash_allocations GROUP BY import_entry_id) a ON a.import_entry_id=e.id
                         LEFT JOIN (SELECT h.user_id,h.external_ref,SUM(r.amount) paid FROM nfh_historical_request_fees h JOIN nfh_historical_fee_receipts r ON r.fee_id=h.id GROUP BY h.user_id,h.external_ref) legacy ON legacy.user_id=e.homeowner_id AND legacy.external_ref=e.external_ref AND e.transaction_type='Request'
                         WHERE e.transaction_type IN ('Request','Others') AND e.reported_status='Unpaid' """)
            summary=c.fetchone()
            c.execute("""SELECT e.transaction_type,COALESCE(SUM(GREATEST(e.amount-COALESCE(a.paid,0)-COALESCE(legacy.paid,0),0)),0) unpaid
                         FROM nfh_historical_import_entries e
                         LEFT JOIN (SELECT import_entry_id,SUM(amount) paid FROM nfh_historical_cash_allocations GROUP BY import_entry_id) a ON a.import_entry_id=e.id
                         LEFT JOIN (SELECT h.user_id,h.external_ref,SUM(r.amount) paid FROM nfh_historical_request_fees h JOIN nfh_historical_fee_receipts r ON r.fee_id=h.id GROUP BY h.user_id,h.external_ref) legacy ON legacy.user_id=e.homeowner_id AND legacy.external_ref=e.external_ref AND e.transaction_type='Request'
                         WHERE e.transaction_type IN ('Request','Others') AND e.reported_status='Unpaid' GROUP BY e.transaction_type""")
            categories={r['transaction_type']:str(r['unpaid']) for r in c.fetchall()}
            summary['request_unpaid']=categories.get('Request','0')
            summary['others_unpaid']=categories.get('Others','0')
            c.execute("""SELECT COALESCE(SUM(a.amount),0) paid FROM nfh_historical_cash_allocations a
                         JOIN nfh_historical_import_entries e ON e.id=a.import_entry_id
                         WHERE e.transaction_type IN ('Request','Others') AND e.reported_status='Unpaid'""")
            verified_new=Decimal(str(c.fetchone()['paid']))
            c.execute("""SELECT COALESCE(SUM(r.amount),0) paid FROM nfh_historical_fee_receipts r
                       JOIN nfh_historical_request_fees h ON h.id=r.fee_id
                       JOIN nfh_historical_import_entries e ON e.homeowner_id=h.user_id AND e.external_ref=h.external_ref
                       WHERE e.transaction_type='Request' AND e.reported_status='Unpaid'""")
            summary['paid']=verified_new+Decimal(str(c.fetchone()['paid']))
        for x in items:
            x['transaction_date']=x['transaction_date'].isoformat()
            for key in ('amount','paid','remaining'):x[key]=str(x[key])
        return jsonify(status='success',items=items,summary={k:str(v) for k,v in summary.items()},total=total,page=page,page_size=limit)
    except Exception:
        import logging;logging.exception('Historical payment listing failed')
        return error('Historical payment records unavailable. Check the database schema.',503)
    finally:conn.close()

@bp.post('/api/treasurer/historical-payments/<int:entry_id>/pay')
def record_historical_payment(entry_id):
    if not guard():return error('Treasurer access required.',403)
    data=request.get_json(silent=True) or {}
    try:
        amount=money(data.get('amount'))
        if amount<=0:raise ValueError('A positive whole-peso amount is required.')
        or_number=str(data.get('receipt_no') or '').strip()
        if not or_number or len(or_number)>120:raise ValueError('An OR Number is required (maximum 120 characters).')
        pay_date=date.fromisoformat(str(data.get('received_on') or ''))
        if pay_date>date.today():raise ValueError('Payment date cannot be in the future.')
        key=str(data.get('request_key') or '').strip()
        if not (12<=len(key)<=100) or not all(ch.isalnum() or ch in '-_' for ch in key):
            raise ValueError('A valid payment submission key is required.')
    except (ValueError,TypeError) as exc:return error(str(exc))
    conn=None
    try:
        conn=connection(autocommit=False)
        with conn.cursor() as c:
            # Lock the obligation to serialize concurrent payments from any device.
            c.execute("""SELECT e.id,e.homeowner_id,e.external_ref,e.description,e.transaction_type,e.amount,e.transaction_date,
                         u.email,u.first_name,u.last_name,u.homeowner_public_id
                         FROM nfh_historical_import_entries e JOIN users u ON u.id=e.homeowner_id
                         WHERE e.id=%s AND e.transaction_type IN ('Request','Others') AND e.reported_status='Unpaid' FOR UPDATE""",(entry_id,))
            entry=c.fetchone()
            if not entry:raise ValueError('Eligible unpaid historical transaction not found.')
            c.execute('SELECT id FROM nfh_historical_cash_receipts WHERE request_key=%s',(key,))
            old=c.fetchone()
            if old:
                conn.rollback()
                return jsonify(status='success',message='Payment was already recorded.',receipt_id=old['id'],duplicate=True)
            c.execute('SELECT COALESCE(SUM(amount),0) paid FROM nfh_historical_cash_allocations WHERE import_entry_id=%s',(entry_id,))
            paid=Decimal(str(c.fetchone()['paid']))
            if entry['transaction_type']=='Request':
                c.execute('SELECT COALESCE(SUM(r.amount),0) paid FROM nfh_historical_fee_receipts r JOIN nfh_historical_request_fees h ON h.id=r.fee_id WHERE h.user_id=%s AND h.external_ref=%s',(entry['homeowner_id'],entry['external_ref']))
                paid += Decimal(str(c.fetchone()['paid']))
            remaining=Decimal(str(entry['amount']))-paid
            if amount>remaining:raise ValueError('Payment exceeds the remaining balance.')
            # One OR means one parent receipt. Never reuse it for an unrelated payment.
            for table,column in [('nfh_historical_cash_receipts','receipt_no'),('nfh_historical_fee_receipts','receipt_no'),('payment_transactions','official_receipt_no')]:
                c.execute('SELECT 1 FROM '+table+' WHERE '+column+'=%s LIMIT 1',(or_number,))
                if c.fetchone():raise ValueError('Official receipt number is already in use.')
            fee=None
            if entry['transaction_type']=='Request':
                c.execute('SELECT id FROM nfh_historical_request_fees WHERE user_id=%s AND external_ref=%s LIMIT 1',(entry['homeowner_id'],entry['external_ref']))
                fee=c.fetchone()
            if entry['transaction_type']=='Request' and not fee:raise ValueError('The linked historical request-fee obligation was not found.')
            c.execute("""INSERT INTO nfh_historical_cash_receipts
                       (user_id,receipt_no,received_on,verified_by,source,request_key)
                       VALUES (%s,%s,%s,%s,'Historical Payment',%s)""",
                      (entry['homeowner_id'],or_number,pay_date,session['user_id'],key))
            receipt_id=c.lastrowid
            c.execute("""INSERT INTO nfh_historical_cash_allocations
                       (receipt_id,import_entry_id,historical_fee_id,category,amount)
                       VALUES (%s,%s,%s,%s,%s)""",(receipt_id,entry_id,fee['id'] if fee else None,entry['transaction_type'],amount))
            new_remaining=remaining-amount
            new_status='Paid' if new_remaining==0 else 'Partially Paid'
            c.execute("""INSERT INTO audit_logs(username,role,action,item,prev_val,new_val)
                       VALUES (%s,'Treasurer','Historical Payment',%s,%s,%s)""",
                      (str(session['user_id']),str(entry_id),json.dumps({'remaining':str(remaining)}),
                       json.dumps({'receipt_id':receipt_id,'OR':or_number,'amount':str(amount),'remaining':str(new_remaining),'status':new_status})))
        conn.commit()
        # Send only after commit; SMTP failure does not roll back payment.
        delivery='not_configured'
        if notification_sender:
            try:
                from html import escape
                name=(entry['first_name']+' '+entry['last_name']).strip()
                plain=(f'Dear {name},\n\nYour historical {entry["transaction_type"]} payment has been recorded.\n'
                       f'Request: {entry["description"]}\nOriginal request date: {entry["transaction_date"]}\n'
                       f'Amount received: PHP {amount:,.2f}\nPayment date: {pay_date}\n'
                       f'OR Number: {or_number}\nRemaining: PHP {new_remaining:,.2f}\nStatus: {new_status}\n'
                       'Please review your Statement of Account in the Homeowner Portal.')
                html=(' <div style="font-family:Arial,sans-serif;background:#F4F9F4;padding:22px;color:#2D312E">'
                      '<div style="background:#1B4332;color:white;padding:16px">NORTH FAIRWAY HOMES HOMEOWNERS ASSOCIATION INC.</div>'
                      '<h2>Historical Request Fee Payment Confirmed</h2><p>'+escape(plain).replace('\n','<br>')+'</p></div>')
                notification_sender(entry['homeowner_id'],'NFH-HOA | Historical Payment Confirmed',plain,related_type='Historical Payment',related_id=str(receipt_id),dedupe_key='nfh-hpay-'+str(receipt_id),html_body=html)
                delivery='attempted'
            except Exception:
                import logging;logging.exception('Historical payment email failed')
                delivery='failed'
        return jsonify(status='success',receipt_id=receipt_id,remaining=str(new_remaining),payment_status=new_status,email=delivery)
    except ValueError as exc:
        if conn:conn.rollback()
        return error(str(exc))
    except Exception:
        if conn:conn.rollback()
        import logging;logging.exception('Historical payment failed')
        return error('Payment could not be recorded. No partial financial entry was saved.',409)
    finally:
        if conn:conn.close()

def _notify_unpaid_import(homeowner_id,batch_id,items):
    """One post-commit delivery per import batch, using the existing mail helper."""
    if notification_sender is None:
        raise RuntimeError('Existing notification sender is not configured.')
    from html import escape
    total=sum(Decimal(str(x['amount'])) for x in items)
    conn=connection()
    try:
        with conn.cursor() as c:
            c.execute("SELECT first_name,last_name FROM users WHERE id=%s AND role='Homeowner'",(homeowner_id,))
            homeowner=c.fetchone()
    finally: conn.close()
    if not homeowner:raise ValueError('Homeowner not found')
    name=(str(homeowner['first_name'])+' '+str(homeowner['last_name'])).strip()
    lines=[f"{x['category']} | {x['description']} | {x['date']} | PHP {x['amount']}" for x in items]
    body=('Dear '+name+',\n\nUnpaid HOA charges were recorded from your historical Statement of Account.\n\n'
          +'\n'.join(lines)+f'\n\nTotal newly imported unpaid charges: PHP {total:,.2f}'
          +'\nPlease coordinate with the HOA Treasurer for face-to-face cash payment.\n'
          +'Review your recorded charges in the NFH-HOA Homeowner Portal.')
    table=''.join('<tr>'+''.join('<td style="padding:8px;border-bottom:1px solid #ddd">'+escape(str(v))+'</td>' for v in
        (x['category'],x['description'],x['date'],'PHP '+str(x['amount'])))+'</tr>' for x in items)
    html=('<div style="background:#F4F9F4;padding:18px;font-family:Arial,sans-serif;color:#2D312E">'
      '<div style="background:#1B4332;color:white;padding:18px;font-weight:bold">NORTH FAIRWAY HOMES HOMEOWNERS ASSOCIATION INC.</div>'
      '<div style="background:white;padding:20px"><h2 style="color:#1B4332">Notice of Unpaid HOA Charges</h2><p>Dear '
      +escape(name)+',</p><p>Unpaid HOA charges were recorded from the historical Statement of Account reviewed by the Treasurer.</p>'
      '<table style="width:100%;border-collapse:collapse"><thead><tr><th>Type</th><th>Description</th><th>Date</th><th>Amount</th></tr></thead><tbody>'
      +table+'</tbody></table><p><strong>Total newly imported unpaid charges: PHP '+f'{total:,.2f}'+'</strong></p>'
      '<p>Please coordinate with the Treasurer for face-to-face cash payment. Review charges in your Homeowner Portal.</p></div>'
      '<div style="background:#E2EBE2;padding:14px">North Fairway Homes Homeowners Association Inc. — Automated notification.</div></div>')
    return notification_sender(homeowner_id,'NFH-HOA | Notice of Unpaid HOA Charges',body,
        related_type='SOA import',related_id=str(batch_id),dedupe_key='nfh-soa-unpaid-'+str(batch_id),
        important=True,html_body=html)
