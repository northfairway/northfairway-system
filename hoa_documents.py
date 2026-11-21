"""Private PDF library for NFH HOA. Only Admin and authenticated Homeowner may access."""
import os, uuid, hashlib
from pathlib import Path
from flask import Blueprint, request, session, jsonify, current_app, send_file
from werkzeug.utils import secure_filename

bp = Blueprint('hoa_library', __name__)
CATEGORIES = ('HOA Resolutions','HOA Policies and Guidelines','Official Announcements','Memorandums','Community Rules and Regulations','Meeting Minutes','Other HOA Documents')
STATUSES = ('Draft','Published','Unpublished')
MAX_FILE = int(os.getenv('NFH_HOA_DOCUMENT_MAX_BYTES', str(12 * 1024 * 1024)))

def _db():
    # Bound when blueprint registered using existing app database factory.
    return bp.nfh_connection()

def _role(admin=False):
    return bool(session.get('user_id') and (session.get('role') == 'Admin' if admin else session.get('role') in ('Admin','Homeowner')))

def _private_dir():
    p=Path(os.getenv('NFH_PRIVATE_HOA_DOCUMENT_DIR', str(Path(current_app.instance_path)/'hoa_private_documents'))).resolve()
    if p == Path(current_app.static_folder).resolve() or Path(current_app.static_folder).resolve() in p.parents:
        raise RuntimeError('Private document storage cannot be inside the static directory')
    p.mkdir(mode=0o700,parents=True,exist_ok=True)
    return p

def _response(data,code=200): return jsonify(data),code

def _fields(row):
    return {k:(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in row.items() if k not in ('stored_filename','sha256')}

def _upload(file):
    if not file or not file.filename or not file.filename.lower().endswith('.pdf'):
        raise ValueError('Only PDF files are supported')
    content=file.stream.read(MAX_FILE+1)
    if not content or len(content)>MAX_FILE: raise ValueError('Invalid PDF size or exceeds upload limit')
    if not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:]:
        raise ValueError('The uploaded file is not a valid PDF structure')
    # PDF signature checking does not replace malware scanning in production.
    name=uuid.uuid4().hex+'.pdf'; path=_private_dir()/name
    with path.open('xb') as f: f.write(content)
    return name,secure_filename(file.filename)[:220],len(content),hashlib.sha256(content).hexdigest()

def _log(event,identifier):
    try: bp.nfh_audit(session.get('username'),session.get('role'),event,str(identifier),None,None)
    except Exception: current_app.logger.exception('HOA library audit failed for %s',event)

@bp.get('/api/hoa-documents')
def list_documents():
    if not _role(): return _response({'error':'Unauthorized'},403)
    conn=_db()
    try:
        with conn.cursor() as cur:
            if session.get('role')=='Admin':
                cur.execute('SELECT id,title,description,category,resolution_number,resolution_date,original_filename,file_size,status,uploaded_by,created_at,published_at,updated_at FROM hoa_documents ORDER BY created_at DESC')
            else:
                cur.execute("SELECT id,title,description,category,resolution_number,resolution_date,created_at,published_at FROM hoa_documents WHERE status='Published' ORDER BY published_at DESC")
            rows=cur.fetchall()
        return _response({'documents':[_fields(r) for r in rows], 'categories':CATEGORIES})
    finally: conn.close()

