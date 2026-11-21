"""Additional NFH features. Apply migration_20261022.sql before use."""
import os, uuid
from datetime import datetime
from io import BytesIO
from flask import Blueprint, request, session, jsonify, send_file, abort, current_app
from werkzeug.utils import secure_filename
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import inch

bp=Blueprint('nfh_extensions',__name__,url_prefix='/api/nfh')

def init_extensions(db_factory):
    global connect
    connect=db_factory
    return bp

def authorized(*roles):
    return session.get('user_id') and session.get('role') in roles

def require(*roles):
    if not authorized(*roles): abort(403)

def query(sql,args=(),one=False):
    conn=connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql,args)
            return cur.fetchone() if one else cur.fetchall()
    finally: conn.close()

def write(sql,args=()):
    conn=connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute(sql,args)
            result=cur.lastrowid
        conn.commit()
        return result
    except Exception:
        conn.rollback(); raise
    finally: conn.close()

def payload(): return request.get_json(silent=True) or {}

@bp.route('/admin/delinquency-settings', methods=['GET','POST'])
def delinquency_settings():
    require('Admin')
    keys=('delinquency_email_enabled','delinquency_unpaid_months',
          'delinquency_email_frequency_value','delinquency_email_frequency_unit',
          'delinquency_email_config_updated_at','delinquency_email_config_updated_by')
    if request.method=='GET':
        rows=query('SELECT setting_key,setting_value FROM hoa_settings WHERE setting_key IN ('+
                   ','.join(['%s']*len(keys))+')',keys)
        data={r['setting_key']:r['setting_value'] for r in rows}
        return jsonify(enabled=data.get(keys[0],'1')=='1',threshold=int(data.get(keys[1]) or 5),
                       frequency=int(data.get(keys[2]) or 3),unit=data.get(keys[3]) or 'months',
                       updated_at=data.get(keys[4]),updated_by=data.get(keys[5]))
    data=payload()
    try:
        enabled=data['enabled']
        if not isinstance(enabled,bool):raise ValueError()
        threshold=int(data['threshold']);frequency=int(data['frequency']);unit=data['unit']
        if not 1<=threshold<=120 or not 1<=frequency<=365 or unit not in ('days','weeks','months'):
            raise ValueError()
    except (KeyError,ValueError,TypeError):
        return jsonify(error='Invalid settings: threshold 1–120; frequency 1–365; unit days/weeks/months'),400
    new={keys[0]:'1' if enabled else '0',keys[1]:str(threshold),keys[2]:str(frequency),keys[3]:unit}
    conn=connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT setting_key,setting_value FROM hoa_settings WHERE setting_key IN (%s,%s,%s,%s) FOR UPDATE',tuple(new))
            previous={r['setting_key']:r['setting_value'] for r in cur.fetchall()}
            for key,value in new.items():
                cur.execute('INSERT INTO hoa_settings(setting_key,setting_value) VALUES(%s,%s) ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)',(key,value))
            cur.execute("INSERT INTO hoa_settings(setting_key,setting_value) VALUES(%s,DATE_FORMAT(NOW(),'%%Y-%%m-%%d %%H:%%i:%%s')) ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)",(keys[4],))
            cur.execute('INSERT INTO hoa_settings(setting_key,setting_value) VALUES(%s,%s) ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)',(keys[5],str(session['user_id'])))
            cur.execute('SELECT username FROM users WHERE id=%s',(session['user_id'],))
            actor=cur.fetchone()
            import json
            cur.execute('INSERT INTO audit_logs(username,role,action,item,prev_val,new_val) VALUES(%s,%s,%s,%s,%s,%s)',
                        ((actor or {}).get('username','admin'),'Admin','Delinquency Reminder Settings Updated','hoa_settings',json.dumps(previous),json.dumps(new)))
        conn.commit()
        return jsonify(status='saved')
    except Exception:
        conn.rollback();current_app.logger.exception('Delinquency configuration failed')
        return jsonify(error='Unable to save settings'),500
    finally:conn.close()

