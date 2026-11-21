"""Treasurer-prepared HOA membership reconciliation; Admin-approved, SOA read-only.

This classification is NOT users.status and never changes login or financial postings.
Requires the two nfh_membership_* tables in the consolidated schema.
"""
import csv
import io
import json
import secrets
import hashlib
import re
import unicodedata
from datetime import datetime
from flask import Blueprint, request, session, jsonify, send_file
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

bp = Blueprint('homeowner_reconciliation', __name__)
connection = None
HEADERS = ['Homeowner_ID','Name','Address','Status']
STAGED = {}

def fail(message, code=400):
    return jsonify(status='error', message=message), code

def authorized(role):
    return session.get('user_id') is not None and session.get('role') == role

def fullname(u):
    return ' '.join(str(u.get(x) or '').strip() for x in ('first_name','middle_name','last_name','suffix') if str(u.get(x) or '').strip())

def address(u):
    # Use the database address exactly; no invented street information.
    return str(u.get('address_line') or '').strip() or ', '.join(x for x in [
        ('Block '+str(u['block'])) if u.get('block') else '',
        ('Lot '+str(u['lot'])) if u.get('lot') else ''] if x)

def status_of(u):
    return u.get('membership_status') or 'Active'

def roster(cur, lock=False):
    cur.execute('''SELECT u.id,u.homeowner_public_id,u.first_name,u.middle_name,u.last_name,u.suffix,
        u.block,u.lot,u.address_line,u.status AS account_status,
        COALESCE(m.status,'Active') AS membership_status
        FROM users u LEFT JOIN nfh_homeowner_membership m ON m.homeowner_id=u.id
        WHERE u.role='Homeowner' AND u.verification_status='Verified'
        ORDER BY u.last_name,u.first_name,u.id''' + (' FOR UPDATE' if lock else ''))
    return cur.fetchall()