@bp.post('/api/hoa-documents')
def create_document():
    if not _role(True): return _response({'error':'Admin required'},403)
    form=request.form; title=form.get('title','').strip()[:200]; category=form.get('category',''); status=form.get('status','Draft')
    if not title or category not in CATEGORIES or status not in ('Draft','Published'): return _response({'error':'Invalid title, category or status'},400)
    file=request.files.get('file')
    try: stored,original,size,digest=_upload(file)
    except ValueError as e: return _response({'error':str(e)},400)
    conn=None; success=False
    try:
        conn=_db()
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO hoa_documents(title,description,category,resolution_number,resolution_date,stored_filename,original_filename,file_size,sha256,status,uploaded_by,published_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,IF(%s='Published',NOW(),NULL))""", (title,form.get('description','').strip()[:2000],category,form.get('resolution_number','').strip()[:100] or None,form.get('resolution_date') or None,stored,original,size,digest,status,session['user_id'],status))
            item=cur.lastrowid
        conn.commit(); success=True
        _log('HOA Document Uploaded',item)
        return _response({'ok':True,'id':item},201)
    finally:
        if conn is not None: conn.close()
        if not success: (_private_dir()/stored).unlink(missing_ok=True)

@bp.post('/api/hoa-documents/<int:doc_id>')
def edit_document(doc_id):
    if not _role(True): return _response({'error':'Admin required'},403)
    form=request.form; conn=_db(); new_file=None
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM hoa_documents WHERE id=%s FOR UPDATE',(doc_id,)); old=cur.fetchone()
            if not old: return _response({'error':'Not found'},404)
            title=form.get('title',old['title']).strip()[:200]; category=form.get('category',old['category']); status=form.get('status',old['status'])
            if not title or category not in CATEGORIES or status not in STATUSES: return _response({'error':'Invalid fields'},400)
            uploaded=request.files.get('file')
            if uploaded and uploaded.filename:
                try: new_file=_upload(uploaded)
                except ValueError as e: return _response({'error':str(e)},400)
            stored,original,size,digest=new_file or (old['stored_filename'],old['original_filename'],old['file_size'],old['sha256'])
            published=old['published_at'] if status=='Published' and old['status']=='Published' else None
            cur.execute("""UPDATE hoa_documents SET title=%s,description=%s,category=%s,resolution_number=%s,resolution_date=%s,stored_filename=%s,original_filename=%s,file_size=%s,sha256=%s,status=%s,published_at=IF(%s='Published',COALESCE(%s,NOW()),NULL),updated_at=NOW() WHERE id=%s""",(title,form.get('description',old['description'] or '')[:2000],category,form.get('resolution_number',old['resolution_number'] or '') or None,form.get('resolution_date') or old['resolution_date'],stored,original,size,digest,status,status,published,doc_id))
        conn.commit()
        if new_file: (_private_dir()/old['stored_filename']).unlink(missing_ok=True)
        _log('HOA Document Updated',doc_id)
        return _response({'ok':True})
    except Exception:
        if new_file: (_private_dir()/new_file[0]).unlink(missing_ok=True)
        raise
    finally: conn.close()

@bp.delete('/api/hoa-documents/<int:doc_id>')
def delete_document(doc_id):
    if not _role(True): return _response({'error':'Admin required'},403)
    conn=_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT stored_filename FROM hoa_documents WHERE id=%s FOR UPDATE',(doc_id,)); row=cur.fetchone()
            if not row: return _response({'error':'Not found'},404)
            cur.execute('DELETE FROM hoa_documents WHERE id=%s',(doc_id,))
        conn.commit(); _log('HOA Document Deleted',doc_id)
        (_private_dir()/row['stored_filename']).unlink(missing_ok=True)
        return _response({'ok':True})
    finally: conn.close()

@bp.get('/api/hoa-documents/<int:doc_id>/view')
def view_document(doc_id):
    if not _role(): return _response({'error':'Unauthorized'},403)
    conn=_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT stored_filename,status FROM hoa_documents WHERE id=%s',(doc_id,)); row=cur.fetchone()
        if not row or (session.get('role')=='Homeowner' and row['status']!='Published'):
            return _response({'error':'Document unavailable'},404)
        path=_private_dir()/row['stored_filename']
        if not path.is_file(): return _response({'error':'Document file unavailable'},404)
        response=send_file(path,mimetype='application/pdf',as_attachment=False,download_name='hoa-document.pdf',conditional=False)
        response.headers['Cache-Control']='private, no-store, max-age=0'; response.headers['Pragma']='no-cache'
        response.headers['X-Content-Type-Options']='nosniff'; response.headers['Content-Security-Policy']="default-src 'none'; sandbox"
        response.headers['Content-Disposition']='inline; filename="hoa-document.pdf"'
        _log('HOA Document Viewed',doc_id)
        return response
    finally: conn.close()