@bp.get('/overview')
def overview():
    require('Homeowner','Treasurer','Secretary','President','Vice President','Board Director','Admin')
    if session['role']=='Homeowner':
        uid=session['user_id']
        counts=query("SELECT COUNT(*) total,SUM(status='Issued / Completed') completed FROM requests WHERE user_id=%s",(uid,),True)
        dues=query("SELECT COUNT(*) months,COALESCE(SUM(amount),0) balance FROM monthly_dues WHERE user_id=%s AND status='Unpaid'",(uid,),True)
        return jsonify(requests=counts,dues=dues)
    return jsonify(requests=query('SELECT status,COUNT(*) total FROM requests GROUP BY status'),concerns=query('SELECT status,COUNT(*) total FROM general_concerns GROUP BY status'))

@bp.route('/feedback',methods=['GET','POST'])
def feedback():
    require('Homeowner','Admin')
    if request.method=='GET':
        if session['role']=='Homeowner': return jsonify(query('SELECT id,rating,category,comments,created_at,reviewed_at FROM system_feedback WHERE user_id=%s ORDER BY id DESC',(session['user_id'],)))
        return jsonify(query('SELECT f.*,CONCAT(u.first_name," ",u.last_name) homeowner FROM system_feedback f JOIN users u ON u.id=f.user_id ORDER BY f.id DESC LIMIT 200'))
    require('Homeowner')
    p=payload(); rating=p.get('rating'); category=str(p.get('category','')).strip()[:80]; comments=str(p.get('comments','')).strip()
    if str(rating) not in ('1','2','3','4','5') or not category or not 1<=len(comments)<=3000: return jsonify(error='Rating 1–5, category, and comments are required'),400
    id=write('INSERT INTO system_feedback(user_id,rating,category,comments) VALUES(%s,%s,%s,%s)',(session['user_id'],int(rating),category,comments))
    return jsonify(id=id,status='Submitted'),201

@bp.post('/feedback/<int:fid>/review')
def review_feedback(fid):
    require('Admin')
    write('UPDATE system_feedback SET reviewed_at=NOW(),reviewed_by=%s WHERE id=%s',(session['user_id'],fid))
    return jsonify(status='Reviewed')

# Shared concern queue. All writes, history, alerts and audit entries commit atomically.
CONCERN_STATUSES=('Submitted','Acknowledged','In Progress','Resolved','Closed')
OFFICER_ROLES=('Secretary','Treasurer','President','Vice President','Board Director','Admin')

def concern_audit(cur, action, cid, previous, updated, details):
    cur.execute('INSERT INTO audit_logs(username,role,action,item,prev_val,new_val) VALUES(%s,%s,%s,%s,%s,%s)',
                (session.get('username') or str(session['user_id']),session['role'],action,f'Concern #{cid}',previous, f'{updated}: {details[:300]}'))

@bp.get('/concerns/officer/search')
def officer_concern_search():
    require(*OFFICER_ROLES)
    term=(request.args.get('q') or '').strip()[:120]
    state=(request.args.get('status') or '').strip()
    if state and state not in CONCERN_STATUSES:return jsonify(error='Invalid concern status'),400
    sort=request.args.get('sort','desc')
    if sort not in ('asc','desc'):return jsonify(error='Invalid sort order'),400
    page=max(1,min(10000,request.args.get('page',1,type=int) or 1))
    where=['1=1'];args=[]
    # Match the existing officer concern-list permission scope; no expansion.
    if term:
        pattern='%'+term.replace('\\','\\\\').replace('%',r'\%').replace('_',r'\_')+'%'
        where.append("(CONCAT_WS(' ',u.first_name,u.last_name) LIKE %s OR u.homeowner_public_id LIKE %s OR c.subject LIKE %s OR c.category LIKE %s OR CAST(c.id AS CHAR) LIKE %s)")
        args.extend([pattern]*5)
    if state:where.append('c.status=%s');args.append(state)
    base=' FROM general_concerns c JOIN users u ON u.id=c.user_id WHERE '+' AND '.join(where)
    conn=connect()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n'+base,args);total=cur.fetchone()['n']
            cur.execute("SELECT c.*,CONCAT_WS(' ',u.first_name,u.last_name) AS homeowner_name,u.homeowner_public_id"+base+
                       ' ORDER BY c.created_at '+sort.upper()+',c.id '+sort.upper()+' LIMIT %s OFFSET %s',args+[20,(page-1)*20]);items=cur.fetchall()
            cur.execute('SELECT c.status,COUNT(*) AS n FROM general_concerns c JOIN users u ON u.id=c.user_id GROUP BY c.status')
            counts={r['status']:r['n'] for r in cur.fetchall()}
        for item in items:
            for key in ('created_at','updated_at'):
                if item.get(key) and hasattr(item[key],'isoformat'):item[key]=item[key].isoformat(sep=' ',timespec='minutes')
        return jsonify(items=items,total=total,page=page,page_size=20,counts={'Total':sum(counts.values()),**counts})
    finally:conn.close()