@bp.get('/treasurer/membership/template')
def template():
    if not authorized('Treasurer'): return fail('Treasurer access required.',403)
    wb=Workbook();ws=wb.active;ws.title='Homeowner Status';ws.append(HEADERS)
    for c in ws[1]:
        c.font=Font(color='FFFFFF',bold=True)
        c.fill=PatternFill('solid',fgColor='1B4332')
    for col,width in zip('ABCD',(26,38,58,20)):ws.column_dimensions[col].width=width
    ws.freeze_panes='A2';ws.auto_filter.ref='A1:D5001'
    for row in ws.iter_rows(min_row=2,max_row=20,min_col=1,max_col=4):
        for c in row:c.number_format='@'
    dv=DataValidation(type='list',formula1='"Active,Inactive"',allow_blank=False)
    dv.showErrorMessage=True;dv.error='Select Active or Inactive.'
    ws.add_data_validation(dv);dv.add('D2:D5001')
    out=io.BytesIO();wb.save(out);out.seek(0)
    return send_file(out,as_attachment=True,download_name='NFH_Homeowner_Status_Reconciliation.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def parse_file(f):
    if not f or not f.filename:raise ValueError('Choose an Excel or CSV file.')
    raw=f.read(5*1024*1024+1)
    if len(raw)>5*1024*1024:raise ValueError('Maximum file size is 5 MB.')
    if f.filename.lower().endswith('.xlsx'):
        if not raw.startswith(b'PK'):raise ValueError('Invalid Excel file.')
        wb=load_workbook(io.BytesIO(raw),read_only=True,data_only=False)
        try:
            if 'Homeowner Status' not in wb.sheetnames:raise ValueError('Use the system-generated Homeowner Status worksheet.')
            rows=iter(wb['Homeowner Status'].values)
            heads=[str(x or '').strip() for x in next(rows,[])]
            if heads != HEADERS:raise ValueError('Unexpected columns. Download a fresh template.')
            values=[]
            for n,vals in enumerate(rows,2):
                if len(vals)>4 and any(v not in ('',None) for v in vals[4:]):raise ValueError(f'Unexpected number of columns at row {n}.')
                vals=tuple(vals[:4])+tuple([None]*max(0,4-len(vals)))
                if not any(v not in ('',None) for v in vals):continue
                if any(getattr(v,'data_type',None)=='f' for v in vals):raise ValueError(f'Formulas are not allowed (row {n}).')
                values.append((n,dict(zip(HEADERS,vals))))
        finally: wb.close()
    elif f.filename.lower().endswith('.csv'):
        inp=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        if inp.fieldnames!=HEADERS:raise ValueError('Unexpected columns. Download a fresh template.')
        values=[(n,r) for n,r in enumerate(inp,2) if any(v not in ('',None) for v in r.values())]
    else:raise ValueError('Only .xlsx or .csv is supported.')
    if not 1<=len(values)<=5000:raise ValueError('File must contain 1–5,000 homeowner records.')
    return values,hashlib.sha256(raw).hexdigest()

def normalize_id(value):
    # Preserve the exact entered ID for storage, normalize only for comparisons.
    return re.sub(r'\s+', '', str(value or '')).casefold()

def identity(value):
    return unicodedata.normalize('NFC', re.sub(r'\s+', ' ', str(value or '').strip())).casefold()

def pending_by_id(cur):
    cur.execute("SELECT * FROM nfh_membership_pending_matches")
    return {normalize_id(r['imported_homeowner_id']):r for r in cur.fetchall()}

INVALID_NAME_MESSAGE = ("Invalid Homeowner Name: The Name field must contain letters "
    "and valid name characters only. Numbers, unsupported symbols, and special "
    "characters are not allowed.")


def normalize_imported_name(value):
    """Collapse whitespace without altering letters, spelling, or punctuation."""
    return re.sub(r'\s+', ' ', str(value if value is not None else '').strip())


def valid_homeowner_name(value):
    """Accept Unicode letters and combining marks, plus safe name separators.

    Unicode NFKC is intentionally NOT applied: original spelling is preserved.
    Reject every non-name symbol, number, control, emoji, and invisible format char.
    Combining marks must follow a Unicode letter/mark, never punctuation.
    """
    raw = str(value if value is not None else '')
    # Do not silently sanitize tabs/newlines/control or format characters.
    if any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs', 'Co', 'Cn') for c in raw):
        return False
    name = normalize_imported_name(raw)
    if not name or not any(unicodedata.category(c).startswith('L') for c in name):
        return False
    previous_letter = False
    for char in name:
        category = unicodedata.category(char)
        if category.startswith('L'):
            previous_letter = True
        elif category.startswith('M'):
            if not previous_letter:
                return False
        elif char in " -'’.":
            previous_letter = False
        else:
            return False
    return True


NAME_MISMATCH_MESSAGE = ("Homeowner Name Mismatch: The entered Homeowner_ID exists, "
    "but the imported homeowner name does not match the registered account. "
    "Please verify the information before reconciliation.")


def validate(entries, users, pending=None):
    """Compare exact normalized public ID and full registered name, never fuzzy-match.

    Review records are not eligible for membership changes. The registration
    identity is authoritative; imported values are preserved without mutation.
    """
    known={normalize_id(u.get('homeowner_public_id')):u for u in users if u.get('homeowner_public_id')}
    pending=pending or {};seen=set();results=[]
    for row,r in entries:
        raw=r.get('Homeowner_ID')
        hid=str(raw if raw is not None else '').strip()
        key=normalize_id(hid)
        u=known.get(key);old_pending=pending.get(key)
        proposed=str(r.get('Status') or '').strip().title()
        raw_name=str(r.get('Name') if r.get('Name') is not None else '')
        name=normalize_imported_name(raw_name);addr=str(r.get('Address') or '').strip()
        registered_name=fullname(u) if u else ''
        reasons=[]
        if not key or not name or not addr:reasons.append('Homeowner ID, Name and Address are required')
        duplicate_in_file=key in seen
        if duplicate_in_file:reasons.append('Duplicate Homeowner ID detected in uploaded file — Reject')
        seen.add(key)
        if not valid_homeowner_name(raw_name):reasons.append(INVALID_NAME_MESSAGE)
        if proposed not in ('Active','Inactive'):reasons.append('Enter Active or Inactive')
        name_mismatch=bool(u and identity(name)!=identity(registered_name))
        address_mismatch=bool(u and identity(addr)!=identity(address(u)))
        pending_name_conflict=bool(old_pending and identity(name)!=identity(old_pending['imported_name']))
        pending_address_conflict=bool(old_pending and identity(addr)!=identity(old_pending['imported_address']))
        old=status_of(u) if u else ''
        if duplicate_in_file:
            state='Duplicate';validation_result='Duplicate — Reject'
        elif reasons:
            state='Invalid';validation_result='Invalid'
        elif name_mismatch:
            state='Requires Review';validation_result='Requires Review — Name Mismatch'
            reasons.append(NAME_MISMATCH_MESSAGE)
        elif pending_name_conflict and not u:
            state='Requires Review';validation_result='Requires Review — Pending Name Conflict'
            reasons.append('Pending Name Conflict: This Homeowner_ID has a different imported name in the pending registry. Authorized identity review required; no duplicate record was created.')
        elif address_mismatch or (pending_address_conflict and not u):
            state='Requires Review';validation_result='Requires Review — Address Mismatch'
            reasons.append('Homeowner Address Mismatch: Address differs from the registered or pending homeowner record; authorized review required.')
        elif old_pending and not u:
            state='Unchanged';validation_result='Existing Pending Record — No duplicate'
            if proposed != old_pending['imported_status']:
                state='Requires Review';validation_result='Requires Review — Pending Status Conflict'
                reasons.append('Existing pending record has a different status; manual review required.')
        elif u:
            state='Unchanged' if old==proposed else 'Ready to Update'
            validation_result='Valid — Existing Homeowner' if state=='Ready to Update' else 'Valid — Existing Homeowner (Unchanged)'
        else:
            state='Valid — Pending Account Match';validation_result='Pending Account Match'
        results.append(dict(row=row,homeowner_id=hid,name=name,original_imported_name=raw_name,registered_name=registered_name or 'No Existing Account',
            address=addr,current=old,proposed=proposed,state=state,validation_result=validation_result,
            message='; '.join(reasons),user_id=u['id'] if u else None,
            existing_pending_id=old_pending['id'] if old_pending else None))
    return results

@bp.post('/treasurer/membership/preview')
def preview():
    if not authorized('Treasurer'):return fail('Treasurer access required.',403)
    try:
        values,digest=parse_file(request.files.get('file'))
        conn=connection()
        try:
            with conn.cursor() as cur:
                users=roster(cur); pending=pending_by_id(cur)
        finally:conn.close()
        results=validate(values,users,pending)
        token=secrets.token_urlsafe(32)
        if len(STAGED)>40:STAGED.clear()
        STAGED[token]={'uid':session['user_id'],'when':datetime.now().timestamp(), 'rows':values,'digest':digest,
                       'filename':request.files['file'].filename}
        return jsonify(status='success',token=token,results=results,
            counts={key:sum(x['state']==key for x in results) for key in ('Ready to Update','Unchanged','Invalid','Duplicate','Requires Review','Valid — Pending Account Match')})
    except (ValueError,UnicodeError) as exc:return fail(str(exc))

@bp.post('/treasurer/membership/submit')
def submit():
    if not authorized('Treasurer'):return fail('Treasurer access required.',403)
    token=(request.get_json(silent=True) or {}).get('token')
    info=STAGED.get(token)
    if not info or info['uid']!=session['user_id'] or datetime.now().timestamp()-info['when']>900:
        return fail('Preview expired. Validate the file again.')
    conn=None
    try:
        conn=connection(autocommit=False)
        with conn.cursor() as cur:
            users=roster(cur,lock=True)
            pending=pending_by_id(cur)
            results=validate(info['rows'],users,pending)
            if any(r['state'] in ('Invalid','Duplicate') for r in results):
                conn.rollback();return fail('The registry or file changed. Correct all invalid rows and preview again.',409)
            changes=[r for r in results if r['state']=='Ready to Update']
            unmatched=[r for r in results if r['state']=='Valid — Pending Account Match']
            reviews=[r for r in results if r['state']=='Requires Review']
            new_reviews=[r for r in reviews if not r['existing_pending_id']]
            if not changes and not unmatched and not reviews:
                conn.rollback();return fail('No new membership changes or unmatched records to submit.')
            cur.execute('''INSERT INTO nfh_membership_import_batches
                (source_filename,file_hash,submitted_by,total_rows,changed_rows,unchanged_rows,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                (info['filename'][:255],info['digest'],session['user_id'],len(results),len(changes),len(results)-len(changes),'Pending Approval' if changes else 'Approved'))
            batch_id=cur.lastrowid
            for r in changes:
                cur.execute('''INSERT INTO nfh_membership_import_changes
                    (batch_id,homeowner_id,homeowner_public_id,name_snapshot,address_snapshot,previous_status,proposed_status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                    (batch_id,r['user_id'],r['homeowner_id'],r['name'],r['address'],r['current'],r['proposed']))
            for r in unmatched:
                cur.execute('''INSERT INTO nfh_membership_pending_matches
                    (imported_homeowner_id,normalized_homeowner_id,imported_name,imported_address,imported_status,
                     reconciliation_status,import_batch_id,imported_by)
                    VALUES (%s,%s,%s,%s,%s,'Pending Account Match',%s,%s)''',
                    (r['homeowner_id'],normalize_id(r['homeowner_id']),r['name'],r['address'],r['proposed'],batch_id,session['user_id']))
            # Retain mismatched existing-ID records for review without updating membership.
            # A conflicting existing pending row stays unchanged (unique normalized ID).
            for r in new_reviews:
                cur.execute('''INSERT INTO nfh_membership_pending_matches
                    (imported_homeowner_id,normalized_homeowner_id,imported_name,imported_address,imported_status,
                     reconciliation_status,import_batch_id,imported_by,validation_remarks)
                    VALUES (%s,%s,%s,%s,%s,'Requires Review',%s,%s,%s)''',
                    (r['homeowner_id'],normalize_id(r['homeowner_id']),r['name'],r['address'],r['proposed'],
                     batch_id,session['user_id'],r['message'][:600]))
            # Audit conflicting incoming records without overwriting the existing pending identity.
            for r in reviews:
                cur.execute('''INSERT INTO audit_logs(username,role,action,item,new_val)
                    VALUES (%s,'Treasurer','Review membership identity conflict',%s,%s)''',
                    (str(session.get('username') or session['user_id']),r['homeowner_id'][:64],
                     json.dumps({'row':r['row'],'name':r['name'],'original_imported_name':r['original_imported_name'],'address':r['address'],
                                 'status':r['proposed'],'result':r['validation_result'],
                                 'pending_id':r['existing_pending_id']})))
            cur.execute('''INSERT INTO audit_logs(username,role,action,item,new_val)
                VALUES (%s,'Treasurer','Submit membership reconciliation',%s,%s)''',
                (str(session.get('username') or session['user_id']),str(batch_id),json.dumps({'changes':len(changes),'unmatched':len(unmatched),'requires_review':len(reviews)})))
        conn.commit();STAGED.pop(token,None)
        return jsonify(status='success',batch_id=batch_id,submitted=len(changes),pending=len(unmatched),review=len(reviews),message='Validated existing-account changes submitted for Admin approval; unmatched and review records retained. No account access or financial records were changed.')
    except Exception:
        if conn:conn.rollback()
        return fail('Unable to submit reconciliation. Check database migration and audit tables.',503)
    finally:
        if conn:conn.close()

@bp.get('/admin/membership/pending')
def pending():
    if not authorized('Admin'):return fail('Admin access required.',403)
    conn=connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''SELECT b.id,b.source_filename,b.submitted_at,b.changed_rows,b.unchanged_rows,
                u.username AS submitted_by FROM nfh_membership_import_batches b
                JOIN users u ON u.id=b.submitted_by WHERE b.status='Pending Approval'
                ORDER BY b.submitted_at DESC LIMIT 100''')
            batches=cur.fetchall()
            for b in batches:
                cur.execute('''SELECT homeowner_public_id,name_snapshot,address_snapshot,previous_status,proposed_status
                    FROM nfh_membership_import_changes WHERE batch_id=%s ORDER BY id''',(b['id'],))
                b['changes']=cur.fetchall()
        return jsonify(status='success',batches=batches, default_status='Active')
    finally:conn.close()

@bp.post('/admin/membership/decide/<int:batch_id>')
def decide(batch_id):
    if not authorized('Admin'):return fail('Admin access required.',403)
    data=request.get_json(silent=True) or {};action=data.get('action')
    if action not in ('approve','reject'):return fail('Choose approve or reject.')
    conn=None
    try:
        conn=connection(autocommit=False)
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM nfh_membership_import_batches WHERE id=%s FOR UPDATE',(batch_id,))
            b=cur.fetchone()
            if not b or b['status']!='Pending Approval':return fail('Batch is no longer pending.',409)
            cur.execute('SELECT * FROM nfh_membership_import_changes WHERE batch_id=%s ORDER BY homeowner_id FOR UPDATE',(batch_id,))
            changes=cur.fetchall()
            if action=='approve':
                for c in changes:
                    cur.execute('''SELECT u.id,u.homeowner_public_id,u.first_name,u.middle_name,u.last_name,u.suffix,
                        u.address_line,u.block,u.lot,u.verification_status,
                        COALESCE(m.status,'Active') AS membership_status
                        FROM users u LEFT JOIN nfh_homeowner_membership m ON m.homeowner_id=u.id
                        WHERE u.id=%s AND u.role='Homeowner' FOR UPDATE''',(c['homeowner_id'],))
                    u=cur.fetchone()
                    if not u or not valid_homeowner_name(c['name_snapshot']) or u['verification_status']!='Verified' or normalize_id(u['homeowner_public_id'])!=normalize_id(c['homeowner_public_id']) or identity(fullname(u))!=identity(c['name_snapshot']) or identity(address(u))!=identity(c['address_snapshot']) or status_of(u)!=c['previous_status']:
                        conn.rollback();return fail('Homeowner records changed since submission. Reject and re-import a fresh roster.',409)
                for c in changes:
                    cur.execute('''INSERT INTO nfh_homeowner_membership(homeowner_id,status,updated_by)
                        VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE status=VALUES(status),updated_by=VALUES(updated_by),updated_at=CURRENT_TIMESTAMP''',
                        (c['homeowner_id'],c['proposed_status'],session['user_id']))
            cur.execute('''UPDATE nfh_membership_import_batches SET status=%s,reviewed_by=%s,reviewed_at=CURRENT_TIMESTAMP
                WHERE id=%s''',('Approved' if action=='approve' else 'Rejected',session['user_id'],batch_id))
            cur.execute('''INSERT INTO audit_logs(username,role,action,item,new_val)
                VALUES (%s,'Admin',%s,%s,%s)''',
                (str(session.get('username') or session['user_id']), 'Approve membership reconciliation' if action=='approve' else 'Reject membership reconciliation',str(batch_id),json.dumps({'changed':len(changes)})))
        conn.commit()
        return jsonify(status='success',message='Batch '+('approved' if action=='approve' else 'rejected')+'. System account status and historical SOA financial records were not modified.')
    except Exception:
        if conn:conn.rollback()
        return fail('Unable to review membership import. Check the database migration.',503)
    finally:
        if conn:conn.close()

def reconcile_future_account(cur, account_id, reviewer_id=None):
    """Call inside the same transaction that verifies/updates the account."""
    cur.execute('''SELECT id,homeowner_public_id,first_name,middle_name,last_name,suffix,block,lot,address_line,
                  verification_status FROM users WHERE id=%s AND role='Homeowner' FOR UPDATE''',(account_id,))
    u=cur.fetchone()
    if not u or u['verification_status']!='Verified':return 'Not Verified'
    key=normalize_id(u.get('homeowner_public_id'))
    if not key:return 'No Homeowner ID'
    cur.execute('''SELECT * FROM nfh_membership_pending_matches WHERE normalized_homeowner_id=%s
                  AND reconciliation_status IN ('Pending Account Match','Requires Review') FOR UPDATE''',(key,))
    pending=cur.fetchone()
    if not pending:return 'No Match'
    if not valid_homeowner_name(pending['imported_name']) or identity(pending['imported_name'])!=identity(fullname(u)) or identity(pending['imported_address'])!=identity(address(u)):
        cur.execute('''UPDATE nfh_membership_pending_matches SET reconciliation_status='Requires Review',
                      validation_remarks='Name character validation failed or imported Name/Address differs; manual verification required' WHERE id=%s''',(pending['id'],))
        return 'Requires Review'
    cur.execute('''INSERT INTO nfh_homeowner_membership(homeowner_id,status,updated_by) VALUES (%s,%s,%s)
                  ON DUPLICATE KEY UPDATE status=VALUES(status),updated_by=VALUES(updated_by),updated_at=CURRENT_TIMESTAMP''',
                (account_id,pending['imported_status'],reviewer_id))
    cur.execute('''UPDATE nfh_membership_pending_matches SET reconciliation_status='Reconciled',matched_homeowner_id=%s,
                  reconciled_at=NOW(),reconciled_by=%s,validation_remarks='Verified ID, name and address matched'
                  WHERE id=%s''',(account_id,reviewer_id,pending['id']))
    return 'Reconciled'

@bp.get('/treasurer/membership/records')
def pending_records():
    if not authorized('Treasurer') and not authorized('Admin'):return fail('Officer access required.',403)
    status=(request.args.get('status') or 'All').strip()
    if status not in ('All','Pending Account Match','Reconciled','Requires Review'):return fail('Invalid filter')
    search=(request.args.get('q') or '').strip()[:100]
    conn=connection()
    try:
        with conn.cursor() as cur:
            sql='''SELECT p.id,p.imported_homeowner_id,p.imported_name,p.imported_address,p.imported_status,
                       p.reconciliation_status,p.matched_homeowner_id,p.imported_at,p.reconciled_at,p.validation_remarks
                       FROM nfh_membership_pending_matches p WHERE 1=1'''
            args=[]
            if status!='All':sql+=' AND p.reconciliation_status=%s';args.append(status)
            if search:sql+=' AND (p.imported_homeowner_id LIKE %s OR p.imported_name LIKE %s OR p.imported_address LIKE %s)';args.extend(['%'+search+'%']*3)
            sql+=' ORDER BY p.imported_at DESC LIMIT 300'
            cur.execute(sql,tuple(args));rows=cur.fetchall()
        return jsonify(status='success',records=rows)
    finally:conn.close()

@bp.post('/admin/membership/match/<int:pending_id>')
def manual_match(pending_id):
    if not authorized('Admin'):return fail('Administrator access required.',403)
    data=request.get_json(silent=True) or {}
    try: account_id=int(data.get('homeowner_account_id'))
    except (ValueError,TypeError):return fail('Provide a verified homeowner account ID.')
    if data.get('confirm') is not True:return fail('Explicit confirmation is required.')
    conn=connection(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute('''SELECT * FROM nfh_membership_pending_matches WHERE id=%s FOR UPDATE''',(pending_id,))
            p=cur.fetchone()
            if not p or p['reconciliation_status']=='Reconciled':conn.rollback();return fail('Pending record not available.',409)
            cur.execute('''SELECT id,homeowner_public_id,first_name,middle_name,last_name,suffix,block,lot,address_line,
                          verification_status FROM users WHERE id=%s AND role='Homeowner' FOR UPDATE''',(account_id,))
            u=cur.fetchone()
            if not u or u['verification_status']!='Verified':conn.rollback();return fail('Verified homeowner account required.',409)
            if not valid_homeowner_name(p['imported_name']):
                conn.rollback();return fail(INVALID_NAME_MESSAGE,409)
            if normalize_id(p['imported_homeowner_id'])!=normalize_id(u['homeowner_public_id']):
                conn.rollback();return fail('Homeowner IDs differ. Manual matching cannot bypass ID verification.',409)
            if identity(p['imported_name'])!=identity(fullname(u)) or identity(p['imported_address'])!=identity(address(u)):
                if not data.get('identity_reviewed'):
                    conn.rollback();return fail('Name/Address mismatch. Review the identity and confirm identity_reviewed.',409)
            cur.execute('''SELECT id FROM nfh_membership_pending_matches WHERE matched_homeowner_id=%s AND id<>%s LIMIT 1''',(account_id,pending_id))
            if cur.fetchone():conn.rollback();return fail('This account is already reconciled to another record.',409)
            cur.execute('''INSERT INTO nfh_homeowner_membership(homeowner_id,status,updated_by) VALUES (%s,%s,%s)
                          ON DUPLICATE KEY UPDATE status=VALUES(status),updated_by=VALUES(updated_by),updated_at=CURRENT_TIMESTAMP''',
                        (account_id,p['imported_status'],session['user_id']))
            cur.execute('''UPDATE nfh_membership_pending_matches SET reconciliation_status='Reconciled',matched_homeowner_id=%s,
                          reconciled_at=NOW(),reconciled_by=%s,validation_remarks='Administrator manually verified matching ID and identity'
                          WHERE id=%s''',(account_id,session['user_id'],pending_id))
            cur.execute('''INSERT INTO audit_logs(username,role,action,item,new_val) VALUES (%s,'Admin','Manual membership reconciliation',%s,%s)''',
                        (str(session.get('username') or session['user_id']),str(pending_id),json.dumps({'homeowner_account_id':account_id})))
        conn.commit();return jsonify(status='success',message='Reconciled with verified homeowner account; financial history unchanged.')
    except Exception:
        conn.rollback();return fail('Unable to reconcile. Confirm the database migration is installed.',503)
    finally:conn.close()

@bp.get('/admin/membership/report.pdf')
def report():
    if not authorized('Admin'):return fail('Admin access required.',403)
    category=(request.args.get('status') or 'All').title()
    if category not in ('All','Active','Inactive'):return fail('Invalid filter.')
    conn=connection()
    try:
        with conn.cursor() as cur: all_users=roster(cur)
    finally:conn.close()
    users=[u for u in all_users if category=='All' or status_of(u)==category]
    from reportlab.lib.pagesizes import landscape, LETTER
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
    from xml.sax.saxutils import escape
    out=io.BytesIO();doc=SimpleDocTemplate(out,pagesize=landscape(LETTER),leftMargin=35,rightMargin=35,topMargin=36,bottomMargin=42)
    styles=getSampleStyleSheet()
    parts=[Paragraph('NORTH FAIRWAY HOMES HOMEOWNERS ASSOCIATION',styles['Title']),
        Paragraph('Homeowner HOA Membership Status Report',styles['Heading2']),
        Paragraph('Filter: '+category+' | Active: '+str(sum(status_of(u)=='Active' for u in all_users))+' | Inactive: '+str(sum(status_of(u)=='Inactive' for u in all_users))+' | Displayed: '+str(len(users)),styles['Normal']),
        Paragraph('Membership classification is separate from system account access. Historical SOA records are retained.',styles['Normal']),Spacer(1,12)]
    safe=lambda x:Paragraph(escape(str(x or '-')),styles['BodyText'])
    cells=[['Homeowner ID','Full Name','Registered Address','HOA Membership','Account Access']]
    for u in users:cells.append([safe(u['homeowner_public_id']),safe(fullname(u)),safe(address(u)),safe(status_of(u)),safe(u['account_status'])])
    if not users:cells.append([safe('No matching homeowners'), '', '', '', ''])
    table=Table(cells,colWidths=[105,150,255,100,85],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1B4332')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,0),9),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),7),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#D8E2D8'))]))
    parts.append(table)
    def footer(canvas,document):
        canvas.setFont('Helvetica',8);canvas.drawRightString(750,20,'Page '+str(document.page))
    doc.build(parts,onFirstPage=footer,onLaterPages=footer);out.seek(0)
    return send_file(out,as_attachment=True,download_name='NFH_HOA_Membership_Status_'+category+'.pdf',mimetype='application/pdf')