@bp.route('/concerns',methods=['GET','POST'])
def concerns():
    require('Homeowner',*OFFICER_ROLES)
    if request.method=='GET':
        if session['role']=='Homeowner':
            return jsonify(query('SELECT c.*,CONCAT(u.first_name," ",u.last_name) homeowner_name FROM general_concerns c JOIN users u ON u.id=c.user_id WHERE c.user_id=%s ORDER BY c.updated_at DESC,c.id DESC',(session['user_id'],)))
        return jsonify(query('SELECT c.*,CONCAT(u.first_name," ",u.last_name) homeowner_name FROM general_concerns c JOIN users u ON u.id=c.user_id ORDER BY c.updated_at DESC,c.id DESC LIMIT 500'))
    require('Homeowner')
    p=payload();category=str(p.get('category','General')).strip()[:80];subject=str(p.get('subject','')).strip()[:200];description=str(p.get('description','')).strip()[:4000]
    if not subject or not description:return jsonify(error='Subject and description required'),400
    role='Treasurer' if category.lower() in ('dues','payment','balance','financial') else 'Secretary'
    conn=connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO general_concerns(user_id,assigned_role,category,subject,description,status) VALUES(%s,%s,%s,%s,%s,%s)',(session['user_id'],role,category,subject,description,'Submitted'))
            cid=cur.lastrowid
            concern_audit(cur,'Concern Submitted',cid,'','Submitted',subject)
        conn.commit()
        return jsonify(id=cid,status='Submitted'),201
    except Exception:
        conn.rollback();current_app.logger.exception('Concern submission failed');return jsonify(error='Unable to save concern'),500
    finally:conn.close()

@bp.get('/concerns/<int:cid>/history')
def concern_history(cid):
    require('Homeowner',*OFFICER_ROLES)
    c=query('SELECT user_id FROM general_concerns WHERE id=%s',(cid,),True)
    if not c:abort(404)
    if session['role']=='Homeowner' and c['user_id']!=session['user_id']:abort(403)
    return jsonify(query('SELECT h.id,h.previous_status,h.new_status,h.message,h.created_at,CONCAT(u.first_name," ",u.last_name) officer_name,u.role officer_role FROM general_concern_history h JOIN users u ON u.id=h.officer_id WHERE h.concern_id=%s ORDER BY h.id',(cid,)))

@bp.post('/concerns/<int:cid>/respond')
def respond_concern(cid):
    require(*OFFICER_ROLES)
    p=payload();status=str(p.get('status','')).strip();message=str(p.get('response','')).strip()[:4000]
    if status not in CONCERN_STATUSES or not message:return jsonify(error='A valid status and response are required'),400
    try:expected=int(p.get('version',-1))
    except (TypeError,ValueError):return jsonify(error='Valid concern version required'),400
    conn=connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT status,version,user_id FROM general_concerns WHERE id=%s FOR UPDATE',(cid,))
            c=cur.fetchone()
            if not c:
                conn.rollback();return jsonify(error='Concern not found'),404
            if c['version']!=expected:
                conn.rollback();return jsonify(error='Concern changed; reload before responding'),409
            cur.execute('UPDATE general_concerns SET officer_response=%s,status=%s,version=version+1 WHERE id=%s',(message,status,cid))
            cur.execute('INSERT INTO general_concern_history(concern_id,officer_id,previous_status,new_status,message) VALUES(%s,%s,%s,%s,%s)',(cid,session['user_id'],c['status'],status,message))
            action='Concern Resolved' if status=='Resolved' else 'Concern Closed' if status=='Closed' else 'Concern Acknowledged' if status=='Acknowledged' else 'Concern Marked In Progress' if status=='In Progress' else 'Officer Response Added'
            concern_audit(cur,action,cid,c['status'],status,message)
            cur.execute('INSERT INTO alerts(user_id,text,unread) VALUES(%s,%s,1)',(c['user_id'],f'Concern #{cid} updated to {status}. An HOA officer has responded.'))
            cur.execute('INSERT INTO notification_log(user_id,channel,subject,body,related_type,related_id,dedupe_key,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(c['user_id'],'in_app',f'Concern #{cid} update',message,'general_concern',str(cid),f'concern-{cid}-v{expected+1}','sent'))
        conn.commit()
        return jsonify(status=status,version=expected+1)
    except Exception:
        conn.rollback();current_app.logger.exception('Concern update failed');return jsonify(error='Unable to save concern update'),500
    finally:conn.close()

@bp.route('/soa',methods=['GET','POST'])
def soa():
    require('Homeowner','Treasurer','Admin','President','Vice President','Board Director')
    if request.method=='GET':
        if session['role']=='Homeowner': return jsonify(query('SELECT * FROM soa_requests WHERE user_id=%s ORDER BY id DESC',(session['user_id'],)))
        return jsonify(query('SELECT * FROM soa_requests ORDER BY id DESC LIMIT 200'))
    require('Homeowner') # deliberately no monthly-dues gate
    p=payload()
    try:
        start=datetime.strptime(p.get('period_start',''),'%Y-%m-%d').date(); end=datetime.strptime(p.get('period_end',''),'%Y-%m-%d').date()
    except ValueError: return jsonify(error='Valid start and end dates required'),400
    purpose=str(p.get('purpose','')).strip()[:250]
    if start>end or not purpose: return jsonify(error='Invalid period or purpose'),400
    service=query("SELECT fee,status FROM service_types WHERE service_name='Statement of Account'",one=True)
    if not service or service['status']!='Active' or service['fee'] is None or service['fee']<=0:
        return jsonify(error='SOA fee has not been configured and activated by an authorized officer'),409
    id=write('INSERT INTO soa_requests(user_id,purpose,period_start,period_end) VALUES(%s,%s,%s,%s)',(session['user_id'],purpose,start,end))
    return jsonify(id=id,status='Submitted'),201

@bp.post('/soa/<int:sid>/review')
def soa_review(sid):
    require('Treasurer')
    status=payload().get('status')
    if status not in ('Under Review','Approved','Rejected'): return jsonify(error='Invalid status'),400
    write('UPDATE soa_requests SET status=%s,reviewed_by=%s,reviewed_at=NOW() WHERE id=%s',(status,session['user_id'],sid))
    return jsonify(status=status)

@bp.get('/soa/<int:sid>/pdf')
def soa_pdf(sid):
    require('Treasurer','Admin','President','Vice President','Board Director','Homeowner')
    s=query('SELECT s.*,u.first_name,u.last_name,u.block,u.lot FROM soa_requests s JOIN users u ON u.id=s.user_id WHERE s.id=%s',(sid,),True)
    if not s: abort(404)
    if session['role']=='Homeowner' and s['user_id']!=session['user_id']: abort(403)
    if s['status']!='Approved': abort(403)
    dues=query('SELECT due_month,amount,status FROM monthly_dues WHERE user_id=%s AND due_month BETWEEN %s AND %s ORDER BY due_month',(s['user_id'],s['period_start'],s['period_end']))
    buf=BytesIO(); doc=SimpleDocTemplate(buf); styles=getSampleStyleSheet(); items=[Paragraph('NORTH FAIRWAY HOMES HOMEOWNERS ASSOCIATION INC.',styles['Heading2']),Paragraph('Statement of Account — Verified Monthly Dues Ledger',styles['Heading3']),Paragraph(f"Homeowner: {s['first_name']} {s['last_name']} | Block {s['block']} Lot {s['lot']}",styles['Normal']),Paragraph(f"Period: {s['period_start']} to {s['period_end']}",styles['Normal']),Spacer(1,12)]
    from xml.sax.saxutils import escape
    balance=0
    for d in dues:
        if d['status']=='Unpaid': balance+=d['amount']
        items.append(Paragraph(escape(f"{d['due_month']} — PHP {d['amount']} — {d['status']}"),styles['Normal']))
    items.append(Spacer(1,12)); items.append(Paragraph(f'Outstanding dues in period: PHP {balance:.2f}',styles['Heading3']))
    items.append(Paragraph('This statement reflects ledger entries, not a complete cash-reconciliation certificate. Verify payment receipts with the Treasurer.',styles['Normal']))
    doc.build(items);buf.seek(0)
    return send_file(buf,mimetype='application/pdf',as_attachment=True,download_name=f'NFH_SOA_{sid}.pdf')

@bp.get('/soa/service')
def soa_service():
    require('Homeowner','Treasurer','Admin','President','Vice President','Board Director')
    return jsonify(query("SELECT service_name,fee,status FROM service_types WHERE service_name='Statement of Account'",one=True) or {})

@bp.route('/chatbot/faqs',methods=['GET','POST'])
def chatbot_faqs():
    require('Admin','Homeowner','Treasurer','Secretary','President','Vice President','Board Director')
    if request.method=='GET':
        if session['role']=='Admin': return jsonify(query('SELECT * FROM chatbot_faq ORDER BY category,id'))
        return jsonify(query('SELECT id,category,question FROM chatbot_faq WHERE is_active=1 ORDER BY category,id'))
    require('Admin')
    p=payload(); question=str(p.get('question','')).strip()[:500]; answer=str(p.get('answer','')).strip()[:4000]
    if not question or not answer:return jsonify(error='Question and answer required'),400
    id=write('INSERT INTO chatbot_faq(category,question,answer,is_active,keywords) VALUES(%s,%s,%s,%s,%s)',(str(p.get('category','General'))[:80],question,answer,1 if p.get('is_active',True) else 0,str(p.get('keywords',''))[:2000]))
    return jsonify(id=id),201

@bp.route('/chatbot/faqs/<int:fid>',methods=['PUT','DELETE'])
def chatbot_faq_edit(fid):
    require('Admin')
    if request.method=='DELETE':
        write('UPDATE chatbot_faq SET is_active=0 WHERE id=%s',(fid,));return jsonify(status='Deactivated')
    p=payload();question=str(p.get('question','')).strip()[:500];answer=str(p.get('answer','')).strip()[:4000]
    if not question or not answer:return jsonify(error='Question and answer required'),400
    write('UPDATE chatbot_faq SET category=%s,question=%s,answer=%s,is_active=%s,keywords=%s WHERE id=%s',(str(p.get('category','General'))[:80],question,answer,1 if p.get('is_active',True) else 0,str(p.get('keywords',''))[:2000],fid))
    return jsonify(status='Updated')

@bp.route('/chatbot/fallback',methods=['GET','PUT'])
def chatbot_fallback():
    require('Admin')
    if request.method=='GET':return jsonify(query("SELECT setting_value FROM hoa_settings WHERE setting_key='chatbot_fallback'",one=True) or {})
    answer=str(payload().get('answer','')).strip()[:4000]
    if not answer:return jsonify(error='Fallback answer required'),400
    write("INSERT INTO hoa_settings(setting_key,setting_value) VALUES('chatbot_fallback',%s) ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)",(answer,))
    return jsonify(status='Updated')

@bp.route('/chatbot/ai-settings', methods=['GET', 'PUT'])
def chatbot_ai_settings():
    require('Admin')
    from nfh_ai_assistant import CONFIG_KEYS, settings_from_rows, validate_settings
    if request.method == 'GET':
        result = settings_from_rows(query('SELECT setting_key, setting_value FROM hoa_settings WHERE setting_key IN (' + ','.join(['%s']*len(CONFIG_KEYS)) + ')', tuple(CONFIG_KEYS.values())))
        import os
        result['configured'] = bool(os.getenv('GEMINI_API_KEY')) if result['provider']=='gemini' else False
        return jsonify(result)
    try:
        new = validate_settings(payload())
    except (ValueError,TypeError) as exc:
        return jsonify(error=str(exc)),400
    conn=connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            for name,key in CONFIG_KEYS.items():
                value=new[name]
                cur.execute('INSERT INTO hoa_settings(setting_key,setting_value) VALUES(%s,%s) ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)',(key,'1' if value is True else '0' if value is False else value))
            cur.execute('INSERT INTO audit_logs(username,role,action,item,prev_val,new_val) VALUES(%s,%s,%s,%s,%s,%s)',
                        (str(session.get('user_id')),'Admin','Chatbot AI Settings Updated','hoa_settings',None,__import__('json').dumps(new)))
        conn.commit()
    except Exception:
        conn.rollback();current_app.logger.exception('AI settings save failed')
        return jsonify(error='Unable to save AI settings'),500
    finally:conn.close()
    return jsonify(status='Updated')

@bp.post('/chatbot/gemini-connection-test')
def chatbot_gemini_connection_test():
    require('Admin')
    from nfh_ai_assistant import ALLOWED_MODELS, gemini_connection_test
    model=str(payload().get('model',''))
    if model not in ALLOWED_MODELS['gemini']:
        return jsonify(error='Unsupported Gemini model'),400
    try:
        gemini_connection_test(model)
        return jsonify(status='connected',provider='gemini',model=model)
    except Exception:
        # Do not leak provider exceptions, request data, or API credentials.
        current_app.logger.warning('Gemini connection test failed')
        return jsonify(error='Live Gemini connection failed. Check the server API key, model availability and free-tier quota.'),503

@bp.route('/chatbot', methods=['GET', 'POST'])
def chatbot():
    require('Homeowner','Treasurer','Secretary','Admin','President','Vice President','Board Director')
    from chatbot_matching import match
    from chatbot_profanity import warning_for
    from nfh_ai_assistant import CONFIG_KEYS, settings_from_rows, generate, rate_allowed, UNKNOWN
    body=payload() if request.method=='POST' else {}
    question=str(body.get('q','') if request.method=='POST' else request.args.get('q','')).strip()
    history=body.get('history',[])
    if not isinstance(history,list) or len(history)>6 or any(not isinstance(x,dict) or x.get('role') not in ('user','assistant') or not isinstance(x.get('content'),str) or len(x['content'])>500 for x in history):return jsonify(error='Invalid conversation history'),400
    if not question:return jsonify(error='Enter a question.'),400
    if len(question)>500:return jsonify(error='Question is too long (maximum 500 characters).'),400
    warning=warning_for(question)
    if warning:return jsonify(answer=warning,matched=False,source='moderation')
    if not rate_allowed(session['user_id']):return jsonify(error='Please wait before sending another question.'),429
    try:
        rows=query('SELECT id,category,question,answer,keywords FROM chatbot_faq WHERE is_active=1')
        config=settings_from_rows(query('SELECT setting_key,setting_value FROM hoa_settings WHERE setting_key IN (' + ','.join(['%s']*len(CONFIG_KEYS)) + ')',tuple(CONFIG_KEYS.values())))
        if config['enabled']:
            try:
                answer=generate(question,rows,config,history=history)
                if answer:return jsonify(answer=answer['answer'],matched=True,source='ai',faq_ids=answer['source_ids'])
            except Exception:
                current_app.logger.warning('AI provider unavailable; using verified FAQ fallback')
            if not config['fallback']:
                return jsonify(answer=UNKNOWN,matched=False,source='unavailable')
        result=match(question,rows)
        if result['type']=='match':
            return jsonify(answer=result['row']['answer'],matched=True,faq_id=result['row']['id'],source='faq')
        if result['type']=='clarify':
            return jsonify(answer='I found several possible topics. Which question did you mean?',matched=False,clarify=result['options'],source='faq')
        fallback=query("SELECT setting_value FROM hoa_settings WHERE setting_key='chatbot_fallback'",one=True)
        return jsonify(answer=(fallback or {}).get('setting_value') or UNKNOWN,matched=False,source='faq')
    except Exception:
        current_app.logger.exception('Chatbot database request failed')
        return jsonify(error='The HOA assistant is temporarily unavailable. Please try again later.'),503

@bp.get('/resolutions')
def resolutions():
    require('Homeowner','Treasurer','Secretary','Admin','President','Vice President','Board Director')
    if session['role']=='Homeowner': return jsonify(query("SELECT id,resolution_number,title,description,category,approval_date FROM hoa_resolutions WHERE status='Published' ORDER BY approval_date DESC"))
    return jsonify(query('SELECT id,resolution_number,title,description,category,approval_date,status FROM hoa_resolutions ORDER BY id DESC'))

@bp.post('/resolutions')
def add_resolution():
    require('Admin','Secretary','President','Vice President','Board Director')
    f=request.files.get('file'); number=request.form.get('number','').strip()[:100]; title=request.form.get('title','').strip()[:250]
    try: date=datetime.strptime(request.form.get('approval_date',''),'%Y-%m-%d').date()
    except ValueError: return jsonify(error='Invalid approval date'),400
    if not f or not number or not title: return jsonify(error='File, number and title required'),400
    filename=secure_filename(f.filename or '')
    if filename.rsplit('.',1)[-1].lower()!='pdf': return jsonify(error='PDF files only'),400
    data=f.read(5*1024*1024+1)
    if len(data)>5*1024*1024 or not data.startswith(b'%PDF-'): return jsonify(error='Invalid PDF or file too large'),400
    directory=os.path.join(current_app.instance_path,'hoa_resolutions');os.makedirs(directory,exist_ok=True)
    stored=uuid.uuid4().hex+'.pdf';open(os.path.join(directory,stored),'wb').write(data)
    id=write('INSERT INTO hoa_resolutions(resolution_number,title,description,category,approval_date,file_path,uploaded_by) VALUES(%s,%s,%s,%s,%s,%s,%s)',(number,title,request.form.get('description','')[:2000],request.form.get('category','General')[:80],date,stored,session['user_id']))
    return jsonify(id=id,status='Draft'),201

@bp.post('/resolutions/<int:rid>/status')
def resolution_status(rid):
    require('Admin','President','Vice President','Board Director')
    status=payload().get('status')
    if status not in ('Draft','Published','Archived'): return jsonify(error='Invalid status'),400
    write('UPDATE hoa_resolutions SET status=%s WHERE id=%s',(status,rid));return jsonify(status=status)

@bp.get('/resolutions/<int:rid>/file')
def resolution_file(rid):
    require('Homeowner','Treasurer','Secretary','Admin','President','Vice President','Board Director')
    r=query('SELECT file_path,status FROM hoa_resolutions WHERE id=%s',(rid,),True)
    if not r or (session['role']=='Homeowner' and r['status']!='Published'): abort(404)
    from flask import send_from_directory
    return send_from_directory(os.path.join(current_app.instance_path,'hoa_resolutions'),r['file_path'],as_attachment=True)

@bp.get('/delinquency')
def delinquency():
    require('Treasurer','Admin','President','Vice President','Board Director')
    threshold=query("SELECT setting_value FROM hoa_settings WHERE setting_key='delinquency_unpaid_months'",one=True)
    return jsonify(threshold=int(threshold['setting_value']) if threshold else 5,accounts=query("SELECT u.id,CONCAT(u.first_name,' ',u.last_name) homeowner,COUNT(d.id) unpaid_months,COALESCE(SUM(d.amount),0) outstanding FROM users u LEFT JOIN monthly_dues d ON d.user_id=u.id AND d.status='Unpaid' WHERE u.role='Homeowner' GROUP BY u.id HAVING unpaid_months>0 ORDER BY unpaid_months DESC"))

@bp.post('/delinquency/threshold')
def threshold():
    require('Admin','Treasurer','President')
    try: value=int(payload().get('months'))
    except (ValueError,TypeError): return jsonify(error='Invalid threshold'),400
    if not 1<=value<=60:return jsonify(error='Threshold must be 1–60'),400
    write("INSERT INTO hoa_settings(setting_key,setting_value) VALUES('delinquency_unpaid_months',%s) ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)",(str(value),))
    return jsonify(months=value)
