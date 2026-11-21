import os
import re
import random
import string
import json
import html
import hashlib
import time
import secrets
import hmac
import smtplib
import socket
import ssl
from email.utils import parseaddr
import unicodedata
from pathlib import Path
from io import BytesIO
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_file
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import pymysql
import pymysql.cursors
from openpyxl import load_workbook, Workbook

from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, Image, KeepTogether)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

app = Flask(__name__)
_configured_secret = os.getenv('SECRET_KEY')
app.secret_key = _configured_secret or secrets.token_hex(32)
if not _configured_secret:
    app.logger.warning('SECRET_KEY is not set. Using an ephemeral development key; set SECRET_KEY in .env before deployment.')

# Safe defaults for the session cookie. Secure cookies remain opt-in locally so
# the project still works over http://127.0.0.1 during capstone development.
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() in {'1','true','yes','on'}

# ---------------------------------------------------------------------------
# Session inactivity security
# ---------------------------------------------------------------------------
# Production defaults: 30 minutes of inactivity with a warning during the
# final 5 minutes. Environment overrides are intentionally limited to timing
# values so local testing can use shorter intervals without changing code.
SESSION_INACTIVITY_MINUTES = max(1, int(os.getenv('SESSION_INACTIVITY_MINUTES', '30')))
SESSION_WARNING_MINUTES = max(1, int(os.getenv('SESSION_WARNING_MINUTES', '5')))
if SESSION_WARNING_MINUTES >= SESSION_INACTIVITY_MINUTES:
    SESSION_WARNING_MINUTES = max(1, SESSION_INACTIVITY_MINUTES - 1)

SESSION_INACTIVITY_SECONDS = SESSION_INACTIVITY_MINUTES * 60
SESSION_WARNING_SECONDS = SESSION_WARNING_MINUTES * 60
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=SESSION_INACTIVITY_SECONDS)
# Background requests must not refresh the cookie simply because a request was
# made. Real activity updates the session explicitly below.
app.config['SESSION_REFRESH_EACH_REQUEST'] = False

# Endpoints that run automatically in the background and therefore must never
# extend an authenticated session.
SESSION_BACKGROUND_ENDPOINTS = {'live_metrics'}


UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads')
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

def _detected_image_ext(file_storage):
    """Validate uploaded image content using file signatures, without a new dependency."""
    pos=file_storage.stream.tell()
    head=file_storage.stream.read(16)
    file_storage.stream.seek(pos)
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if head.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    return None

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
SIGNATURE_FOLDER = os.path.join(app.instance_path, 'protected_uploads', 'esignatures')
SIGNATURE_SNAPSHOT_FOLDER = os.path.join(app.instance_path, 'protected_uploads', 'signature_snapshots')
os.makedirs(SIGNATURE_FOLDER, exist_ok=True)
os.makedirs(SIGNATURE_SNAPSHOT_FOLDER, exist_ok=True)
app.config['SIGNATURE_FOLDER'] = SIGNATURE_FOLDER
app.config['SIGNATURE_SNAPSHOT_FOLDER'] = SIGNATURE_SNAPSHOT_FOLDER
IMPORT_STAGING_FOLDER = os.path.join(app.instance_path, 'import_staging')
os.makedirs(IMPORT_STAGING_FOLDER, exist_ok=True)
app.config['IMPORT_STAGING_FOLDER'] = IMPORT_STAGING_FOLDER
MAX_IMPORT_FILE_SIZE = 10 * 1024 * 1024  # 10MB

EXECUTIVE_ROLES = ['President', 'Vice President', 'Board Director']
OFFICER_ROLES = ['Secretary', 'Treasurer', *EXECUTIVE_ROLES, 'Admin']
HOA_NAME = "NORTH FAIRWAY HOMES HOMEOWNERS ASSOCIATION INC."
HOA_ADDRESS = "Sitio Pastol, Brgy. Muzon West, City of San Jose del Monte, Bulacan 3023"
HOA_REG = "HLURB Registration Number: NTR-20986-R | TIN No: 486-778-923-000"

# Temporary homeowner self-correction is concern-driven and time-limited.
REQUEST_EDIT_ACCESS_MINUTES = (30, 60, 120, 240)
TERMINAL_REQUEST_STATUSES = {'Rejected','Cancelled','Issued / Completed'}



DOCUMENT_SIGNATURE_RULES = {
    'cert-improvement': ['Secretary','President'],
    'proof-residency': ['Secretary','President'],
    'move-in': ['Secretary','President'],
    'move-out': ['Secretary','President'],
    'cert-membership': ['Secretary','President'],
    'gate-pass': ['Treasurer','President'],
    'vehicle-sticker': [],
    'tenant-form': [],
}

# Human-readable labels used by the Admin template editor. The database keeps
# compact internal tokens, while administrators edit familiar field names.
TEMPLATE_FIELD_LABELS = {
    'homeowner': 'Homeowner Full Name',
    'block': 'Block Number',
    'lot': 'Lot Number',
    'address': 'Complete Address',
    'mobile': 'Contact Number',
    'email': 'Email Address',
    'request_id': 'Request ID',
    'request_type': 'Request Type',
    'purpose': 'Purpose of Request',
    'request_date': 'Request Date',
    'issue_date': 'Issue Date',
    'materials': 'Materials',
    'permit_no': 'Construction Permit Number',
    'vehicle_plate': 'Vehicle Plate Number',
    'vehicle_brand': 'Vehicle Brand',
    'vehicle_model': 'Vehicle Model',
    'vehicle_color': 'Vehicle Color',
    'vehicle_type': 'Vehicle Type',
    'secretary_name': 'Secretary Name',
    'treasurer_name': 'Treasurer Name',
    'president_name': 'President Name',
}

def template_text_to_display(text):
    out=str(text or '')
    for token,label in TEMPLATE_FIELD_LABELS.items():
        out=out.replace('{'+token+'}', '['+label+']')
    return out

def template_text_to_internal(text):
    out=str(text or '')
    for token,label in TEMPLATE_FIELD_LABELS.items():
        out=out.replace('['+label+']', '{'+token+'}')
    return out

def _signature_roles(template):
    raw=(template or {}).get('required_signatures') if template else None
    if raw:
        roles=[x.strip() for x in str(raw).split(',') if x.strip()]
        if roles: return roles
    return DOCUMENT_SIGNATURE_RULES.get((template or {}).get('template_key'), ['Secretary','President'])

def _current_role_signature(cursor, role):
    cursor.execute("""SELECT id, CONCAT(first_name,' ',last_name) AS full_name, e_signature_path
                      FROM users WHERE role=%s AND status='Active' ORDER BY id ASC LIMIT 1""", (role,))
    return cursor.fetchone()

def _signature_abs(path_value, snapshot=False):
    if not path_value: return None
    base=app.config['SIGNATURE_SNAPSHOT_FOLDER'] if snapshot else app.config['SIGNATURE_FOLDER']
    p=os.path.join(base, os.path.basename(path_value))
    return p if os.path.isfile(p) else None

def snapshot_request_signatures(cursor, request_id, template):
    """Copy current authorized e-signatures at issuance so historical PDFs never change."""
    import shutil
    for role in _signature_roles(template):
        cursor.execute("SELECT id FROM request_signature_snapshots WHERE request_id=%s AND role=%s", (request_id, role))
        if cursor.fetchone(): continue
        officer=_current_role_signature(cursor, role)
        if not officer or not officer.get('e_signature_path'): continue
        src=_signature_abs(officer.get('e_signature_path'))
        if not src: continue
        ext=os.path.splitext(src)[1].lower() or '.png'
        safe_role=re.sub(r'[^A-Za-z0-9]+','_',role).strip('_').lower()
        filename=secure_filename(f"{request_id}_{safe_role}_{secrets.token_hex(12)}{ext}")
        dst=os.path.join(app.config['SIGNATURE_SNAPSHOT_FOLDER'], filename)
        shutil.copy2(src,dst)
        cursor.execute("""INSERT INTO request_signature_snapshots
            (request_id,role,officer_id,officer_name,signature_path,captured_at) VALUES (%s,%s,%s,%s,%s,NOW())""",
            (request_id,role,officer['id'],officer['full_name'],filename))

def request_signature_assets(cursor, request_id, template):
    result={}
    roles=_signature_roles(template)
    for role in roles:
        cursor.execute("SELECT officer_name,signature_path FROM request_signature_snapshots WHERE request_id=%s AND role=%s", (request_id,role))
        snap=cursor.fetchone()
        if snap:
            result[role]={'name':snap.get('officer_name') or role,'path':_signature_abs(snap.get('signature_path'), snapshot=True)}
            continue
        officer=_current_role_signature(cursor, role)
        result[role]={'name':(officer or {}).get('full_name') or f'NFH-HOA {role}', 'path':_signature_abs((officer or {}).get('e_signature_path'))}
    return result

# ---------------------------------------------------------------------------
# Unicode-safe text and person-name helpers
# ---------------------------------------------------------------------------
def normalize_unicode_text(value):
    """Preserve the user's spelling while normalizing equivalent Unicode forms."""
    return unicodedata.normalize('NFC', str(value or '').strip())


def valid_person_name(value, *, required=True, max_length=150):
    """Accept Filipino/Unicode names, spaces, hyphens, apostrophes, and periods."""
    value = normalize_unicode_text(value)
    if not value:
        return not required
    if len(value) > max_length or not any(ch.isalpha() for ch in value):
        return False
    allowed_punctuation = {" ", "-", "'", "’", "."}
    return all(ch.isalpha() or ch in allowed_punctuation for ch in value)


def normalize_search_text(value):
    """Accent-insensitive comparison key without changing stored/displayed text."""
    value = normalize_unicode_text(value).casefold()
    return ''.join(ch for ch in unicodedata.normalize('NFD', value)
                   if unicodedata.category(ch) != 'Mn')


# ---------------------------------------------------------------------------
# Request-type-specific approval routing
# ---------------------------------------------------------------------------
# Keep these names aligned with the request titles currently emitted by the
# Homeowner request forms. These sets are the single backend source of truth
# for who may perform the initial checking stage.
SECRETARY_FIRST_REQUEST_TYPES = {
    'Certificate of Improvement',
    'Proof of Residency',
    'Move-in Gate Pass',
    'Move-out Gate Pass',
    'Certificate of Membership',
}
TREASURER_FIRST_REQUEST_TYPES = {
    'Statement of Account',
    'Gate Pass',
}
SHARED_INITIAL_CHECK_REQUEST_TYPES = {
    'Vehicle Sticker Application',
    'Renters/Tenants Information Form',
}


def get_service_config(cursor, request_type, active_only=False):
    """Return the authoritative service/workflow configuration for a request type."""
    sql = """SELECT id, service_name, category, fee, initial_reviewer,
                    requires_executive, requires_payment, requires_dues_clearance, purpose_required,
                    release_role, form_template, description, status
             FROM service_types WHERE service_name=%s"""
    params = [request_type]
    if active_only:
        sql += " AND status='Active'"
    cursor.execute(sql, tuple(params))
    return cursor.fetchone()


def service_reviewer_roles(config, request_type=None):
    if request_type == 'Statement of Account' or (config and config.get('service_name') == 'Statement of Account'):
        return {'Treasurer'}
    if config:
        reviewer = config.get('initial_reviewer')
        if reviewer == 'Treasurer':
            return {'Treasurer'}
        if reviewer == 'Shared':
            return {'Secretary', 'Treasurer'}
        return {'Secretary'}
    if request_type in SECRETARY_FIRST_REQUEST_TYPES:
        return {'Secretary'}
    if request_type in TREASURER_FIRST_REQUEST_TYPES:
        return {'Treasurer'}
    if request_type in SHARED_INITIAL_CHECK_REQUEST_TYPES:
        return {'Secretary', 'Treasurer'}
    return {'Secretary'}


def initial_checker_roles(request_type):
    # Administrator-managed configuration is the primary source of truth.
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            config = get_service_config(cursor, request_type, active_only=True)
        if config:
            return service_reviewer_roles(config, request_type)
    except Exception:
        # This compatibility fallback lets an older database start long enough
        # to run migrate.sql without breaking legacy request routing.
        pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    return service_reviewer_roles(None, request_type)


def release_roles_for_request(config, assigned_officer=None):
    """Resolve which operational role may release/issue a configured service."""
    if config and config.get('service_name') == 'Statement of Account':
        return {'Treasurer'}
    if not config:
        return {'Secretary'}
    release_role = config.get('release_role') or 'Secretary'
    if release_role == 'Treasurer':
        return {'Treasurer'}
    if release_role == 'Initial Reviewer':
        if assigned_officer in {'Secretary', 'Treasurer'}:
            return {assigned_officer}
        return service_reviewer_roles(config, config.get('service_name'))
    return {'Secretary'}


def role_can_initial_check(role, request_type, assigned_officer=None):
    allowed = initial_checker_roles(request_type)
    if role not in allowed:
        return False
    # A dynamically configured Shared service can initially be seen by either
    # authorized reviewer. Once assigned, keep it with the same checker so the
    # request does not bounce between Secretary and Treasurer.
    if len(allowed) > 1 and assigned_officer in {'Secretary', 'Treasurer'}:
        return role == assigned_officer
    return True


def request_is_check_actionable(req, role):
    return (
        req.get('status') in {'Submitted', 'Under Review'} and
        role_can_initial_check(role, req.get('request_type'), req.get('assigned_officer'))
    )


def _request_edit_access_active(req):
    expires = (req or {}).get('edit_access_expires_at')
    if not expires:
        return False
    if isinstance(expires, str):
        try:
            expires = datetime.fromisoformat(expires)
        except ValueError:
            return False
    return expires > datetime.now() and (req or {}).get('status') not in TERMINAL_REQUEST_STATUSES


def _expire_edit_access_for_request(request_id):
    """Lazily close an expired grant and record it once in request/audit history."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""SELECT id,status,edit_access_expires_at,edit_access_expired_at,edit_access_granted_by
                              FROM requests WHERE id=%s""", (request_id,))
            row = cursor.fetchone()
            if not row or not row.get('edit_access_expires_at') or row.get('edit_access_expired_at'):
                return False
            expires = row['edit_access_expires_at']
            if expires >= datetime.now():
                return False
            cursor.execute("UPDATE requests SET edit_access_expired_at=NOW() WHERE id=%s AND edit_access_expired_at IS NULL", (request_id,))
        if cursor.rowcount:
            deadline = expires.strftime('%Y-%m-%d %H:%M') if hasattr(expires, 'strftime') else str(expires)
            record_request_history(request_id, 'Temporary Edit Access Expired', row.get('status'), row.get('status'),
                                   f'Homeowner edit access expired at {deadline}.', 'System', 'System')
            log_audit_action('System','System','Temporary Edit Access Expired',request_id,
                             row.get('edit_access_granted_by') or 'Granted', deadline)
            return True
        return False
    finally:
        conn.close()


def _request_review_access_allowed(req, role, user_id, service=None):
    if not req:
        return False
    if role == 'Homeowner':
        return req.get('user_id') == user_id
    if role == 'Admin':
        return True
    if role in EXECUTIVE_ROLES:
        return req.get('status') == 'Pending Executive Approval' or bool(req.get('executive_decided_at'))
    if role in {'Secretary','Treasurer'}:
        allowed = service_reviewer_roles(service, req.get('request_type'))
        release_roles = release_roles_for_request(service, req.get('assigned_officer'))
        return (role in allowed or role in release_roles or req.get('assigned_officer') == role)
    return False



# ---------------------------------------------------------------------------
# Inactivity enforcement and shared UI configuration
# ---------------------------------------------------------------------------
def _session_expired_response():
    session.clear()
    if request.path.startswith('/api/') or request.headers.get('Accept', '').lower().find('application/json') >= 0:
        response = jsonify({
            'status': 'error',
            'message': 'Your session expired after 30 minutes of inactivity. Please sign in again.',
            'session_expired': True,
        })
        response.status_code = 401
        response.headers['X-Session-Expired'] = '1'
        return response
    return redirect(url_for('register_page', session='expired'))


@app.before_request
def enforce_session_inactivity():
    """Expire authenticated sessions after 30 minutes without real activity.

    Automatic live-metric polling is checked for expiration but intentionally
    does not refresh last_activity. Normal page/API actions do refresh it, so
    server-side enforcement still works when JavaScript is unavailable.
    """
    if request.endpoint == 'static' or 'user_id' not in session:
        return None

    now = time.time()
    last_activity = float(session.get('last_activity', now))
    if now - last_activity >= SESSION_INACTIVITY_SECONDS:
        return _session_expired_response()

    if request.endpoint not in SESSION_BACKGROUND_ENDPOINTS and request.endpoint != 'session_keepalive':
        session['last_activity'] = now
        session.permanent = True
        session.modified = True
    return None


def _get_csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
        session.modified = True
    return token


@app.context_processor
def inject_session_timeout_config():
    return {
        'session_timeout_seconds': SESSION_INACTIVITY_SECONDS,
        'session_warning_seconds': SESSION_WARNING_SECONDS,
        'csrf_token': _get_csrf_token(),
    }


@app.before_request
def enforce_active_account_status():
    """Immediately revoke authenticated access for accounts deactivated by Admin.

    Login already checks account status. This additional server-side check prevents an
    already-open browser session from continuing to use protected routes after the
    account is deactivated.
    """
    if request.endpoint == 'static' or 'user_id' not in session:
        return None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT status, role FROM users WHERE id=%s", (session.get('user_id'),))
            current = cursor.fetchone()
        conn.close()
        if not current or current.get('status') != 'Active':
            session.clear()
            if request.path.startswith('/api/') or 'application/json' in request.headers.get('Accept', '').lower():
                response = jsonify({
                    'status': 'error',
                    'message': 'This account is inactive. Please contact the NFH-HOA office.',
                    'account_inactive': True,
                })
                response.status_code = 403
                return response
            flash('This account is inactive. Please contact the NFH-HOA office.', 'warning')
            return redirect(url_for('register_page'))
    except Exception:
        # Do not hide a database outage behind a misleading deactivation message.
        app.logger.exception('Unable to verify active account status for session user %s', session.get('user_id'))
    return None


@app.before_request
def enforce_csrf_for_authenticated_changes():
    """Protect authenticated state-changing requests without adding a dependency.

    Browser forms receive the token through static/csrf.js, and same-origin fetch
    calls receive it through the same helper. Authentication/bootstrap endpoints
    remain usable before a user session exists.
    """
    if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'} or 'user_id' not in session:
        return None
    if request.endpoint in {'session_keepalive'}:
        return None
    expected = session.get('_csrf_token') or ''
    supplied = request.headers.get('X-CSRF-Token') or request.form.get('_csrf_token') or ''
    if expected and supplied and secrets.compare_digest(expected, supplied):
        return None
    if request.path.startswith('/api/') or 'application/json' in request.headers.get('Accept', '').lower():
        return jsonify({'status': 'error', 'message': 'Security token expired. Refresh the page and try again.'}), 400
    flash('Your security token expired. Please refresh the page and try again.', 'error')
    return redirect(request.referrer or _role_home_url(session.get('role')))


@app.route('/api/session/keepalive', methods=['POST'])
def session_keepalive():
    if 'user_id' not in session:
        response = jsonify({'status': 'error', 'message': 'Unauthorized', 'session_expired': True})
        response.status_code = 401
        response.headers['X-Session-Expired'] = '1'
        return response
    now = time.time()
    session['last_activity'] = now
    session.permanent = True
    session.modified = True
    return jsonify({
        'status': 'success',
        'expires_in': SESSION_INACTIVITY_SECONDS,
        'server_time': int(now),
    })


# ---------------------------------------------------------------------------
# Jinja filter
# ---------------------------------------------------------------------------
@app.template_filter('format_details')
def format_details(details):
    if not details:
        return 'None'
    try:
        parsed = json.loads(details) if isinstance(details, str) else details
        if isinstance(parsed, dict):
            items = []
            for k, v in parsed.items():
                if k == 'vehicles' and isinstance(v, list):
                    items.append(f"Vehicles: {len(v)}")
                else:
                    items.append(f"{k.replace('_', ' ').title()}: {v}")
            return ', '.join(items)
    except Exception:
        pass
    return str(details)


# ---------------------------------------------------------------------------
# Database configuration
# ---------------------------------------------------------------------------
DB_HOST = os.getenv('MYSQL_HOST', 'localhost')
DB_USER = os.getenv('MYSQL_USER', 'root')
DB_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
DB_NAME = os.getenv('MYSQL_DB', 'northfairwayportal')
DB_PORT = int(os.getenv('MYSQL_PORT', 3306))

def _mail_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {'true', '1', 'yes', 'on'}

app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com').strip()
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', '587'))
app.config['MAIL_USE_TLS'] = _mail_bool('MAIL_USE_TLS', True)
app.config['MAIL_USE_SSL'] = _mail_bool('MAIL_USE_SSL', False)
app.config['MAIL_USERNAME'] = (os.getenv('MAIL_USERNAME') or '').strip()
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD') or ''
app.config['MAIL_DEFAULT_SENDER'] = (os.getenv('MAIL_DEFAULT_SENDER') or app.config['MAIL_USERNAME']).strip()
app.config['MAIL_TIMEOUT'] = max(3, int(os.getenv('MAIL_TIMEOUT', '15')))
DEV_SHOW_OTP = False  # Do not disclose registration verification codes via HTTP/logs.


def _validate_mail_settings():
    cfg = app.config
    if cfg['MAIL_USE_TLS'] and cfg['MAIL_USE_SSL']:
        raise ValueError('MAIL_USE_TLS and MAIL_USE_SSL cannot both be enabled')
    if not 1 <= cfg['MAIL_PORT'] <= 65535:
        raise ValueError('Invalid MAIL_PORT')
    if cfg['MAIL_PORT'] == 465 and not cfg['MAIL_USE_SSL']:
        raise ValueError('SMTP port 465 requires MAIL_USE_SSL=True')
    if cfg['MAIL_PORT'] == 587 and not cfg['MAIL_USE_TLS']:
        raise ValueError('SMTP port 587 requires MAIL_USE_TLS=True')
    if not (cfg['MAIL_SERVER'] and cfg['MAIL_USERNAME'] and cfg['MAIL_PASSWORD']):
        raise ValueError('SMTP host, username, or password is missing')
    sender = cfg['MAIL_DEFAULT_SENDER']
    if not sender or parseaddr(sender)[1].count('@') != 1:
        raise ValueError('MAIL_DEFAULT_SENDER must be a valid email address')


def _send_system_message(message, purpose):
    """Never log recipients, messages, codes or credentials; propagate classified exceptions."""
    try:
        _validate_mail_settings()
    except ValueError:
        app.logger.error('Mail %s failed: mail configuration invalid or incomplete', purpose)
        raise
    try:
        mail.send(message)
    except smtplib.SMTPAuthenticationError:
        app.logger.error('Mail %s failed: SMTP authentication rejected', purpose)
        raise
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected,
            ConnectionRefusedError, socket.gaierror, socket.timeout, TimeoutError, OSError):
        app.logger.error('Mail %s failed: SMTP connection, DNS or timeout problem', purpose)
        raise
    except (smtplib.SMTPException, ssl.SSLError):
        app.logger.error('Mail %s failed: SMTP protocol, TLS or recipient rejection', purpose)
        raise

mail = Mail(app)

VERIFICATION_CODES = {}
RESET_CODES = {}


def get_db_connection(autocommit=True):
    return pymysql.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME,
        port=DB_PORT, cursorclass=pymysql.cursors.DictCursor, autocommit=autocommit
    )


def now_str():
    """NFH convention: DD/MM/YYYY - HH:MM"""
    return datetime.now().strftime('%d/%m/%Y - %H:%M')


def dues_summary(cursor, user_id):
    """Return a compact, read-only summary of a homeowner's unpaid monthly dues."""
    cursor.execute("""SELECT COUNT(*) AS unpaid_months, COALESCE(SUM(amount),0) AS outstanding_balance,
                              MIN(due_month) AS oldest_unpaid_due
                       FROM monthly_dues WHERE user_id=%s AND status='Unpaid'""", (user_id,))
    row = cursor.fetchone() or {}
    cursor.execute("""SELECT due_month, amount FROM monthly_dues
                       WHERE user_id=%s AND status='Unpaid' ORDER BY due_month ASC""", (user_id,))
    unpaid_rows = cursor.fetchall() or []
    count = int(row.get('unpaid_months') or 0)
    oldest = row.get('oldest_unpaid_due')
    if count <= 0 or not oldest:
        period = 'Clear'
    else:
        today = datetime.now().date().replace(day=1)
        if isinstance(oldest, datetime): oldest = oldest.date()
        months = max(1, (today.year-oldest.year)*12 + today.month-oldest.month + 1)
        years, rem = divmod(months, 12)
        parts=[]
        if years: parts.append(f"{years} year{'s' if years != 1 else ''}")
        if rem: parts.append(f"{rem} month{'s' if rem != 1 else ''}")
        period = ' and '.join(parts) or '1 month'
    return {
        'unpaid_months': count,
        'outstanding_balance': float(row.get('outstanding_balance') or 0),
        'oldest_unpaid_due': oldest.strftime('%B %Y') if oldest else None,
        'unpaid_periods': [r['due_month'].strftime('%B %Y') if hasattr(r.get('due_month'), 'strftime') else str(r.get('due_month')) for r in unpaid_rows],
        'outstanding_period': period,
        'dues_status': 'Outstanding' if count else 'Clear'
    }


def dues_summaries(cursor, user_ids):
    """Return dues summaries for many homeowners using two queries total.

    This avoids the previous per-homeowner query loop on officer dashboards while
    preserving the same summary shape returned by ``dues_summary``.
    """
    ids=sorted({int(uid) for uid in (user_ids or []) if uid is not None})
    if not ids:
        return {}
    placeholders=','.join(['%s']*len(ids))
    cursor.execute(f"""SELECT user_id, COUNT(*) AS unpaid_months, COALESCE(SUM(amount),0) AS outstanding_balance,
                              MIN(due_month) AS oldest_unpaid_due
                       FROM monthly_dues
                       WHERE user_id IN ({placeholders}) AND status='Unpaid'
                       GROUP BY user_id""", tuple(ids))
    aggregates={row['user_id']:row for row in (cursor.fetchall() or [])}
    cursor.execute(f"""SELECT user_id, due_month, amount FROM monthly_dues
                       WHERE user_id IN ({placeholders}) AND status='Unpaid'
                       ORDER BY user_id, due_month ASC""", tuple(ids))
    periods={uid:[] for uid in ids}
    for row in cursor.fetchall() or []:
        periods.setdefault(row['user_id'],[]).append(row)

    today=datetime.now().date().replace(day=1)
    result={}
    for uid in ids:
        row=aggregates.get(uid) or {}
        count=int(row.get('unpaid_months') or 0)
        oldest=row.get('oldest_unpaid_due')
        if count<=0 or not oldest:
            period='Clear'
        else:
            oldest_date=oldest.date() if isinstance(oldest,datetime) else oldest
            months=max(1,(today.year-oldest_date.year)*12+today.month-oldest_date.month+1)
            years,rem=divmod(months,12)
            parts=[]
            if years: parts.append(f"{years} year{'s' if years != 1 else ''}")
            if rem: parts.append(f"{rem} month{'s' if rem != 1 else ''}")
            period=' and '.join(parts) or '1 month'
        result[uid]={
            'unpaid_months':count,
            'outstanding_balance':float(row.get('outstanding_balance') or 0),
            'oldest_unpaid_due':oldest.strftime('%B %Y') if oldest else None,
            'unpaid_periods':[r['due_month'].strftime('%B %Y') if hasattr(r.get('due_month'),'strftime') else str(r.get('due_month')) for r in periods.get(uid,[])],
            'outstanding_period':period,
            'dues_status':'Outstanding' if count else 'Clear'
        }
    return result


def format_pdf_datetime(value):
    """Human-readable presentation for database datetimes used in PDFs."""
    if not value:
        return ''
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        dt = None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S'):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                pass
        if dt is None:
            return text
    return dt.strftime('%B %d, %Y • %I:%M %p').replace(' 0', ' ')


def generate_code(length=6):
    return ''.join(secrets.choice(string.digits) for _ in range(length))


OTP_TTL_SECONDS = max(120, int(os.getenv('OTP_TTL_SECONDS', '600')))
OTP_RESEND_COOLDOWN_SECONDS = max(15, int(os.getenv('OTP_RESEND_COOLDOWN_SECONDS', '60')))
OTP_MAX_ATTEMPTS = max(3, int(os.getenv('OTP_MAX_ATTEMPTS', '5')))


def _issue_one_time_code(store, key):
    """Create a short-lived code with resend throttling for this process."""
    now = time.time()
    current = store.get(key)
    if isinstance(current, dict):
        remaining = OTP_RESEND_COOLDOWN_SECONDS - int(now - float(current.get('sent_at', 0)))
        if remaining > 0 and not current.get('verified'):
            return None, remaining
    code = generate_code()
    store[key] = {
        'code_hash': hmac.new(app.secret_key.encode(), (key + ':' + code).encode(), hashlib.sha256).hexdigest(),
        'expires_at': now + OTP_TTL_SECONDS,
        'sent_at': now,
        'attempts': 0,
        'verified': False,
    }
    return code, 0


def _verify_one_time_code(store, key, submitted_code, mark_verified=False):
    entry = store.get(key)
    if not isinstance(entry, dict):
        return False, 'No active verification code was found. Request a new code.'
    now = time.time()
    if now > float(entry.get('expires_at', 0)):
        store.pop(key, None)
        return False, 'The verification code has expired. Request a new code.'
    if int(entry.get('attempts', 0)) >= OTP_MAX_ATTEMPTS:
        store.pop(key, None)
        return False, 'Too many incorrect attempts. Request a new code.'
    if not (re.fullmatch(r'\d{6}', str(submitted_code or '')) and
            secrets.compare_digest(str(entry.get('code_hash') or ''),
                hmac.new(app.secret_key.encode(), (key + ':' + str(submitted_code)).encode(), hashlib.sha256).hexdigest())):
        entry['attempts'] = int(entry.get('attempts', 0)) + 1
        remaining = max(0, OTP_MAX_ATTEMPTS - entry['attempts'])
        return False, f'Invalid verification code. {remaining} attempt(s) remaining.'
    if mark_verified:
        entry['verified'] = True
        entry['code_hash'] = None
        # Keep a verified registration token alive only for the original TTL.
    return True, None


def _registration_email_verified(email):
    entry = VERIFICATION_CODES.get(email)
    return bool(isinstance(entry, dict) and entry.get('verified') and time.time() <= float(entry.get('expires_at', 0)))


def _issue_password_reset_token(email):
    """Create a short-lived one-use token after the email OTP is verified."""
    entry = RESET_CODES.get(email)
    if not isinstance(entry, dict) or not entry.get('verified'):
        return None
    if time.time() > float(entry.get('expires_at', 0)):
        RESET_CODES.pop(email, None)
        return None
    token = secrets.token_urlsafe(32)
    entry['reset_token_hash'] = hashlib.sha256(token.encode('utf-8')).hexdigest()
    entry['verified_at'] = time.time()
    return token


def _password_reset_token_valid(email, token):
    entry = RESET_CODES.get(email)
    if not isinstance(entry, dict) or not entry.get('verified'):
        return False
    if time.time() > float(entry.get('expires_at', 0)):
        RESET_CODES.pop(email, None)
        return False
    expected = str(entry.get('reset_token_hash') or '')
    supplied = hashlib.sha256(str(token or '').encode('utf-8')).hexdigest()
    return bool(expected and secrets.compare_digest(expected, supplied))


def _is_local_demo_reset(email):
    """Allow seeded .local demo accounts to recover on localhost without SMTP."""
    host = (request.remote_addr or '').strip()
    return email.endswith('@nfhhoa.local') and host in {'127.0.0.1', '::1', 'localhost'}


# ---------------------------------------------------------------------------
# Validation helpers (also enforced server-side so URL/API bypass is blocked)
# ---------------------------------------------------------------------------
COLOR_RE = re.compile(r'^[A-Za-z\s\-]+$')


def validate_vehicle_list(vehicles):
    """Returns an error message string, or None if all vehicles are valid."""
    if not vehicles:
        return 'At least one vehicle is required.'
    for idx, v in enumerate(vehicles, start=1):
        brand = (v.get('brand') or '').strip()
        model = (v.get('model') or '').strip()
        color = (v.get('color') or '').strip()
        plate = (v.get('plate') or '').strip()
        if not plate:
            return f'Vehicle #{idx}: Plate number is required.'
        if not brand:
            return f'Vehicle #{idx}: Vehicle brand is required.'
        if len(model) < 4:
            return f'Vehicle #{idx}: Vehicle Model must be at least 4 characters.'
        if not color or not COLOR_RE.match(color):
            return f'Vehicle #{idx}: Vehicle Color must contain letters only.'
    return None


# ---------------------------------------------------------------------------
# HOA settings (key/value store) — used for Treasurer contact info
# ---------------------------------------------------------------------------
def get_settings(keys=None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if keys:
                fmt = ','.join(['%s'] * len(keys))
                cursor.execute(f"SELECT setting_key, setting_value FROM hoa_settings WHERE setting_key IN ({fmt})", tuple(keys))
            else:
                cursor.execute("SELECT setting_key, setting_value FROM hoa_settings")
            rows = cursor.fetchall()
        return {r['setting_key']: r['setting_value'] for r in rows}
    finally:
        conn.close()


def set_setting(key, value, updated_by=None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""INSERT INTO hoa_settings (setting_key, setting_value, updated_by)
                              VALUES (%s,%s,%s)
                              ON DUPLICATE KEY UPDATE setting_value=%s, updated_by=%s""",
                           (key, value, updated_by, value, updated_by))
    finally:
        conn.close()


def get_treasurer_contact():
    s = get_settings(['treasurer_name', 'treasurer_phone', 'treasurer_email', 'treasurer_office_hours'])
    return {
        'name': s.get('treasurer_name') or 'Office of the Treasurer',
        'phone': s.get('treasurer_phone') or 'N/A',
        'email': s.get('treasurer_email') or 'N/A',
        'office_hours': s.get('treasurer_office_hours') or 'N/A',
    }


# ---------------------------------------------------------------------------
# Audit + notifications
# ---------------------------------------------------------------------------
def log_audit_action(username, role, action, item, prev_val=None, new_val=None):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO audit_logs (username, role, action, item, prev_val, new_val)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (username, role, action, item,
                  str(prev_val) if prev_val is not None else None,
                  str(new_val) if new_val is not None else None))
        conn.close()
    except Exception as e:
        print(f"Audit log error: {e}")




def record_request_history(request_id, action, previous_status=None, new_status=None, remarks=None, actor_name=None, actor_role=None):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""INSERT INTO request_history
                (request_id,action,previous_status,new_status,actor_name,actor_role,remarks)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (request_id, action, previous_status, new_status,
                 actor_name or session.get('full_name') or session.get('username') or 'System',
                 actor_role or session.get('role') or 'System', remarks))
        conn.close()
    except Exception as exc:
        app.logger.warning('Request history insert failed for %s: %s', request_id, exc)




def send_in_app_notification(user_id, subject, body, related_type=None, related_id=None, dedupe_key=None):
    """Create an in-app workflow notification without sending email.

    Used for face-to-face payment/release events where the homeowner is already
    physically present and the portal record is the useful confirmation.
    """
    try:
        if dedupe_key and notification_already_sent(dedupe_key):
            return {'created': False}
        create_alert(user_id, f"{subject}: {body}")
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""INSERT INTO notification_log
                (user_id, channel, subject, body, related_type, related_id, dedupe_key, status)
                VALUES (%s,'In-App',%s,%s,%s,%s,%s,'Sent')""",
                (user_id, subject, body, related_type, related_id, dedupe_key))
        conn.close()
        return {'created': True}
    except Exception as exc:
        app.logger.warning('In-app notification failed for %s: %s', related_id, exc)
        return {'created': False}


def get_active_document_template(cursor, request_type=None, template_key=None):
    """Return the newest active version of the requested official soft-copy template."""
    if template_key:
        cursor.execute("""SELECT * FROM document_templates
                          WHERE template_key=%s AND status='Active'
                          ORDER BY version_no DESC LIMIT 1""", (template_key,))
        return cursor.fetchone()
    if request_type:
        cursor.execute("""SELECT dt.* FROM document_templates dt
                          LEFT JOIN service_types s ON s.service_name=%s
                          WHERE dt.status='Active'
                            AND (dt.service_name=%s OR dt.template_key=s.form_template)
                          ORDER BY (dt.service_name=%s) DESC, dt.version_no DESC LIMIT 1""",
                       (request_type, request_type, request_type))
        return cursor.fetchone()
    return None


def assign_request_document_template(cursor, request_id, request_type):
    """Freeze the template version used by a request so later Admin edits do not rewrite history."""
    cursor.execute("SELECT document_template_id FROM requests WHERE id=%s", (request_id,))
    row = cursor.fetchone()
    if row and row.get('document_template_id'):
        return row.get('document_template_id')
    template = get_active_document_template(cursor, request_type=request_type)
    if template:
        cursor.execute("""UPDATE requests SET document_template_id=%s, document_prepared_at=COALESCE(document_prepared_at,NOW())
                          WHERE id=%s""", (template['id'], request_id))
        return template['id']
    return None


def _request_workflow_after_approval(cursor, req):
    """Resolve the next stage after initial/executive approval using actual HOA procedure."""
    service = get_service_config(cursor, req['request_type'], active_only=False)
    requires_dues = False if req['request_type'] == 'Statement of Account' else (True if not service else bool(service.get('requires_dues_clearance')))
    requires_payment = bool(float(req.get('fee') or 0) > 0) if not service else bool(service.get('requires_payment')) and float(req.get('fee') or 0) > 0
    dues = dues_summary(cursor, req['user_id']) if requires_dues else {'unpaid_months': 0}
    if dues.get('unpaid_months', 0) > 0 and req.get('request_type') != 'Statement of Account':
        return 'Awaiting Dues Clearance', requires_payment
    if requires_payment:
        return 'Ready for Payment & Release', True
    return 'Ready for Release', False


def _ensure_payment_reference(cursor, transaction_id):
    """Create an internal payment-confirmation reference for request tracking.

    This is not an accounting invoice/receipt number. Official financial records
    remain under the HOA Treasurer's existing financial procedure.
    """
    year = datetime.now().year
    ref = f"NFH-PAY-{year}-{transaction_id:05d}"
    cursor.execute("""UPDATE payment_transactions
                      SET system_reference=COALESCE(system_reference,%s)
                      WHERE id=%s""", (ref, transaction_id))
    return ref

def generate_homeowner_public_id(cursor, block, lot):
    b = re.sub(r'[^A-Za-z0-9]', '', str(block or '')).upper()
    l = re.sub(r'[^A-Za-z0-9]', '', str(lot or '')).upper()
    base = f"NFH-B{b or 'NA'}-L{l or 'NA'}"
    cursor.execute("SELECT COUNT(*) AS total FROM users WHERE homeowner_public_id LIKE %s", (base + '%',))
    n = (cursor.fetchone() or {}).get('total', 0)
    return base if n == 0 else f"{base}-{n + 1}"


PURPOSE_REQUIRED_REQUEST_TYPES = {
    'Gate Pass',
    'Proof of Residency',
    'Certificate of Improvement',
    'Certificate of Membership',
}


def complete_missing_request_profile(cursor, user_id, user, form_data):
    """Fill only missing core property fields from the request form.

    New registrations already capture these values. This compatibility path keeps
    older homeowner accounts from being forced to leave the request screen and
    visit Profile before they can proceed.
    """
    user = dict(user or {})
    candidates = {
        'block': str(form_data.get('profileBlock') or form_data.get('blockNum') or '').strip(),
        'lot': str(form_data.get('profileLot') or form_data.get('lotNum') or '').strip(),
        'address_line': str(form_data.get('profileAddressLine') or '').strip(),
    }
    updates = {}
    for field, value in candidates.items():
        if not str(user.get(field) or '').strip() and value:
            updates[field] = value
            user[field] = value
    if updates:
        assignments = ', '.join(f"{field}=%s" for field in updates)
        cursor.execute(f"UPDATE users SET {assignments} WHERE id=%s", (*updates.values(), user_id))
    return user


def validate_request_payload(title, form_data, user, service_config=None):
    """Server-side request validation for every supported request template."""
    missing = []
    if not str(user.get('block') or '').strip(): missing.append('Block Number')
    if not str(user.get('lot') or '').strip(): missing.append('Lot Number')
    if not str(user.get('address_line') or '').strip(): missing.append('Complete Address')
    if missing:
        return 'Please provide the missing property details shown in the request form: ' + ', '.join(missing) + '.'

    config = service_config or {}
    form_template = str(config.get('form_template') or '').strip() or {
        'Gate Pass': 'gate-pass',
        'Proof of Residency': 'proof-residency',
        'Certificate of Improvement': 'cert-improvement',
        'Certificate of Membership': 'cert-membership',
        'Move-in Gate Pass': 'move-in',
        'Move-out Gate Pass': 'move-out',
        'Vehicle Sticker Application': 'vehicle-sticker',
        'Renters/Tenants Information Form': 'tenant-form',
    }.get(title, 'generic')

    purpose_required = bool(config.get('purpose_required')) if 'purpose_required' in config else title in PURPOSE_REQUIRED_REQUEST_TYPES
    if purpose_required:
        purpose = str(form_data.get('purpose') or '').strip()
        if not purpose:
            return 'Please select the reason or purpose for this request.'
        if purpose == 'Other' and not str(form_data.get('purposeDetails') or '').strip():
            return 'Please briefly specify the reason for this request.'

    def required(key, label, minimum=1):
        value = str(form_data.get(key) or '').strip()
        if len(value) < minimum:
            return f'{label} is required.'
        return None

    if form_template == 'statement-of-account':
        from datetime import date as _date
        try:
            start = _date.fromisoformat(str(form_data.get('period_start') or ''))
            end = _date.fromisoformat(str(form_data.get('period_end') or ''))
        except ValueError:
            return 'Select valid coverage dates for the Statement of Account.'
        if start > end:
            return 'The coverage start date must not be later than the end date.'
        if not str(form_data.get('purpose') or '').strip():
            return 'Purpose of Request is required.'
        if len(str(form_data.get('purpose') or '')) > 250:
            return 'Purpose must not exceed 250 characters.'
        if len(str(form_data.get('remarks') or '')) > 1000:
            return 'Remarks must not exceed 1000 characters.'
    elif form_template == 'gate-pass':
        err = required('materialsList', 'List of materials', 3)
        if err: return err
    elif form_template == 'proof-residency':
        for key, label in [('verifiedOwner', 'Verified owner'), ('requestDate', 'Date requested')]:
            err = required(key, label)
            if err: return err
    elif form_template == 'cert-improvement':
        err = required('requestDate', 'Request date')
        if err: return err
    elif form_template == 'cert-membership':
        err = required('applicationDate', 'Application date')
        if err: return err
    elif form_template == 'move-in':
        err = required('moveInDate', 'Move-in date')
        if err: return err
    elif form_template == 'move-out':
        err = required('moveOutDate', 'Move-out date')
        if err: return err
    elif form_template == 'vehicle-sticker':
        err = validate_vehicle_list(form_data.get('vehicles', []))
        if err: return err
        for i, vehicle in enumerate(form_data.get('vehicles', []), start=1):
            plate = str(vehicle.get('plate') or '').strip().upper()
            if not re.match(r'^[A-Z0-9][A-Z0-9 -]{2,9}$', plate):
                return f'Vehicle #{i}: enter a valid plate number using 3-10 letters/numbers.'
    elif form_template == 'tenant-form':
        for key, label in [
            ('fullName', 'Tenant full name'), ('dob', 'Date of birth'), ('phoneNum', 'Phone number'),
            ('previousAddress', 'Previous address'), ('rentedAddress', 'Rented unit address'),
            ('ownerName', 'Unit owner name'), ('ownerPhone', 'Owner contact number'),
            ('emergencyName', 'Emergency contact person'), ('emergencyPhone', 'Emergency contact number')]:
            err = required(key, label)
            if err: return err
        phone_fields = [('phoneNum', 'Phone number'), ('ownerPhone', 'Owner contact number'), ('emergencyPhone', 'Emergency contact number')]
        for key, label in phone_fields:
            digits = re.sub(r'\D', '', str(form_data.get(key) or ''))
            if len(digits) < 10 or len(digits) > 11:
                return f'{label} must contain a valid 10-11 digit number.'
        if not form_data.get('oathAgreed'):
            return 'You must accept the Tenant Oath before submitting.'
    else:
        # Administrator-created generic services still require meaningful details
        # so the reviewing officer receives more than an empty transaction shell.
        details = str(form_data.get('requestDetails') or '').strip()
        if len(details) < 5:
            return 'Please provide brief details for this request.'
    return None


def create_alert(user_id, text):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO alerts (user_id, text) VALUES (%s, %s)", (user_id, text))
        conn.close()
    except Exception as e:
        print(f"Alert insert error: {e}")


def notification_already_sent(dedupe_key):
    if not dedupe_key:
        return False
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM notification_log WHERE dedupe_key=%s", (dedupe_key,))
            row = cursor.fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def send_alert_and_email(user_id, subject, body, related_type=None, related_id=None, dedupe_key=None, important=True, html_body=None):
    """Persist the in-app notification and send the matching workflow email.

    Workflow mail deliberately uses the same initialized Flask-Mail ``mail``
    object and ``Message`` path as the already-working registration-code mail.
    Business actions are committed by their routes before this helper runs, so
    SMTP failure can never roll back an HOA decision.
    """
    user = None
    email_sent = False
    email_error = None
    in_app_exists = False
    email_already_sent = False

    # Dedupe channels independently.  An earlier in-app notification (or an
    # earlier FAILED email attempt) must never prevent a later legitimate SMTP
    # attempt.  Only a previously successful Email/Sent row suppresses mail.
    if dedupe_key:
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("""SELECT channel, status FROM notification_log
                                  WHERE dedupe_key=%s""", (dedupe_key,))
                prior = cursor.fetchall()
            conn.close()
            in_app_exists = any(r.get('channel') == 'In-App' and r.get('status') == 'Sent' for r in prior)
            email_already_sent = any(r.get('channel') == 'Email' and r.get('status') == 'Sent' for r in prior)
        except Exception as exc:
            app.logger.warning('[EMAIL] Dedupe lookup failed for %s: %s', related_id, exc)

    if not in_app_exists:
        create_alert(user_id, f"{subject}: {body}")

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Registered email is the only field required for critical workflow
            # delivery.  Older live NFH databases may not yet have the optional
            # email_notifications preference column; verification mail works on
            # those databases because it also depends only on the email address.
            cursor.execute("SELECT email FROM users WHERE id=%s", (user_id,))
            user = cursor.fetchone()
        conn.close()

        # Important workflow events always email.  This intentionally avoids
        # making correction/approval/rejection delivery depend on an optional
        # preference column that may be absent in an upgraded database.
        should_email = bool(important)
        recipient = (user.get('email') or '').strip() if user else ''

        if email_already_sent:
            email_sent = True
            email_error = 'already_sent'
        elif recipient and should_email:
            # Match the proven registration verification path: construct a
            # Flask-Mail Message and call the SAME global mail.send().  Do not
            # add a second mail object or frontend recipient source.
            if not app.config.get('MAIL_USERNAME'):
                email_error = 'Mail sender is not configured.'
                app.logger.warning('[EMAIL FAILURE] %s for %s: MAIL_USERNAME is not configured', subject, related_id)
            else:
                try:
                    msg = Message(subject, recipients=[recipient])
                    msg.body = body
                    if html_body is None:
                        try:
                            from nfh_status_emails import render_status_email
                            kind = None
                            key = str(dedupe_key or '')
                            if key.startswith('homeowner-registration-verified-'): kind = 'account_verified'
                            elif key.startswith('homeowner-registration-rejected-'): kind = 'account_rejected'
                            elif key.startswith('approval-'): kind = 'request_approved'
                            elif key.startswith('rejected-'): kind = 'request_rejected'
                            if kind:
                                mail_conn = get_db_connection()
                                try:
                                    with mail_conn.cursor() as mail_cursor:
                                        mail_cursor.execute('SELECT first_name,last_name,homeowner_public_id,verified_at FROM users WHERE id=%s', (user_id,))
                                        mail_user = mail_cursor.fetchone() or {}
                                finally: mail_conn.close()
                                name = (str(mail_user.get('first_name') or '')+' '+str(mail_user.get('last_name') or '')).strip()
                                detail = {'Homeowner Name':name}
                                if kind.startswith('account_'):
                                    detail['Homeowner ID'] = mail_user.get('homeowner_public_id') or str(user_id)
                                    detail['Account Status'] = 'Verified' if kind=='account_verified' else 'Rejected'
                                    detail['Decision Date'] = str(mail_user.get('verified_at') or '')
                                else:
                                    mail_conn = get_db_connection()
                                    try:
                                        with mail_conn.cursor() as mail_cursor:
                                            mail_cursor.execute('SELECT id,request_type,date_submitted,executive_decided_at,executive_decided_by,fee,status,remarks,executive_decision_details FROM requests WHERE id=%s AND user_id=%s',(related_id,user_id))
                                            r = mail_cursor.fetchone() or {}
                                    finally: mail_conn.close()
                                    detail.update({'Request ID':related_id or '', 'Request Type':r.get('request_type') or '',
                                                   'Date Submitted':str(r.get('date_submitted') or ''),
                                                   'Decision Date':str(r.get('executive_decided_at') or ''),
                                                   'Request Status':r.get('status') or ''})
                                    if kind=='request_approved':
                                        detail['Approved By']=r.get('executive_decided_by') or 'Authorized HOA officer'
                                        detail['Request Fee']='PHP '+str(r.get('fee') or '0.00')
                                    else:detail['Reason'] = r.get('executive_decision_details') or r.get('remarks') or 'Please contact the HOA office.'
                                next_step = 'Please sign in to the NFH-HOA portal to review your account or request. Payment and physical release, where applicable, are separate steps.'
                                html_body, msg.body = render_status_email(kind,name,detail,next_step)
                        except Exception:
                            app.logger.exception('Status email formatting failed; using safe plain-text fallback.')
                    if html_body is not None:
                        msg.html = html_body
                    mail.send(msg)
                    email_sent = True
                    app.logger.info('[EMAIL SUCCESS] %s for %s sent to registered homeowner email %s',
                                    subject, related_id, recipient)
                    print(f"[EMAIL SUCCESS] {subject} for {related_id} sent to {recipient}")
                except Exception as exc:
                    email_error = f'{type(exc).__name__}: {exc}'
                    app.logger.warning('[EMAIL FAILURE] %s for %s to %s: %s',
                                       subject, related_id, recipient, email_error)
                    print(f"[EMAIL FAILURE] {subject} for {related_id} to {recipient}: {email_error}")
        elif not recipient:
            email_error = 'No registered homeowner email address is available.'
            app.logger.warning('[EMAIL FAILURE] %s for %s: homeowner has no registered email', subject, related_id)
        else:
            email_error = 'Email notifications are disabled for this account.'
    except Exception as exc:
        email_error = f'{type(exc).__name__}: {exc}'
        app.logger.warning('[EMAIL FAILURE] Recipient lookup for user_id=%s related_id=%s: %s',
                           user_id, related_id, email_error)

    # Record only channel attempts that were not already successfully logged.
    # Logging errors do not change the already-completed workflow action.
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            if not email_already_sent:
                cursor.execute("""INSERT INTO notification_log
                    (user_id, channel, subject, body, recipient, related_type, related_id, dedupe_key, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                               (user_id, 'Email', subject, body,
                                user.get('email') if user else None,
                                related_type, related_id, dedupe_key,
                                'Sent' if email_sent else 'Failed'))
            if not in_app_exists:
                cursor.execute("""INSERT INTO notification_log
                    (user_id, channel, subject, body, related_type, related_id, dedupe_key, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                               (user_id, 'In-App', subject, body,
                                related_type, related_id, dedupe_key, 'Sent'))
        conn.close()
    except Exception as exc:
        app.logger.warning('Notification log insert failed for user_id=%s related_id=%s: %s',
                           user_id, related_id, exc)

    return {'created': not in_app_exists, 'email_sent': email_sent,
            'reason': email_error, 'recipient': user.get('email') if user else None}


def _set_login_session(user):
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['full_name'] = f"{user['first_name']} {user['last_name']}".strip()
    session['role'] = user['role']
    session['email'] = user.get('email', '')
    session['last_activity'] = time.time()
    session.permanent = True


def _role_home_url(role):
    if role in ['Secretary', 'Treasurer', *EXECUTIVE_ROLES]:
        return url_for('officer')
    if role == 'Admin':
        return url_for('admin')
    if role == 'Renter':
        return url_for('renter_portal')
    return url_for('homeowner')


# Prevent stale login/protected HTML from being restored as a usable page via browser cache.
# Static assets keep their normal caching behavior.
@app.after_request
def set_auth_page_cache_headers(response):
    if request.endpoint in {'index', 'register_page', 'homeowner', 'renter_portal', 'renter_invitation_page', 'officer', 'admin', 'logout'}:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


# ===========================================================================
# PAGE ROUTES
# ===========================================================================
@app.route('/')
def index():
    if 'user_id' in session:
        role = session.get('role', 'Homeowner')
        if role == 'Homeowner':
            return redirect(url_for('homeowner'))
        elif role in ['Secretary', 'Treasurer', *EXECUTIVE_ROLES]:
            return redirect(url_for('officer'))
        elif role == 'Admin':
            return redirect(url_for('admin'))
    if 'user_id' in session:
        return redirect(_role_home_url(session.get('role')))
    return render_template('index.html')


@app.route('/register')
def register_page():
    if 'user_id' in session:
        role = session.get('role', 'Homeowner')
        if role == 'Homeowner':
            return redirect(url_for('homeowner'))
        elif role in ['Secretary', 'Treasurer', *EXECUTIVE_ROLES]:
            return redirect(url_for('officer'))
        elif role == 'Admin':
            return redirect(url_for('admin'))
    if 'user_id' in session:
        return redirect(_role_home_url(session.get('role')))
    return render_template('register.html')


@app.route('/home')
def homeowner():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    if session.get('role') != 'Homeowner':
        return redirect(url_for('index'))
    return render_template('homeowner.html', treasurer=get_treasurer_contact())



# ---------------------------------------------------------------------------
# Officer route (queries homeowners for Treasurer dropdown)
# ---------------------------------------------------------------------------
@app.route('/officer')
def officer():
    if 'user_id' not in session or session.get('role') not in OFFICER_ROLES:
        return redirect(url_for('index'))

    role = session.get('role', 'Secretary')
    username = session.get('username')
    ready_release_requests = []

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT u.id, u.homeowner_public_id, u.first_name, u.last_name, u.username, u.block, u.lot,
                       CONCAT(u.first_name, ' ', u.last_name) AS full_name,
                       COALESCE(d.unpaid_months, 0) AS unpaid_months,
                       COALESCE(d.outstanding_balance, 0) AS outstanding_balance
                FROM users u
                LEFT JOIN (
                    SELECT user_id, COUNT(*) AS unpaid_months, COALESCE(SUM(amount),0) AS outstanding_balance
                    FROM monthly_dues
                    WHERE status='Unpaid'
                    GROUP BY user_id
                ) d ON d.user_id=u.id
                WHERE u.role = 'Homeowner' AND u.status = 'Active'
                ORDER BY u.last_name ASC, u.first_name ASC
            """)
            homeowners = cursor.fetchall()

            # Treasurer-facing dues work queues are intentionally pre-aggregated in
            # one query so the interface remains usable even when many homeowners
            # have outstanding monthly dues.
            outstanding_dues_homeowners = []
            if role in ('Treasurer', 'Admin'):
                cursor.execute("""
                    SELECT u.id, u.homeowner_public_id,
                           CONCAT(u.first_name, ' ', u.last_name) AS full_name,
                           u.block, u.lot,
                           COUNT(md.id) AS unpaid_months,
                           COALESCE(SUM(md.amount), 0) AS outstanding_balance,
                           MIN(md.due_month) AS oldest_unpaid_due,
                           DATE_FORMAT(MIN(md.due_month), '%%M %%Y') AS oldest_unpaid_due_display,
                           GROUP_CONCAT(DATE_FORMAT(md.due_month, '%%M %%Y') ORDER BY md.due_month SEPARATOR ', ') AS unpaid_periods_display
                    FROM users u
                    JOIN monthly_dues md ON md.user_id = u.id AND md.status = 'Unpaid'
                    WHERE u.role = 'Homeowner' AND u.status = 'Active'
                    GROUP BY u.id, u.homeowner_public_id, u.first_name, u.last_name, u.block, u.lot
                    ORDER BY outstanding_balance DESC, u.last_name ASC, u.first_name ASC
                """)
                outstanding_dues_homeowners = cursor.fetchall()

            cursor.execute("SELECT item_name, amount, proposed_amount, status FROM fees ORDER BY item_name ASC")
            fees_rows = cursor.fetchall()
            fees = {
                row['item_name']: {
                    'amount': float(row['amount']),
                    'proposed_amount': float(row['proposed_amount']) if row.get('proposed_amount') is not None else None,
                    'status': row['status']
                } for row in fees_rows
            }
            official_monthly_due = fees.get('Monthly Dues', {}).get('amount', 100.00)

            cursor.execute("SELECT * FROM service_types")
            service_rows = cursor.fetchall()
            service_map = {row['service_name']: row for row in service_rows}

            cursor.execute("""
                SELECT r.id, CONCAT(u.first_name,' ',u.last_name) AS homeowner, u.block, u.lot, r.request_type,
                       r.category, r.submission_type, r.assigned_officer, r.status, r.payment_status, r.fee,
                       r.details, r.attachment, r.remarks, r.purpose, r.purpose_details,
                       r.payment_reference, r.official_receipt_no, r.payment_date, r.ready_for_release_at,
                       r.issued_at, r.issued_by, r.sticker_valid_from, r.sticker_valid_until,
                       r.edit_access_granted_at, r.edit_access_expires_at, r.edit_access_expired_at,
                       DATE_FORMAT(r.date_submitted,'%Y-%m-%d %H:%i') AS date_submitted,
                       DATE_FORMAT(r.last_updated,'%Y-%m-%d %H:%i') AS last_updated, r.user_id
                FROM requests r JOIN users u ON r.user_id=u.id
                ORDER BY r.date_submitted DESC
            """)
            all_requests = cursor.fetchall()

            cursor.execute("SELECT * FROM payment_transactions ORDER BY created_at DESC")
            payment_tx_rows = cursor.fetchall()
            payment_tx_map = {row['request_id']: row for row in payment_tx_rows}

            # Load all homeowner dues summaries in two batched queries instead of
            # two queries per homeowner (prevents an N+1 query pattern).
            dues_cache = dues_summaries(cursor, [r['user_id'] for r in all_requests])
            for req in all_requests:
                req['dues'] = dues_cache.get(req['user_id'], {'unpaid_months':0,'outstanding_balance':0,'dues_status':'Clear'})
                req['service_config'] = service_map.get(req['request_type'])
                req['payment_tx'] = payment_tx_map.get(req['id'])

            active_requests = [r for r in all_requests if r['status'] != 'Cancelled']

            def actionable_for_role(req):
                if req.get('status') not in {'Submitted','Under Review'}:
                    return False
                # A concern-approved edit window temporarily suspends officer action
                # until the homeowner submits the revised information or the window expires.
                if _request_edit_access_active(req):
                    return False
                cfg = service_map.get(req.get('request_type'))
                allowed = service_reviewer_roles(cfg, req.get('request_type'))
                if role == 'Admin':
                    return True
                if role not in allowed:
                    return False
                if cfg and cfg.get('initial_reviewer') == 'Shared' and req.get('assigned_officer') in {'Secretary','Treasurer'}:
                    return role == req.get('assigned_officer')
                return True

            checking_requests = [r for r in active_requests if actionable_for_role(r)]
            if role == 'Secretary':
                assigned_requests = checking_requests
            elif role == 'Treasurer':
                assigned_requests = [r for r in active_requests
                                     if (r['status'] in ('Ready for Payment & Release','Awaiting Payment Verification','Approved')
                                         and r['payment_status'] == 'Unpaid')
                                     or (r['request_type'] == 'Statement of Account'
                                         and r['status'] in ('Submitted','Under Review','Ready for Payment & Release','Paid - Awaiting Release'))]
            elif role in EXECUTIVE_ROLES:
                assigned_requests = [r for r in active_requests
                                     if r['status'] == 'Pending Executive Approval' and not _request_edit_access_active(r)]
            else:
                assigned_requests = active_requests

            if role in {'Secretary','Treasurer','Admin'}:
                for req in active_requests:
                    if req['status'] != 'Ready for Release':
                        continue
                    cfg = service_map.get(req['request_type'])
                    if role == 'Admin' or role in release_roles_for_request(cfg, req.get('assigned_officer')):
                        ready_release_requests.append(req)

            cursor.execute("SELECT id, CONCAT(first_name,' ',last_name) AS full_name, username, email, mobile, role, status, profile_image, e_signature_path, e_signature_updated_at, created_at FROM users WHERE id=%s", (session['user_id'],))
            current_user = cursor.fetchone()
            if role in EXECUTIVE_ROLES:
                cursor.execute("SELECT * FROM audit_logs WHERE role IN ('President','Vice President','Board Director') ORDER BY timestamp ASC")
            else:
                cursor.execute("SELECT * FROM audit_logs WHERE role=%s OR username=%s ORDER BY timestamp ASC", (role, username))
            audits_rows = cursor.fetchall()

            concerns = []
            if role in ('Secretary','Treasurer'):
                cursor.execute("""SELECT c.*, r.request_type, r.assigned_officer, u.block, u.lot,
                                  CONCAT(u.first_name,' ',u.last_name) AS homeowner
                           FROM request_concerns c
                           JOIN requests r ON r.id=c.request_id
                           JOIN users u ON u.id=c.user_id
                           WHERE c.assigned_role=%s
                           ORDER BY c.updated_at DESC""", (role,))
                concerns = cursor.fetchall()

            executive_history = []
            if role in EXECUTIVE_ROLES:
                cursor.execute("""SELECT r.id, r.request_type, r.status, r.executive_decision_reason,
                                  r.executive_decision_details, r.executive_decided_by,
                                  r.executive_decided_role, r.executive_decided_at, u.block, u.lot,
                                  CONCAT(u.first_name,' ',u.last_name) AS homeowner
                           FROM requests r JOIN users u ON u.id=r.user_id
                           WHERE r.executive_decided_at IS NOT NULL
                           ORDER BY r.executive_decided_at DESC LIMIT 50""")
                executive_history = cursor.fetchall()

            cursor.execute("""SELECT dt.*, s.fee AS service_fee, s.requires_payment AS service_requires_payment,
                                      s.form_template AS service_form_template
                              FROM document_templates dt
                              JOIN (SELECT template_key, MAX(version_no) AS max_version
                                    FROM document_templates WHERE status='Active' GROUP BY template_key) x
                                ON x.template_key=dt.template_key AND x.max_version=dt.version_no
                              LEFT JOIN service_types s ON s.service_name=dt.service_name
                              WHERE dt.status='Active' AND dt.template_key NOT IN ('service-invoice','ack-receipt','dues-commitment') ORDER BY dt.title""")
            document_templates = cursor.fetchall()
            for _t in document_templates:
                _t['display_body_text'] = template_text_to_display(_t.get('body_text'))
                _t['display_footer_text'] = template_text_to_display(_t.get('footer_text'))

            financial_adjustments = []
            if role in ['Treasurer', 'Admin']:
                cursor.execute("SELECT * FROM financial_adjustments ORDER BY created_at DESC")
                financial_adjustments = cursor.fetchall()
        conn.close()
    except Exception as e:
        app.logger.exception('Officer route error')
        return render_template('officer.html', role=role, requests=[], all_requests=[], assigned_requests=[], checking_requests=[],
                               ready_release_requests=[], fees={}, audits=[], financial_adjustments=[], homeowners=[],
                               outstanding_dues_homeowners=[], official_monthly_due=100.00,
                               treasurer=get_treasurer_contact(), current_user=None,
                               concerns=[], executive_history=[], document_templates=[])

    if 'full_name' not in session:
        session['full_name'] = username

    return render_template('officer.html', role=role, requests=all_requests, all_requests=all_requests,
                           assigned_requests=assigned_requests, checking_requests=checking_requests,
                           ready_release_requests=ready_release_requests, fees=fees, audits=audits_rows,
                           financial_adjustments=financial_adjustments, homeowners=homeowners,
                           outstanding_dues_homeowners=outstanding_dues_homeowners,
                           official_monthly_due=official_monthly_due, treasurer=get_treasurer_contact(),
                           current_user=current_user, concerns=concerns, executive_history=executive_history,
                           document_templates=document_templates)


# ---------------------------------------------------------------------------
# Admin route

# ---------------------------------------------------------------------------
@app.route('/admin')
def admin():
    if 'user_id' not in session or session.get('role') != 'Admin':
        flash('Unauthorized access. Admin privileges required.', 'error')
        return redirect(url_for('index'))

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Consolidated dashboard metrics avoid repeated full-table COUNT queries.
            cursor.execute("""SELECT
                COUNT(*) AS total_requests,
                SUM(status IN ('Submitted','Under Review','Checked','For Correction')) AS pending_requests,
                SUM(status='Pending Executive Approval') AS pending_executive,
                SUM(status='Ready for Payment & Release' AND payment_status='Unpaid') AS ready_for_payment_release,
                SUM(status='Ready for Release') AS ready_for_release,
                SUM(status='Issued / Completed') AS completed_requests
                FROM requests""")
            request_metrics = cursor.fetchone() or {}
            total_requests = request_metrics.get('total_requests') or 0
            pending_requests = request_metrics.get('pending_requests') or 0
            pending_executive = request_metrics.get('pending_executive') or 0
            ready_for_payment_release = request_metrics.get('ready_for_payment_release') or 0
            ready_for_release = request_metrics.get('ready_for_release') or 0
            completed_requests = request_metrics.get('completed_requests') or 0

            cursor.execute("""SELECT
                SUM(role='Homeowner' AND verification_status='Verified' AND status='Active') AS total_homeowners,
                SUM(role IN ('Secretary','Treasurer','President','Vice President','Board Director') AND status='Active') AS active_officers
                FROM users""")
            user_metrics = cursor.fetchone() or {}
            total_homeowners = user_metrics.get('total_homeowners') or 0
            active_officers = user_metrics.get('active_officers') or 0

            cursor.execute("SELECT COUNT(*) AS total FROM fees WHERE status='Pending Executive Approval'")
            pending_fee_changes = cursor.fetchone()['total']

            cursor.execute("SELECT * FROM audit_logs ORDER BY timestamp ASC")
            audits_rows = cursor.fetchall()

            cursor.execute("""
                SELECT id, CONCAT(first_name,' ',last_name) AS full_name, username, email, mobile, role, status, created_at
                FROM users WHERE role IN ('Secretary','Treasurer','President','Vice President','Board Director') ORDER BY created_at DESC
            """)
            officers = cursor.fetchall()

            cursor.execute("""
                SELECT id, homeowner_public_id, CONCAT(first_name,' ',COALESCE(NULLIF(middle_name,''),''),
                       CASE WHEN middle_name IS NULL OR middle_name='' THEN '' ELSE ' ' END,last_name) AS full_name,
                       first_name, middle_name, last_name, suffix, email, mobile, block, lot, address_line, household,
                       verification_status, status, created_at
                FROM users WHERE role='Homeowner' AND verification_status='Verified'
                ORDER BY status='Active' DESC, last_name ASC, first_name ASC
            """)
            homeowners = cursor.fetchall()

            cursor.execute("SELECT * FROM import_history ORDER BY created_at DESC LIMIT 100")
            import_history = cursor.fetchall()

            cursor.execute("SELECT COUNT(*) AS total FROM request_concerns WHERE status IN ('Open','Under Review')")
            open_concerns = cursor.fetchone()['total']

            cursor.execute("""
                SELECT r.id, CONCAT(u.first_name,' ',u.last_name) AS homeowner, u.block, u.lot, r.request_type, r.category,
                       r.submission_type, r.assigned_officer, r.status, r.payment_status,
                       DATE_FORMAT(r.date_submitted,'%Y-%m-%d %H:%i') AS date_submitted,
                       DATE_FORMAT(r.last_updated,'%Y-%m-%d %H:%i') AS last_updated
                FROM requests r JOIN users u ON r.user_id=u.id ORDER BY r.date_submitted DESC
            """)
            requests_list = cursor.fetchall()

            cursor.execute("SELECT item_name, amount, proposed_amount, status FROM fees ORDER BY item_name ASC")
            fees_rows = cursor.fetchall()
            fees = {
                row['item_name']: {
                    'amount': float(row['amount']),
                    'proposed_amount': float(row['proposed_amount']) if row.get(
                        'proposed_amount') is not None else None,
                    'status': row['status']
                } for row in fees_rows
            }

            cursor.execute("SELECT * FROM requests WHERE status='Cancelled' ORDER BY last_updated DESC")
            cancellations = cursor.fetchall()
            cursor.execute("SELECT * FROM financial_adjustments ORDER BY created_at DESC")
            financial_adjustments = cursor.fetchall()
            cursor.execute("SELECT * FROM notification_log ORDER BY sent_at DESC LIMIT 200")
            notifications_log = cursor.fetchall()
            cursor.execute("SELECT id, CONCAT(first_name,' ',last_name) AS full_name, username, email, mobile, role, status, profile_image, e_signature_path, e_signature_updated_at, created_at FROM users WHERE id=%s", (session['user_id'],))
            current_user = cursor.fetchone()
            cursor.execute("""SELECT id, homeowner_public_id, CONCAT(first_name,' ',last_name) AS full_name,
                              email, mobile, block, lot, address_line, verification_status, created_at
                              FROM users WHERE role='Homeowner' AND verification_status='Pending Verification'
                              ORDER BY created_at ASC""")
            pending_homeowners = cursor.fetchall()
            cursor.execute("SELECT * FROM service_types ORDER BY category, service_name")
            service_types = cursor.fetchall()
            cursor.execute("""SELECT dt.* FROM document_templates dt
                              JOIN (SELECT template_key, MAX(version_no) AS max_version
                                    FROM document_templates WHERE status='Active' GROUP BY template_key) x
                                ON x.template_key=dt.template_key AND x.max_version=dt.version_no
                              WHERE dt.status='Active' AND dt.template_key NOT IN ('service-invoice','ack-receipt','dues-commitment') ORDER BY dt.title""")
            document_templates = cursor.fetchall()
            for _t in document_templates:
                _t['display_body_text'] = template_text_to_display(_t.get('body_text'))
                _t['display_footer_text'] = template_text_to_display(_t.get('footer_text'))
            cursor.execute("""SELECT r.request_type,
                       COUNT(*) AS completed_requests,
                       ROUND(AVG(TIMESTAMPDIFF(MINUTE, r.date_submitted, r.issued_at))/60, 2) AS avg_total_hours,
                       ROUND(AVG(TIMESTAMPDIFF(MINUTE, r.date_submitted, h.reviewed_at))/60, 2) AS avg_review_hours,
                       ROUND(AVG(CASE WHEN r.executive_decided_at IS NOT NULL AND r.ready_for_release_at IS NOT NULL
                                      THEN TIMESTAMPDIFF(MINUTE, r.executive_decided_at, r.ready_for_release_at) END)/60, 2) AS avg_approval_to_release_hours
                FROM requests r
                LEFT JOIN (
                    SELECT request_id, MIN(created_at) AS reviewed_at
                    FROM request_history WHERE action='Initial Review' GROUP BY request_id
                ) h ON h.request_id=r.id
                WHERE r.status='Issued / Completed' AND r.issued_at IS NOT NULL
                GROUP BY r.request_type ORDER BY r.request_type""")
            report_processing_summary = cursor.fetchall()
            cursor.execute("""SELECT COUNT(*) AS completed_requests,
                       ROUND(AVG(TIMESTAMPDIFF(MINUTE,date_submitted,issued_at))/60,2) AS avg_total_hours
                       FROM requests WHERE status='Issued / Completed' AND issued_at IS NOT NULL""")
            report_processing_overall = cursor.fetchone() or {'completed_requests':0,'avg_total_hours':None}

        conn.close()
    except Exception as e:
        print(f"Admin Route Error: {e}")
        return render_template('admin.html',
                               metrics={'total_homeowners': 0, 'total_requests': 0, 'pending_requests': 0,
                                        'pending_executive': 0, 'active_officers': 0, 'pending_fee_changes': 0,
                                        'open_concerns': 0, 'ready_for_payment_release': 0,
                                        'ready_for_release': 0, 'completed_requests': 0},
                               audits=[], officers=[], homeowners=[], requests=[], fees={}, cancellations=[],
                               financial_adjustments=[], notifications_log=[], current_user=None, pending_homeowners=[], service_types=[], document_templates=[], import_history=[], report_processing_summary=[], report_processing_overall={'completed_requests':0,'avg_total_hours':None})

    if 'full_name' not in session:
        session['full_name'] = session.get('username', 'System Admin')

    metrics = {
        'total_homeowners': total_homeowners, 'total_requests': total_requests,
        'pending_requests': pending_requests, 'pending_executive': pending_executive,
        'active_officers': active_officers, 'pending_fee_changes': pending_fee_changes,
        'open_concerns': open_concerns, 'ready_for_payment_release': ready_for_payment_release,
        'ready_for_release': ready_for_release, 'completed_requests': completed_requests
    }

    return render_template('admin.html', metrics=metrics, audits=audits_rows,
                           officers=officers, homeowners=homeowners, requests=requests_list, fees=fees,
                           cancellations=cancellations, financial_adjustments=financial_adjustments,
                           notifications_log=notifications_log, current_user=current_user, pending_homeowners=pending_homeowners,
                           service_types=service_types, document_templates=document_templates, import_history=import_history,
                           report_processing_summary=report_processing_summary,
                           report_processing_overall=report_processing_overall)


# ===========================================================================
# OFFICER WORKFLOW ENDPOINTS
# ===========================================================================
@app.route('/officer/check_request/<req_id>', methods=['POST'])
def check_request(req_id):
    """Perform the Secretary/Treasurer initial-review action atomically.

    This route is the authoritative transition for Check/Forward, For Correction,
    and initial-review Rejection. It intentionally locks the request row so two
    shared reviewers cannot process the same request at the same time.
    """
    if 'user_id' not in session or session.get('role') not in ['Secretary', 'Treasurer']:
        return redirect(url_for('index'))

    role = session.get('role')
    action = (request.form.get('action') or '').strip().lower()
    remarks = (request.form.get('remarks') or '').strip()
    rejection_reason = (request.form.get('rejection_reason') or '').strip()
    rejection_details = (request.form.get('rejection_details') or '').strip()

    def back_to_review():
        return redirect(url_for('request_review', req_id=req_id))

    if action not in ('check', 'correction', 'reject'):
        flash('Choose a valid initial-review action and try again.', 'error')
        return back_to_review()
    if action == 'correction' and not remarks:
        flash('Officer Remarks are required before a request can be returned For Correction.', 'error')
        return back_to_review()

    allowed_reject_reasons = {
        'Invalid supporting document', 'Request information is inconsistent',
        'Applicant is not eligible for the requested service', 'Duplicate request',
        'Incorrect property information', 'HOA policy restriction', 'Other'
    }
    if action == 'reject':
        if rejection_reason not in allowed_reject_reasons:
            flash('Select a valid rejection reason.', 'error')
            return back_to_review()
        if rejection_reason == 'Other' and not rejection_details:
            flash('Please provide the rejection reason.', 'error')
            return back_to_review()

    correction_delivery = None
    homeowner_notice = None
    prev_req = None
    prev_status = None
    new_status = None
    ready_now = False
    conn = None
    try:
        conn = get_db_connection(autocommit=False)
        with conn.cursor() as cursor:
            cursor.execute("""SELECT status, request_type, user_id, assigned_officer, fee, payment_status,
                                      edit_access_expires_at, edit_access_expired_at
                              FROM requests WHERE id=%s FOR UPDATE""", (req_id,))
            prev_req = cursor.fetchone()
            if not prev_req:
                conn.rollback(); flash('Request not found.', 'error'); return redirect(url_for('officer'))

            prev_status = prev_req['status']
            if prev_status == 'Cancelled':
                conn.rollback(); flash('Cannot process a cancelled request.', 'error'); return back_to_review()
            if prev_status not in ('Submitted', 'Under Review'):
                conn.rollback(); flash('This request is no longer available for initial review. Refresh to see its latest status.', 'warning'); return back_to_review()
            if _request_edit_access_active(prev_req):
                conn.rollback(); flash('The homeowner currently has temporary edit access. Wait for the revised information or for the edit window to expire before reviewing this request.', 'warning'); return back_to_review()

            service = get_service_config(cursor, prev_req['request_type'], active_only=False)
            allowed = service_reviewer_roles(service, prev_req['request_type'])
            if role not in allowed:
                conn.rollback(); flash(f'{role} is not authorized to perform the initial checking for {prev_req["request_type"]}.', 'error'); return back_to_review()

            # Shared-review services are visible to both roles until one officer
            # performs an action. Once ownership exists, only that reviewer may act.
            current_owner = prev_req.get('assigned_officer')
            if service and service.get('initial_reviewer') == 'Shared' and current_owner in {'Secretary','Treasurer'} and role != current_owner:
                conn.rollback(); flash(f'This shared request is already being handled by the {current_owner}.', 'warning'); return back_to_review()

            checker = role
            if action == 'correction':
                new_status = 'For Correction'
            elif action == 'reject':
                new_status = 'Rejected'
                remarks = rejection_details if rejection_reason == 'Other' else rejection_reason
            else:
                requires_executive = False if prev_req['request_type'] == 'Statement of Account' else (True if not service else bool(service.get('requires_executive')))
                requires_payment = bool(float(prev_req.get('fee') or 0) > 0) if not service else bool(service.get('requires_payment')) and float(prev_req.get('fee') or 0) > 0
                requires_dues = False if prev_req['request_type'] == 'Statement of Account' else (True if not service else bool(service.get('requires_dues_clearance')))
                dues = dues_summary(cursor, prev_req['user_id']) if requires_dues else {'unpaid_months': 0}
                if requires_dues and dues.get('unpaid_months', 0) > 0:
                    conn.rollback()
                    flash('Outstanding monthly dues are recorded for this homeowner. Resolve the dues before forwarding the request, or reject it during initial review when appropriate.', 'warning')
                    return back_to_review()
                if requires_executive:
                    new_status = 'Pending Executive Approval'
                elif requires_payment:
                    new_status = 'Ready for Payment & Release'
                    homeowner_notice = ('Request Ready for Payment & Release',
                        f"Your {prev_req['request_type']} request {req_id} passed review. The document is being prepared and may be paid for and released during one face-to-face visit with the Treasurer.")
                else:
                    new_status = 'Ready for Release'
                    ready_now = True
                    homeowner_notice = ('Request Ready for Release',
                        f"Your {prev_req['request_type']} request {req_id} passed review and is now Ready for Release.")

            sql = """UPDATE requests
                     SET status=%s, remarks=%s, assigned_officer=%s,
                         edit_access_granted_at=NULL, edit_access_expires_at=NULL,
                         edit_access_granted_by=NULL, edit_access_reason=NULL,
                         edit_access_expired_at=NULL"""
            params = [new_status, remarks or None, checker]
            if ready_now:
                sql += ", ready_for_release_at=NOW(), payment_status='Not Required'"
            sql += " WHERE id=%s AND status IN ('Submitted','Under Review')"
            params.append(req_id)
            cursor.execute(sql, tuple(params))
            if cursor.rowcount != 1:
                conn.rollback()
                flash('This request was already processed by another officer. Refresh to see its current status.', 'warning')
                return back_to_review()
            if action == 'reject':
                cursor.execute("SELECT id FROM nfh_advance_promo_redemptions WHERE request_id=%s",(req_id,))
                if cursor.fetchone():
                    cursor.execute("INSERT INTO audit_logs(username,role,action,item,prev_val,new_val) VALUES (%s,%s,'Restore Promo Certificate Credit',%s,'Reserved','Available')",
                                   (session.get('username'),role,req_id))
            if action == 'check':
                assign_request_document_template(cursor, req_id, prev_req['request_type'])
        conn.commit()
    except Exception:
        if conn:
            try: conn.rollback()
            except Exception: pass
        app.logger.exception('Initial review action failed for %s', req_id)
        flash('Unable to update the request right now. Please try again.', 'error')
        return back_to_review()
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

    record_request_history(
        req_id,
        'Initial Review' if action == 'check' else ('Returned for Correction' if action == 'correction' else 'Officer Rejected'),
        prev_status, new_status, remarks,
        session.get('full_name') or session.get('username'), role
    )
    log_audit_action(session.get('username'), role, f'Request {action.title()}', req_id, prev_status, new_status)

    if new_status == 'For Correction':
        homeowner_name = 'Homeowner'
        try:
            c2 = get_db_connection()
            with c2.cursor() as cursor:
                cursor.execute("SELECT first_name, last_name FROM users WHERE id=%s", (prev_req['user_id'],))
                homeowner = cursor.fetchone()
            c2.close()
            if homeowner:
                homeowner_name = f"{homeowner.get('first_name') or ''} {homeowner.get('last_name') or ''}".strip() or 'Homeowner'
        except Exception as exc:
            app.logger.warning('Could not resolve homeowner name for correction email %s: %s', req_id, exc)
        subject = f'NFH-HOA Request Requires Correction — {req_id}'
        body = (
            f"Dear {homeowner_name},\n\nYour {prev_req['request_type']} request ({req_id}) requires correction.\n\n"
            f"Status: For Correction\nOfficer Remarks: {remarks}\n\n"
            "Please sign in to the NFH-HOA system to review the remarks, make the necessary corrections, and resubmit your request.\n\n"
            "Thank you,\nNorth Fairway Homes Homeowners' Association"
        )
        correction_delivery = send_alert_and_email(
            prev_req['user_id'], subject, body, related_type='request', related_id=req_id,
            dedupe_key=f"correction-{req_id}-{prev_status}-{int(time.time())}"
        )
    elif new_status == 'Rejected':
        body = (f"Your {prev_req['request_type']} request {req_id} was rejected during officer review.\n\nReason: {remarks}\n\n"
                "Please sign in to the NFH-HOA portal to review the recorded decision.")
        send_alert_and_email(prev_req['user_id'], f'NFH-HOA | Document Request Status Update — {req_id}', body,
                             related_type='request', related_id=req_id,
                             dedupe_key=f'rejected-{req_id}-{int(time.time())}')
    elif homeowner_notice:
        send_alert_and_email(prev_req['user_id'], homeowner_notice[0], homeowner_notice[1],
                             related_type='request', related_id=req_id,
                             dedupe_key=f'review-progress-{req_id}-{new_status}')

    if action == 'correction':
        flash('Request moved to For Correction. It has been removed from the initial-review queue and the homeowner can now revise the same Request ID.', 'success')
        if correction_delivery and not correction_delivery.get('email_sent'):
            flash('The in-app correction notice was saved, but email delivery was unavailable.', 'warning')
        return redirect(url_for('request_review', req_id=req_id))
    if action == 'reject':
        flash('Request rejected during initial review.', 'success')
    else:
        flash(f'Request checked and forwarded to {new_status}.', 'success')
    return redirect(url_for('officer'))


@app.route('/officer/update_payment/<req_id>', methods=['POST'])
def update_payment(req_id):
    """Record face-to-face cash payment and optionally confirm document release in the same visit."""
    if 'user_id' not in session or session.get('role') not in ['Treasurer','Admin']:
        return redirect(url_for('index'))
    payment_date=(request.form.get('payment_date') or '').strip() or datetime.now().strftime('%Y-%m-%d')
    or_no=(request.form.get('official_receipt_no') or '').strip()
    release_now=str(request.form.get('document_released') or '').lower() in {'1','true','yes','on'}
    if not or_no:
        flash('Official Receipt Number is required for a recorded face-to-face cash payment.', 'error')
        return redirect(url_for('officer') + '#payments')
    if len(or_no) > 120:
        flash('Official Receipt Number is too long.', 'error')
        return redirect(url_for('officer') + '#payments')
    remarks=(request.form.get('release_remarks') or '').strip()
    sticker_from=(request.form.get('sticker_valid_from') or '').strip()
    sticker_until=(request.form.get('sticker_valid_until') or '').strip()
    try:
        paid_date=datetime.strptime(payment_date,'%Y-%m-%d').date()
    except ValueError:
        flash('Enter a valid payment date.','error')
        return redirect(url_for('officer') + '#payments')

    try:
        conn=get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""SELECT r.*, CONCAT(u.first_name,' ',u.last_name) AS homeowner
                              FROM requests r JOIN users u ON u.id=r.user_id WHERE r.id=%s""",(req_id,))
            req=cursor.fetchone()
            if not req:
                conn.close(); flash('Request not found.','error'); return redirect(url_for('officer') + '#payments')
            if req['payment_status'] == 'Paid':
                conn.close(); flash('Payment for this request has already been recorded.','warning'); return redirect(url_for('officer') + '#payments')
            if req['status'] not in ('Ready for Payment & Release','Awaiting Payment Verification','Approved'):
                conn.close(); flash('This request is not yet ready for face-to-face payment and release.','error'); return redirect(url_for('officer') + '#payments')
            if req['request_type'] == 'Statement of Account' and session.get('role') != 'Treasurer':
                conn.close(); flash('Only the Treasurer can process SOA payment and release.','error'); return redirect(url_for('officer') + '#payments')
            service=get_service_config(cursor,req['request_type'],active_only=False)
            requires_payment=(float(req.get('fee') or 0)>0) if not service else (bool(service.get('requires_payment')) and float(req.get('fee') or 0)>0)
            if not requires_payment:
                conn.close(); flash('This request does not require a payment transaction.','error'); return redirect(url_for('officer') + '#payments')
            cursor.execute("SELECT request_id FROM payment_transactions WHERE LOWER(official_receipt_no)=LOWER(%s) LIMIT 1", (or_no,))
            duplicate_or = cursor.fetchone()
            if duplicate_or:
                conn.close()
                flash(f'Official Receipt Number {or_no} is already recorded for request {duplicate_or["request_id"]}. Use the actual unique physical receipt number.', 'error')
                return redirect(url_for('officer') + '#payments')
            assign_request_document_template(cursor, req_id, req['request_type'])

            valid_from=None; valid_until=None
            is_vehicle = bool(service and service.get('form_template')=='vehicle-sticker') or req['request_type']=='Vehicle Sticker Application'
            if release_now and is_vehicle:
                if not sticker_from or not sticker_until:
                    conn.close(); flash('Enter the vehicle sticker validity dates before confirming release.','error'); return redirect(url_for('officer') + '#payments')
                try:
                    valid_from=datetime.strptime(sticker_from,'%Y-%m-%d').date()
                    valid_until=datetime.strptime(sticker_until,'%Y-%m-%d').date()
                except ValueError:
                    conn.close(); flash('Enter valid sticker validity dates.','error'); return redirect(url_for('officer') + '#payments')
                if valid_until < valid_from:
                    conn.close(); flash('Sticker expiration date cannot be earlier than its start date.','error'); return redirect(url_for('officer') + '#payments')

            receiver=session.get('full_name') or session.get('username') or 'Treasurer'
            cursor.execute("""INSERT INTO payment_transactions
                (request_id,user_id,amount,payment_method,official_receipt_no,payment_date,received_by,
                 document_released,released_by,released_at,remarks)
                VALUES (%s,%s,%s,'Cash',%s,%s,%s,%s,%s,%s,%s)""",
                (req_id,req['user_id'],float(req.get('fee') or 0),or_no or None,paid_date,receiver,
                 1 if release_now else 0, receiver if release_now else None,
                 datetime.now() if release_now else None, remarks or None))
            tx_id=cursor.lastrowid
            system_ref=_ensure_payment_reference(cursor, tx_id)
            new_status='Issued / Completed' if release_now else 'Paid - Awaiting Release'
            cursor.execute("""UPDATE requests SET payment_status='Paid',status=%s,
                              payment_reference=%s,official_receipt_no=%s,payment_date=%s,
                              ready_for_release_at=COALESCE(ready_for_release_at,NOW()),
                              issued_at=%s,issued_by=%s,sticker_valid_from=%s,sticker_valid_until=%s
                              WHERE id=%s""",
                           (new_status,system_ref,or_no or None,paid_date,
                            datetime.now() if release_now else None, receiver if release_now else None,
                            valid_from,valid_until,req_id))
            if release_now:
                template=get_active_document_template(cursor,request_type=req['request_type'])
                snapshot_request_signatures(cursor,req_id,template)
        conn.close()

        record_request_history(req_id,'Cash Payment Received',req['status'],new_status,
                               f'Cash payment ₱{float(req.get("fee") or 0):.2f}; Reference {system_ref}.')
        log_audit_action(session.get('username'),session.get('role'),'Record Cash Payment',req_id,req['status'],new_status)
        if release_now:
            release_note='Document physically handed to homeowner during face-to-face payment.'
            if remarks: release_note += f' {remarks}'
            record_request_history(req_id,'Document Released',new_status,'Issued / Completed',release_note)
            log_audit_action(session.get('username'),session.get('role'),'Confirm Payment & Release',req_id,'Payment Received','Issued / Completed')
            send_in_app_notification(req['user_id'],'Payment and Release Completed',
                f'Your {req["request_type"]} request {req_id} was paid and physically released. Reference: {system_ref}.',
                related_type='request',related_id=req_id,dedupe_key=f'pay-release-{req_id}')
            flash(f'Payment recorded and document released. Reference {system_ref}.','success')
        else:
            send_in_app_notification(req['user_id'],'Payment Recorded',
                f'Your cash payment for {req["request_type"]} request {req_id} was recorded. The document is still awaiting physical release.',
                related_type='request',related_id=req_id,dedupe_key=f'payment-only-{req_id}')
            flash(f'Payment recorded. Request is now Paid - Awaiting Release. Reference {system_ref}.','success')
    except pymysql.IntegrityError:
        app.logger.exception('Duplicate payment transaction for %s', req_id)
        flash('A payment transaction for this request already exists. Refresh the queue before trying again.','warning')
    except Exception:
        app.logger.exception('Face-to-face payment/release failed for %s', req_id)
        flash('Unable to record the payment/release right now. Please try again.','error')
    return redirect(url_for('officer') + '#payments')


@app.route('/officer/complete_release/<req_id>', methods=['POST'])
def complete_paid_release(req_id):
    """Confirm physical hand-over when payment was recorded earlier."""
    if 'user_id' not in session or session.get('role') not in ['Treasurer','Admin','Secretary']:
        return redirect(url_for('index'))
    remarks=(request.form.get('release_remarks') or '').strip()
    sticker_from=(request.form.get('sticker_valid_from') or '').strip()
    sticker_until=(request.form.get('sticker_valid_until') or '').strip()
    try:
        conn=get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM requests WHERE id=%s",(req_id,)); req=cursor.fetchone()
            if not req or req['status']!='Paid - Awaiting Release' or req['payment_status']!='Paid':
                conn.close(); flash('This request is not waiting for release confirmation.','error'); return redirect(url_for('officer')+'#payments')
            if req['request_type'] == 'Statement of Account' and session.get('role') != 'Treasurer':
                conn.close(); flash('Only the Treasurer can release an SOA.','error'); return redirect(url_for('officer')+'#payments')
            service=get_service_config(cursor,req['request_type'],active_only=False)
            valid_from=None; valid_until=None
            is_vehicle=bool(service and service.get('form_template')=='vehicle-sticker') or req['request_type']=='Vehicle Sticker Application'
            if is_vehicle:
                if not sticker_from or not sticker_until:
                    conn.close(); flash('Sticker validity dates are required before release.','error'); return redirect(url_for('officer')+'#payments')
                valid_from=datetime.strptime(sticker_from,'%Y-%m-%d').date(); valid_until=datetime.strptime(sticker_until,'%Y-%m-%d').date()
                if valid_until < valid_from:
                    conn.close(); flash('Sticker expiration date cannot be earlier than its start date.','error'); return redirect(url_for('officer')+'#payments')
            releaser=session.get('full_name') or session.get('username') or session.get('role')
            cursor.execute("""UPDATE requests SET status='Issued / Completed',issued_at=NOW(),issued_by=%s,
                              sticker_valid_from=%s,sticker_valid_until=%s WHERE id=%s""",
                           (releaser,valid_from,valid_until,req_id))
            cursor.execute("""UPDATE payment_transactions SET document_released=1,released_by=%s,released_at=NOW(),
                              remarks=CONCAT_WS(' | ',remarks,%s) WHERE request_id=%s""",(releaser,remarks or None,req_id))
            template=get_active_document_template(cursor,request_type=req['request_type'])
            snapshot_request_signatures(cursor,req_id,template)
        conn.close()
        record_request_history(req_id,'Document Released','Paid - Awaiting Release','Issued / Completed',remarks or 'Physical document handed to homeowner.')
        log_audit_action(session.get('username'),session.get('role'),'Confirm Document Release',req_id,'Paid - Awaiting Release','Issued / Completed')
        send_in_app_notification(req['user_id'],'Document Released',
            f'Your {req["request_type"]} request {req_id} has been physically released and is now completed.',
            related_type='request',related_id=req_id,dedupe_key=f'release-after-payment-{req_id}')
        flash('Document release confirmed. Request is now Issued / Completed.','success')
    except Exception:
        app.logger.exception('Paid release confirmation failed for %s',req_id)
        flash('Unable to confirm release right now.','error')
    return redirect(url_for('officer')+'#payments')


@app.route('/officer/propose_fee', methods=['POST'])
def propose_fee():
    if 'user_id' not in session or session.get('role') not in ['Treasurer', 'Admin']:
        return redirect(url_for('index'))
    fee_name = (request.form.get('fee_name') or '').strip()
    amount_raw = (request.form.get('amount') or '').strip()
    try:
        amount = float(amount_raw)
        if amount < 0:
            raise ValueError
    except (TypeError, ValueError):
        flash('Enter a valid non-negative proposed fee.', 'error')
        return redirect(url_for('officer'))
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT amount FROM fees WHERE item_name=%s", (fee_name,))
            row = cursor.fetchone()
            if not row:
                conn.close(); flash('Fee item not found.', 'error'); return redirect(url_for('officer'))
            prev = float(row['amount'])
            cursor.execute("UPDATE fees SET proposed_amount=%s, status='Pending Executive Approval' WHERE item_name=%s",
                           (amount, fee_name))
        conn.close()
        log_audit_action(session.get('username'), session.get('role'), 'Propose Fee Update', fee_name, prev, amount)
        flash(f'Proposed fee for {fee_name} submitted for Executive approval.', 'success')
    except Exception as e:
        app.logger.exception('Fee proposal failed')
        flash('Unable to submit the fee proposal right now.', 'error')
    return redirect(url_for('officer'))


@app.route('/officer/update-treasurer-contact', methods=['POST'])
def update_treasurer_contact():
    if 'user_id' not in session or session.get('role') not in ['Treasurer', 'Admin']:
        return redirect(url_for('index'))
    name = request.form.get('treasurer_name', '').strip()
    phone = request.form.get('treasurer_phone', '').strip()
    email = request.form.get('treasurer_email', '').strip()
    office_hours = request.form.get('treasurer_office_hours', '').strip()
    if not name or not phone:
        flash('Treasurer name and contact number are required.', 'error')
        return redirect(url_for('officer'))
    try:
        who = session.get('username')
        set_setting('treasurer_name', name, who)
        set_setting('treasurer_phone', phone, who)
        set_setting('treasurer_email', email, who)
        set_setting('treasurer_office_hours', office_hours, who)
        log_audit_action(who, session.get('role'), 'Update Treasurer Contact Info', 'hoa_settings', None, name)
        flash('Treasurer contact information updated.', 'success')
    except Exception as e:
        app.logger.exception('Treasurer contact update failed')
        flash('Unable to update the Treasurer contact information right now.', 'error')
    return redirect(url_for('officer'))


@app.route('/officer/president_action/<req_id>', methods=['POST'])
def president_action(req_id):
    """Executive Approvers record the final approval only.

    Rejection belongs to the Secretary/Treasurer initial-review stage so invalid,
    incomplete, duplicate, or ineligible requests do not reach Executive approval.
    """
    if 'user_id' not in session or session.get('role') not in EXECUTIVE_ROLES:
        return redirect(url_for('index'))
    action = request.form.get('action')
    if action != 'approve':
        flash('Executive Approvers can approve final requests only. Rejection is handled during initial review.', 'error')
        return redirect(request.referrer or url_for('officer'))
    mail_result = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""SELECT r.status, r.payment_status, r.request_type, r.user_id,
                              CONCAT(u.first_name,' ',u.last_name) AS homeowner, r.fee,
                              r.edit_access_expires_at, r.edit_access_expired_at
                       FROM requests r JOIN users u ON u.id=r.user_id WHERE r.id=%s""", (req_id,))
            req = cursor.fetchone()
            if not req or req['status'] != 'Pending Executive Approval':
                conn.close(); flash('This request is no longer pending Executive approval. Refresh the page to view the latest status.', 'error'); return redirect(request.referrer or url_for('officer'))
            if _request_edit_access_active(req):
                conn.close(); flash('Executive approval is temporarily suspended because the homeowner has active edit access. Review the revised information after the edit is submitted or the window expires.', 'warning'); return redirect(request.referrer or url_for('request_review', req_id=req_id))
            service = get_service_config(cursor, req['request_type'], active_only=False)
            requires_dues = False if req['request_type'] == 'Statement of Account' else (True if not service else bool(service.get('requires_dues_clearance')))
            requires_payment = bool(float(req.get('fee') or 0) > 0) if not service else bool(service.get('requires_payment')) and float(req.get('fee') or 0) > 0
            dues = dues_summary(cursor, req['user_id']) if requires_dues else {'unpaid_months': 0}
            if requires_dues and dues.get('unpaid_months', 0) > 0:
                # Dues should have been clear at initial review. If they changed afterward,
                # keep the request pending rather than recording an Executive approval on
                # an ineligible request. Treasurer settlement can clear the issue first.
                conn.close()
                flash('This homeowner currently has outstanding monthly dues. Clear the dues before recording Executive approval.', 'warning')
                return redirect(request.referrer or url_for('request_review', req_id=req_id))
            prev_status = req['status']
            if requires_payment:
                new_status = 'Ready for Payment & Release'
            else:
                new_status = 'Ready for Release'
            assign_request_document_template(cursor, req_id, req['request_type'])
            sql = """UPDATE requests SET status=%s, remarks=NULL,
                     executive_decision_reason=NULL, executive_decision_details=NULL,
                     executive_decided_by=%s, executive_decided_role=%s, executive_decided_at=NOW()"""
            params = [new_status, session.get('full_name') or session.get('username'), session.get('role')]
            if not requires_payment and new_status == 'Ready for Release':
                sql += ", payment_status='Not Required', ready_for_release_at=NOW()"
            elif new_status == 'Ready for Payment & Release':
                sql += ", ready_for_release_at=NOW()"
            sql += " WHERE id=%s"
            params.append(req_id)
            cursor.execute(sql, tuple(params))
        conn.close()
        mail_result = send_approval_email(
            req_id, req['request_type'], req['user_id'],
            session.get('full_name') or session.get('username') or 'HOA Executive',
            session.get('role') or 'Executive'
        )
        if new_status == 'Ready for Release':
            send_alert_and_email(req['user_id'], 'Request Ready for Release',
                f"Your {req['request_type']} request {req_id} has completed approval and is now Ready for Release.",
                related_type='request', related_id=req_id, dedupe_key=f'ready-release-{req_id}')
        elif new_status == 'Ready for Payment & Release':
            send_alert_and_email(req['user_id'], 'Ready for Payment & Release',
                f"Your {req['request_type']} request {req_id} is approved. Please visit the Treasurer for face-to-face payment and document release.",
                related_type='request', related_id=req_id, dedupe_key=f'pay-release-ready-{req_id}')
        elif new_status == 'Awaiting Dues Clearance':
            send_alert_and_email(req['user_id'], 'Request Approved — Dues Clearance Required',
                f"Your {req['request_type']} request {req_id} is approved but must clear outstanding monthly dues with the Treasurer before payment/release.",
                related_type='request', related_id=req_id, dedupe_key=f'dues-clearance-{req_id}')
        record_request_history(req_id, 'Executive Approved', prev_status, new_status,
                               'Final Executive approval recorded.')
        log_audit_action(session.get('username'), session.get('role'), 'Executive Approval', req_id,
                         prev_status, new_status)
        flash('Request approved successfully.', 'success')
        if mail_result and not mail_result.get('email_sent'):
            flash('The approval was saved and the in-app notification was created, but the email could not be delivered.', 'warning')
    except Exception:
        app.logger.exception('Executive approval error for %s', req_id)
        flash('Unable to record the Executive approval. Please try again.', 'error')
    return redirect(request.referrer or url_for('officer'))


@app.route('/officer/president_fee_action', methods=['POST'])
def president_fee_action():
    if 'user_id' not in session or session.get('role') not in EXECUTIVE_ROLES:
        return redirect(url_for('index'))
    fee_name = (request.form.get('fee_name') or '').strip()
    action = request.form.get('action')
    if action not in ('approve', 'reject'):
        flash('Invalid fee decision.', 'error')
        return redirect(url_for('officer'))
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT amount, proposed_amount, status FROM fees WHERE item_name=%s", (fee_name,))
            fee = cursor.fetchone()
            if not fee or fee.get('proposed_amount') is None:
                conn.close(); flash('No pending fee proposal was found for this item.', 'warning'); return redirect(url_for('officer'))
            proposed = float(fee['proposed_amount'])
            if action == 'approve':
                cursor.execute(
                    "UPDATE fees SET amount=%s, proposed_amount=NULL, status='Active' WHERE item_name=%s",
                    (proposed, fee_name))
                # service_types is the authoritative request configuration; keep
                # any matching service fee synchronized with the approved fee.
                cursor.execute("UPDATE service_types SET fee=%s WHERE service_name=%s", (proposed, fee_name))
                log_audit_action(session.get('username'), session.get('role'), 'Approve Fee Update', fee_name,
                                 fee['amount'], proposed)
                flash(f'Fee update for {fee_name} approved and activated.', 'success')
            else:
                cursor.execute("UPDATE fees SET proposed_amount=NULL, status='Active' WHERE item_name=%s", (fee_name,))
                log_audit_action(session.get('username'), session.get('role'), 'Reject Fee Update', fee_name,
                                 fee['proposed_amount'], 'Rejected')
                flash(f'Fee proposal for {fee_name} rejected.', 'info')
        conn.close()
    except Exception as e:
        app.logger.exception('Fee approval failed for %s', fee_name)
        flash('Unable to process the fee decision right now.', 'error')
    return redirect(url_for('officer'))


# ===========================================================================
# OWNER APIS

# ===========================================================================


# ===========================================================================
# ROLE-AWARE LIVE DASHBOARD METRICS (lightweight polling endpoint)
# ===========================================================================
@app.route('/api/live-metrics', methods=['GET'])
def live_metrics():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    role = session.get('role')
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            def count(sql, params=()):
                cursor.execute(sql, params)
                return int(cursor.fetchone()['total'] or 0)

            cursor.execute("SELECT service_name,initial_reviewer,release_role FROM service_types WHERE status='Active'")
            services = cursor.fetchall()
            secretary_types = [s['service_name'] for s in services if s['initial_reviewer'] in ('Secretary','Shared')]
            treasurer_types = [s['service_name'] for s in services if s['initial_reviewer'] in ('Treasurer','Shared')]

            if role == 'Admin':
                metrics = {
                    'total_homeowners': count("SELECT COUNT(*) total FROM users WHERE role='Homeowner' AND verification_status='Verified' AND status='Active'"),
                    'total_requests': count("SELECT COUNT(*) total FROM requests"),
                    'pending_requests': count("SELECT COUNT(*) total FROM requests WHERE status IN ('Submitted','Under Review','Awaiting Dues Clearance')"),
                    'pending_executive': count("SELECT COUNT(*) total FROM requests WHERE status='Pending Executive Approval' AND (edit_access_expires_at IS NULL OR edit_access_expires_at<=NOW())"),
                    'active_officers': count("SELECT COUNT(*) total FROM users WHERE role IN ('Secretary','Treasurer','President','Vice President','Board Director') AND status='Active'"),
                    'pending_fee_changes': count("SELECT COUNT(*) total FROM fees WHERE status='Pending Executive Approval'"),
                    'approved_requests': count("SELECT COUNT(*) total FROM requests WHERE status IN ('Ready for Payment & Release','Paid - Awaiting Release','Ready for Release','Issued / Completed')"),
                    'paid_requests': count("SELECT COUNT(*) total FROM requests WHERE payment_status='Paid'"),
                    'missing_dues': count("SELECT COUNT(*) total FROM monthly_dues WHERE status='Unpaid'"),
                    'open_concerns': count("SELECT COUNT(*) total FROM request_concerns WHERE status IN ('Open','Under Review')"),
                    'ready_for_payment_release': count("SELECT COUNT(*) total FROM requests WHERE status='Ready for Payment & Release' AND payment_status='Unpaid'"),
                    'ready_for_release': count("SELECT COUNT(*) total FROM requests WHERE status='Ready for Release'"),
                    'completed_requests': count("SELECT COUNT(*) total FROM requests WHERE status='Issued / Completed'"),
                }
            elif role == 'Secretary':
                types = secretary_types or list(SECRETARY_FIRST_REQUEST_TYPES | SHARED_INITIAL_CHECK_REQUEST_TYPES)
                placeholders = ','.join(['%s']*len(types))
                base_params = tuple(types)
                metrics = {
                    'pending_requests': count(f"SELECT COUNT(*) total FROM requests WHERE status IN ('Submitted','Under Review') AND (edit_access_expires_at IS NULL OR edit_access_expires_at<=NOW()) AND request_type IN ({placeholders}) AND (assigned_officer IS NULL OR assigned_officer IN ('Secretary',''))", base_params),
                    'for_correction': count(f"SELECT COUNT(*) total FROM requests WHERE status='For Correction' AND request_type IN ({placeholders}) AND (assigned_officer IS NULL OR assigned_officer='Secretary')", base_params),
                    'pending_executive': count("SELECT COUNT(*) total FROM requests WHERE status='Pending Executive Approval' AND (edit_access_expires_at IS NULL OR edit_access_expires_at<=NOW())"),
                    'recent_submitted': count("SELECT COUNT(*) total FROM requests WHERE status='Submitted' AND date_submitted >= NOW() - INTERVAL 7 DAY"),
                    'request_concerns': count("SELECT COUNT(*) total FROM request_concerns WHERE assigned_role='Secretary' AND status IN ('Open','Under Review')"),
                    'ready_for_release': count("SELECT COUNT(*) total FROM requests r LEFT JOIN service_types s ON s.service_name=r.request_type WHERE r.status='Ready for Release' AND (s.release_role='Secretary' OR s.release_role IS NULL OR (s.release_role='Initial Reviewer' AND (r.assigned_officer='Secretary' OR (r.assigned_officer IS NULL AND s.initial_reviewer IN ('Secretary','Shared')))))"),
                }
            elif role in EXECUTIVE_ROLES:
                metrics = {
                    'pending_request_approvals': count("SELECT COUNT(*) total FROM requests WHERE status='Pending Executive Approval' AND (edit_access_expires_at IS NULL OR edit_access_expires_at<=NOW())"),
                    'pending_fee_approvals': count("SELECT COUNT(*) total FROM fees WHERE status='Pending Executive Approval'"),
                    'recently_approved': count("SELECT COUNT(*) total FROM requests WHERE executive_decided_at IS NOT NULL AND executive_decision_reason IS NULL AND executive_decided_at >= NOW() - INTERVAL 7 DAY"),
                    'for_correction': count("SELECT COUNT(*) total FROM requests WHERE status='For Correction'"),
                    'pending_executive': count("SELECT COUNT(*) total FROM requests WHERE status='Pending Executive Approval' AND (edit_access_expires_at IS NULL OR edit_access_expires_at<=NOW())"),
                    'pending_fee_changes': count("SELECT COUNT(*) total FROM fees WHERE status='Pending Executive Approval'"),
                }
            elif role == 'Treasurer':
                cursor.execute("SELECT COALESCE(SUM(amount),0) total FROM monthly_dues WHERE status='Unpaid'")
                outstanding = float(cursor.fetchone()['total'] or 0)
                types = treasurer_types or list(TREASURER_FIRST_REQUEST_TYPES | SHARED_INITIAL_CHECK_REQUEST_TYPES)
                placeholders = ','.join(['%s']*len(types))
                base_params = tuple(types)
                metrics = {
                    'requests_for_checking': count(f"SELECT COUNT(*) total FROM requests WHERE status IN ('Submitted','Under Review') AND (edit_access_expires_at IS NULL OR edit_access_expires_at<=NOW()) AND request_type IN ({placeholders}) AND (assigned_officer IS NULL OR assigned_officer='Treasurer')", base_params),
                    'for_correction': count(f"SELECT COUNT(*) total FROM requests WHERE status='For Correction' AND request_type IN ({placeholders}) AND assigned_officer='Treasurer'", base_params),
                    'approved_unpaid': count("SELECT COUNT(*) total FROM requests WHERE status='Ready for Payment & Release' AND payment_status='Unpaid'"),
                    'paid_requests': count("SELECT COUNT(*) total FROM requests WHERE payment_status='Paid'"),
                    'missing_dues': count("SELECT COUNT(*) total FROM monthly_dues WHERE status='Unpaid'"),
                    'outstanding_dues_total': outstanding,
                    'recently_paid': count("SELECT COUNT(*) total FROM requests WHERE payment_status='Paid' AND last_updated >= NOW() - INTERVAL 7 DAY"),
                    'request_concerns': count("SELECT COUNT(*) total FROM request_concerns WHERE assigned_role='Treasurer' AND status IN ('Open','Under Review')"),
                    'ready_for_payment_release': count("SELECT COUNT(*) total FROM requests WHERE status='Ready for Payment & Release' AND payment_status='Unpaid'"),
                }
            else:
                metrics = {}
        conn.close()
        return jsonify({'status':'success','role':role,'metrics':metrics,'updated_at':datetime.now().strftime('%H:%M:%S')})
    except Exception as e:
        app.logger.exception('Live metrics error')
        return jsonify({'status':'error','message':'Unable to refresh dashboard metrics.'}), 500


@app.route('/api/user-data', methods=['GET'])
def get_user_data():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    user_id = session['user_id']
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
            user = cursor.fetchone()
            cursor.execute("SELECT item_name, amount FROM fees WHERE status='Active'")
            fees_rows = cursor.fetchall()
            fees_dict = {f['item_name']: float(f['amount']) for f in fees_rows}
            cursor.execute("""SELECT id,service_name,category,fee,initial_reviewer,requires_executive,
                                      requires_payment,requires_dues_clearance,purpose_required,
                                      release_role,form_template,description,status
                               FROM service_types WHERE status='Active' OR service_name='Statement of Account'
                               ORDER BY category,service_name""")
            service_rows = cursor.fetchall()
            services=[]
            for svc in service_rows:
                svc=dict(svc)
                svc['fee']=float(svc.get('fee') or 0)
                services.append(svc)
            cursor.execute("SELECT * FROM requests WHERE user_id=%s ORDER BY date_submitted DESC", (user_id,))
            requests_rows = cursor.fetchall()
            # Close any expired temporary edit grants before rendering homeowner actions.
            expired_ids=[r['id'] for r in requests_rows if r.get('edit_access_expires_at') and not r.get('edit_access_expired_at') and r['edit_access_expires_at'] < datetime.now()]
            cursor.execute("""SELECT h.* FROM request_history h JOIN requests r ON r.id=h.request_id
                              WHERE r.user_id=%s ORDER BY h.created_at ASC""", (user_id,))
            history_by_request={}
            for hist in cursor.fetchall():
                hist['created_at']=hist['created_at'].strftime('%Y-%m-%d %H:%M') if hist.get('created_at') else ''
                history_by_request.setdefault(hist['request_id'],[]).append(hist)
            cursor.execute("SELECT * FROM alerts WHERE user_id=%s ORDER BY time DESC", (user_id,))
            alerts_rows = cursor.fetchall()
            cursor.execute("""SELECT * FROM monthly_dues WHERE user_id=%s AND status='Unpaid'
                              ORDER BY due_month ASC""", (user_id,))
            missing_dues_rows = cursor.fetchall()
            # Authoritative historical SOA request obligations, net of verified cash allocations.
            # Legacy request-fee imports are included only when no equivalent SOA entry exists.
            cursor.execute("""
                SELECT CONCAT('HIST-', e.id) AS external_ref, e.description AS request_type,
                       e.transaction_date AS request_date,
                       GREATEST(0, e.amount - COALESCE(SUM(a.amount), 0)) AS amount
                FROM nfh_historical_import_entries e
                LEFT JOIN nfh_historical_cash_allocations a ON a.import_entry_id=e.id
                WHERE e.homeowner_id=%s AND e.transaction_type='Request'
                GROUP BY e.id, e.description, e.transaction_date, e.amount
                HAVING amount > 0
                UNION ALL
                SELECT h.external_ref, h.request_type, h.request_date,
                       GREATEST(0, h.amount - COALESCE((
                           SELECT SUM(r.amount) FROM nfh_historical_fee_receipts r WHERE r.fee_id=h.id
                       ), 0)) AS amount
                FROM nfh_historical_request_fees h
                WHERE h.user_id=%s AND NOT EXISTS (
                    SELECT 1 FROM nfh_historical_import_entries e
                    WHERE e.homeowner_id=h.user_id AND e.external_ref=h.external_ref
                )
            """, (user_id,user_id))
            historical_request_fees=cursor.fetchall()
            cursor.execute("SELECT * FROM payment_transactions WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
            payment_tx_rows = cursor.fetchall()
            payment_tx_map = {row['request_id']: row for row in payment_tx_rows}
        conn.close()
        for _rid in expired_ids:
            _expire_edit_access_for_request(_rid)
        if expired_ids:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM requests WHERE user_id=%s ORDER BY date_submitted DESC", (user_id,))
                requests_rows = cursor.fetchall()
            conn.close()

        if user:
            user.pop('password_hash', None)
            if user.get('profile_image'):
                user['profile_image'] = f"/static/uploads/{os.path.basename(user['profile_image'])}"
            if user.get('dob'):
                user['dob'] = user['dob'].strftime('%Y-%m-%d')
            if user.get('date_joined'):
                user['date_joined'] = user['date_joined'].strftime('%Y-%m-%d')
            user['emergency'] = {
                'name': user.get('emergency_contact_name'),
                'number': user.get('emergency_contact_number'),
                'relationship': user.get('emergency_contact_relationship'),
            }

        req_list, active_count, outstanding_request_fees = [], 0, 0.0
        for r in requests_rows:
            status = r['status']
            payment_status = r['payment_status']
            fee_val = float(r['fee'])
            if status in ['Submitted','Under Review','Checked','Pending Executive Approval','For Correction','Approved','Awaiting Dues Clearance','Awaiting Payment Verification','Ready for Payment & Release','Paid - Awaiting Release','Ready for Release']:
                active_count += 1
            if payment_status == 'Unpaid' and status not in ['Rejected', 'Cancelled', 'Issued / Completed']:
                outstanding_request_fees += fee_val
            req_list.append({
                'id': r['id'], 'type': r['request_type'], 'title': r['request_type'],
                'category': r.get('category') or 'Document Request',
                'date': r['date_submitted'].strftime('%Y-%m-%d %H:%M') if r.get('date_submitted') else '',
                'fee': f"₱{fee_val:.2f}", 'payment_status': payment_status, 'status': status,
                'remarks': r.get('remarks') or '', 'details': r.get('details') or '{}',
                'purpose': r.get('purpose') or '', 'history': history_by_request.get(r['id'], []),
                'issued_at': r.get('issued_at').strftime('%Y-%m-%d %H:%M') if r.get('issued_at') else '',
                'sticker_valid_from': r.get('sticker_valid_from').strftime('%Y-%m-%d') if r.get('sticker_valid_from') else '',
                'sticker_valid_until': r.get('sticker_valid_until').strftime('%Y-%m-%d') if r.get('sticker_valid_until') else '',
                'document_available': status == 'Issued / Completed',
                'edit_access_active': _request_edit_access_active(r),
                'edit_access_expires_at': r.get('edit_access_expires_at').strftime('%Y-%m-%d %H:%M') if r.get('edit_access_expires_at') else '',
                'edit_access_granted_by': r.get('edit_access_granted_by') or '',
                'payment_transaction': ({
                    'system_reference': payment_tx_map[r['id']].get('system_reference'),
                    'payment_date': payment_tx_map[r['id']].get('payment_date').strftime('%Y-%m-%d') if payment_tx_map[r['id']].get('payment_date') else '',
                    'official_receipt_no': payment_tx_map[r['id']].get('official_receipt_no') or '',
                    'document_released': bool(payment_tx_map[r['id']].get('document_released')),
                    'released_at': payment_tx_map[r['id']].get('released_at').strftime('%Y-%m-%d %H:%M') if payment_tx_map[r['id']].get('released_at') else ''
                } if r['id'] in payment_tx_map else None),
            })

        historical_request_fee_list=[{'type':x['request_type'],'date':x['request_date'].isoformat(),
                                      'amount':str(x['amount']),'status':'Unpaid','reference':x['external_ref']}
                                     for x in historical_request_fees]
        outstanding_request_fees += sum(float(x['amount']) for x in historical_request_fees)
        alert_list = [{'id': a['id'], 'text': a['text'],
                       'time': a['time'].strftime('%Y-%m-%d %H:%M') if a.get('time') else '',
                       'unread': bool(a['unread'])} for a in alerts_rows]
        unread_alerts_count = sum(1 for a in alert_list if a['unread'])

        missing_dues_total = sum(float(m['amount']) for m in missing_dues_rows)
        if missing_dues_rows:
            oldest = missing_dues_rows[0].get('due_month')
            today = datetime.now().date().replace(day=1)
            if isinstance(oldest, datetime): oldest = oldest.date()
            months_elapsed = max(1, (today.year-oldest.year)*12 + today.month-oldest.month + 1) if oldest else len(missing_dues_rows)
            years, rem = divmod(months_elapsed, 12)
            period_parts = ([f"{years} year{'s' if years != 1 else ''}"] if years else []) + ([f"{rem} month{'s' if rem != 1 else ''}"] if rem else [])
            outstanding_period = ' and '.join(period_parts) or '1 month'
            oldest_unpaid_due = oldest.strftime('%B %Y') if oldest else None
        else:
            outstanding_period = 'Clear'
            oldest_unpaid_due = None
        missing_dues_list = [{
            'due_month': m['due_month'].strftime('%Y-%m') if m.get('due_month') else '',
            'amount': f"₱{float(m['amount']):.2f}"
        } for m in missing_dues_rows]

        return jsonify({'status': 'success', 'user': user, 'fees': fees_dict, 'services': services, 'dashboard': {
            'active_requests': active_count,
            'outstanding_dues': missing_dues_total,
            'outstanding_request_fees': outstanding_request_fees,
            'historical_request_fees': historical_request_fee_list,
            'unread_alerts': unread_alerts_count, 'requests': req_list, 'alerts': alert_list,
            'missing_dues_count': len(missing_dues_rows), 'missing_dues_total': missing_dues_total,
            'oldest_unpaid_due': oldest_unpaid_due, 'outstanding_period': outstanding_period,
            'dues_status': 'Outstanding' if missing_dues_rows else 'Clear', 'missing_dues': missing_dues_list
        }, 'treasurer': get_treasurer_contact()})
    except Exception as e:
        app.logger.exception('Homeowner data load failed')
        return jsonify({'status': 'error', 'message': 'Unable to load homeowner data right now.'}), 500


@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    if session.get('role') != 'Homeowner':
        return jsonify({'status':'error','message':'Officer/Admin identity details are managed by the Administrator.'}),403
    data = request.get_json() or {}
    user_id = session['user_id']
    try:
        household=max(1,min(30,int(data.get('household') or 1)))
    except (TypeError,ValueError):
        return jsonify({'status':'error','message':'Household members must be a valid number.'}),400

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT first_name,middle_name,last_name,suffix,email,mobile,block,lot,address_line,household,verification_status FROM users WHERE id=%s AND role='Homeowner'", (user_id,))
            previous = cursor.fetchone()
            if not previous:
                conn.close()
                return jsonify({'status':'error','message':'Homeowner account not found.'}),404

            # Once HOA verification is complete, identity/property fields are controlled
            # records. Homeowners may still maintain personal/contact details that do not
            # change ownership/eligibility. Admin can update controlled fields when needed.
            verified = previous.get('verification_status') == 'Verified'
            if verified:
                first = previous.get('first_name') or ''
                middle = previous.get('middle_name') or ''
                last = previous.get('last_name') or ''
                suffix = previous.get('suffix') or ''
                email = (previous.get('email') or '').lower()
                block = previous.get('block') or ''
                lot = previous.get('lot') or ''
                address_line = previous.get('address_line') or ''
            else:
                first=normalize_unicode_text(data.get('first_name'))
                middle=normalize_unicode_text(data.get('middle_name'))
                last=normalize_unicode_text(data.get('last_name'))
                suffix=normalize_unicode_text(data.get('suffix'))
                # Email changes require proof of possession of the new address.
                email=(previous.get('email') or '').lower()
                block=normalize_unicode_text(data.get('block'))
                lot=normalize_unicode_text(data.get('lot'))
                # The homeowner profile UI does not expose the complete address field;
                # preserve the registration address unless a future verified UI supplies it.
                address_line = previous.get('address_line') or ''

            mobile=normalize_unicode_text(data.get('mobile'))
            if not first or not last or not email or not mobile:
                conn.close()
                return jsonify({'status':'error','message':'First name, last name, email, and mobile number are required.'}),400
            if not valid_person_name(first) or not valid_person_name(last) or (middle and not valid_person_name(middle, required=False)):
                conn.close()
                return jsonify({'status':'error','message':'Names may contain Unicode letters such as Ñ/ñ, spaces, hyphens, apostrophes, and periods only.'}),400
            if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$',email):
                conn.close()
                return jsonify({'status':'error','message':'Enter a valid email address.'}),400
            if not re.match(r'^09\d{9}$',mobile):
                conn.close()
                return jsonify({'status':'error','message':'Mobile number must contain 11 digits and start with 09.'}),400

            cursor.execute("SELECT id FROM users WHERE id<>%s AND LOWER(email)=LOWER(%s)", (user_id,email))
            if cursor.fetchone():
                conn.close()
                return jsonify({'status':'error','message':'That email address is already used by another account.'}),400

            cursor.execute("""UPDATE users SET
                first_name=%s, middle_name=%s, last_name=%s, suffix=%s,
                gender=%s, dob=%s, civil_status=%s, block=%s, lot=%s, address_line=%s,
                mobile=%s, household=%s WHERE id=%s""",
                           (first, middle or None, last, suffix or None, data.get('gender'), data.get('dob') or None,
                            data.get('civil_status'), block or None, lot or None, address_line or None,
                            mobile, household, user_id))
        conn.close()
        current={'first_name':first,'middle_name':middle,'last_name':last,'email':email,'mobile':mobile,'block':block,'lot':lot,'address_line':address_line,'household':household}
        log_audit_action(session.get('username'),'Homeowner','Update Homeowner Profile','Account',json.dumps(previous,default=str,ensure_ascii=False),json.dumps(current,ensure_ascii=False))
        msg = 'Profile updated successfully.'
        if previous.get('verification_status') == 'Verified':
            msg = 'Profile updated. Verified identity and property fields remain Administrator-controlled; email changes require verification.'
        return jsonify({'status': 'success', 'message': msg})
    except Exception:
        app.logger.exception('Homeowner API operation failed')
        return jsonify({'status': 'error', 'message': 'Unable to complete this operation right now. Please try again.'}), 500




# ---------------------------------------------------------------------------
# Homeowner email change: persistent, one-time, session-protected verification
# Requires database/HOMEOWNER_EMAIL_CHANGE_MIGRATION.sql before use.
# ---------------------------------------------------------------------------
EMAIL_CHANGE_TTL = 600
EMAIL_CHANGE_RESEND_SECONDS = 60
EMAIL_CHANGE_MAX_ATTEMPTS = 5


def _email_change_response(message, status=400):
    return jsonify({'status': 'error', 'message': message}), status


def _email_change_hash(user_id, new_email, code):
    material = f'{user_id}:{new_email}:{code}'.encode('utf-8')
    return hmac.new(app.secret_key.encode('utf-8'), material, hashlib.sha256).hexdigest()


def _email_change_send(address, code):
    if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
        raise RuntimeError('Email delivery is not configured')
    from markupsafe import escape
    message = Message('Verify Your New Email Address – NFH-HOA', recipients=[address])
    message.body = (
        'Dear Homeowner,\n\nWe received a request to change the email address '
        'associated with your NFH-HOA account.\n\n'
        f'Your verification code is: {code}\n\nThis code expires in 10 minutes. '
        'If you did not request this change, ignore this email; your registered '
        'email will remain unchanged.\n\nNorth Fairway Homes Homeowners\' Association'
    )
    message.html = (
        '<div style="font-family:Arial,sans-serif;max-width:540px;margin:auto">'
        '<h2 style="color:#1B4332">NFH-HOA Email Verification</h2>'
        '<p>Dear Homeowner,</p><p>We received a request to change your account email.</p>'
        '<p>Enter this verification code:</p>'
        f'<p style="font-size:28px;font-weight:bold;letter-spacing:5px">{escape(code)}</p>'
        '<p>This code expires in 10 minutes. If you did not request this change, '
        'ignore this message. Your registered email will remain unchanged.</p>'
        '<p>North Fairway Homes Homeowners\' Association</p></div>'
    )
    mail.send(message)


def _email_change_auth():
    if 'user_id' not in session:
        return _email_change_response('Please sign in again.', 401)
    if session.get('role') != 'Homeowner':
        return _email_change_response('Homeowner access required.', 403)
    return None


@app.route('/api/profile/email-change/status', methods=['GET'])
def homeowner_email_change_status():
    error = _email_change_auth()
    if error: return error
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT email FROM users WHERE id=%s AND role=%s',
                               (session['user_id'], 'Homeowner'))
                user = cursor.fetchone()
                cursor.execute('''SELECT new_email, expires_at FROM homeowner_email_changes
                                  WHERE user_id=%s AND expires_at>NOW()''', (session['user_id'],))
                pending = cursor.fetchone()
        finally: conn.close()
        if not user: return _email_change_response('Account not found.', 404)
        return jsonify({'status':'success', 'current_email':user['email'],
                        'pending_email':pending['new_email'] if pending else None,
                        'expires_at':pending['expires_at'].isoformat() if pending else None})
    except Exception:
        app.logger.exception('Email change status unavailable')
        return _email_change_response('Unable to load email settings.', 503)


@app.route('/api/profile/email-change/request', methods=['POST'])
def homeowner_email_change_request():
    error = _email_change_auth()
    if error: return error
    payload = request.get_json(silent=True) or {}
    new_email = str(payload.get('new_email') or '').strip().lower()
    if len(new_email) > 150 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', new_email):
        return _email_change_response('Enter a valid email address.')
    conn = None
    try:
        conn = get_db_connection(autocommit=False)
        with conn.cursor() as cursor:
            cursor.execute('SELECT email FROM users WHERE id=%s AND role=%s FOR UPDATE',
                           (session['user_id'], 'Homeowner'))
            user = cursor.fetchone()
            if not user: return _email_change_response('Account not found.', 404)
            if user['email'].casefold() == new_email.casefold():
                return _email_change_response('Enter a different email address.')
            cursor.execute('SELECT id FROM users WHERE LOWER(email)=LOWER(%s) AND id<>%s LIMIT 1',
                           (new_email, session['user_id']))
            if cursor.fetchone(): return _email_change_response('This email is already registered.')
            cursor.execute('SELECT sent_at FROM homeowner_email_changes WHERE user_id=%s FOR UPDATE',
                           (session['user_id'],))
            prior = cursor.fetchone()
            if prior and prior['sent_at'] > datetime.now() - timedelta(seconds=EMAIL_CHANGE_RESEND_SECONDS):
                return _email_change_response('Please wait one minute before requesting another code.',429)
            code = generate_code(6)
            cursor.execute('''INSERT INTO homeowner_email_changes
                    (user_id,new_email,code_hash,expires_at,sent_at,attempts)
                    VALUES (%s,%s,%s,DATE_ADD(NOW(),INTERVAL 10 MINUTE),NOW(),0)
                    ON DUPLICATE KEY UPDATE new_email=VALUES(new_email),code_hash=VALUES(code_hash),
                    expires_at=VALUES(expires_at),sent_at=VALUES(sent_at),attempts=0''',
                    (session['user_id'],new_email,_email_change_hash(session['user_id'],new_email,code)))
            # Mail failure rolls back the pending state; current registered email never changes.
            _email_change_send(new_email, code)
        conn.commit()
        return jsonify({'status':'success','message':'Verification code sent to your new email address.'})
    except Exception:
        app.logger.exception('Unable to send homeowner email-change verification')
        return _email_change_response('Unable to send the verification email. Please try again.',503)
    finally:
        if conn:
            try: conn.rollback()  # no-op after commit, safety on early returns/errors
            finally: conn.close()


@app.route('/api/profile/email-change/verify', methods=['POST'])
def homeowner_email_change_verify():
    error = _email_change_auth()
    if error: return error
    code = str((request.get_json(silent=True) or {}).get('code') or '').strip()
    if not re.fullmatch(r'\d{6}',code):
        return _email_change_response('Enter the six-digit verification code.')
    conn = None
    old_email = None
    new_email = None
    try:
        conn = get_db_connection(autocommit=False)
        with conn.cursor() as cursor:
            cursor.execute('SELECT email FROM users WHERE id=%s AND role=%s FOR UPDATE',
                           (session['user_id'],'Homeowner'))
            user = cursor.fetchone()
            if not user: return _email_change_response('Account not found.',404)
            cursor.execute('SELECT * FROM homeowner_email_changes WHERE user_id=%s FOR UPDATE',
                           (session['user_id'],))
            pending = cursor.fetchone()
            if not pending: return _email_change_response('Request a verification code first.')
            if pending['expires_at'] <= datetime.now():
                cursor.execute('DELETE FROM homeowner_email_changes WHERE user_id=%s',(session['user_id'],))
                conn.commit()
                return _email_change_response('Code expired. Request a new verification code.')
            if int(pending['attempts']) >= EMAIL_CHANGE_MAX_ATTEMPTS:
                cursor.execute('DELETE FROM homeowner_email_changes WHERE user_id=%s',(session['user_id'],))
                conn.commit()
                return _email_change_response('Too many attempts. Request a new code.',429)
            expected = _email_change_hash(session['user_id'],pending['new_email'],code)
            if not hmac.compare_digest(pending['code_hash'],expected):
                cursor.execute('UPDATE homeowner_email_changes SET attempts=attempts+1 WHERE user_id=%s',
                               (session['user_id'],))
                if int(pending['attempts']) + 1 >= EMAIL_CHANGE_MAX_ATTEMPTS:
                    cursor.execute('DELETE FROM homeowner_email_changes WHERE user_id=%s',(session['user_id'],))
                conn.commit()
                return _email_change_response('Incorrect code. Check the code or request a new one.')
            cursor.execute('SELECT id FROM users WHERE LOWER(email)=LOWER(%s) AND id<>%s LIMIT 1',
                           (pending['new_email'],session['user_id']))
            if cursor.fetchone(): return _email_change_response('This address is already registered.')
            old_email, new_email = user['email'],pending['new_email']
            cursor.execute('UPDATE users SET email=%s WHERE id=%s AND role=%s',
                           (new_email,session['user_id'],'Homeowner'))
            cursor.execute('DELETE FROM homeowner_email_changes WHERE user_id=%s',(session['user_id'],))
        conn.commit()
    except pymysql.err.IntegrityError:
        return _email_change_response('That email has been registered by another account.')
    except Exception:
        app.logger.exception('Unable to verify homeowner email change')
        return _email_change_response('Verification could not be completed.',503)
    finally:
        if conn:
            try: conn.rollback()
            finally: conn.close()
    log_audit_action(session.get('username'),'Homeowner','Change Verified Email','Account',
                     'Email changed from '+old_email,'Email changed to '+new_email)
    try:
        if old_email and old_email.casefold() != new_email.casefold():
            msg = Message('NFH-HOA Account Email Changed', recipients=[old_email])
            msg.body = ('The registered email address for your NFH-HOA account was changed. '
                        'If this was not you, contact the NFH-HOA office immediately.')
            mail.send(msg)
    except Exception:
        app.logger.warning('Could not deliver previous-address security notification')
    return jsonify({'status':'success','message':'Your new email address has been verified and saved.',
                    'current_email':new_email})


@app.route('/api/profile/email-change/cancel', methods=['POST'])
def homeowner_email_change_cancel():
    error = _email_change_auth()
    if error: return error
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('DELETE FROM homeowner_email_changes WHERE user_id=%s',(session['user_id'],))
        finally: conn.close()
        return jsonify({'status':'success','message':'Pending email change canceled.'})
    except Exception:
        app.logger.exception('Unable to cancel email change')
        return _email_change_response('Unable to cancel the request.',503)

@app.route('/api/profile/photo', methods=['POST'])
def upload_profile_photo():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file uploaded.'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'status': 'error', 'message': 'No file selected.'}), 400

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({'status': 'error', 'message': 'File too large. Maximum 5MB.'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'status': 'error', 'message': 'Invalid format. Use JPG, JPEG, PNG, or WEBP.'}), 400
    detected=_detected_image_ext(file)
    normalized_declared='jpg' if ext in {'jpg','jpeg'} else ext
    if not detected or detected != normalized_declared:
        return jsonify({'status':'error','message':'The selected file is not a valid image of the chosen type.'}),400

    filename = secure_filename(f"{session['user_id']}_{int(time.time())}.{ext}")
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)

    image_url = f"/static/uploads/{filename}"
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT profile_image FROM users WHERE id=%s", (session['user_id'],))
            previous_image=(cursor.fetchone() or {}).get('profile_image')
            cursor.execute("UPDATE users SET profile_image=%s WHERE id=%s", (image_url, session['user_id']))
        conn.close()
    except Exception:
        app.logger.exception('Profile picture update failed')
        return jsonify({'status': 'error', 'message': 'Unable to complete this operation right now. Please try again.'}), 500

    log_audit_action(session.get('username'),session.get('role'),'Update Profile Picture','Account',previous_image,image_url)
    return jsonify({'status': 'success', 'message': 'Profile picture updated.', 'image_url': image_url})


@app.route('/api/account/esign', methods=['POST'])
def upload_esignature():
    if 'user_id' not in session or session.get('role') not in OFFICER_ROLES:
        return jsonify({'status':'error','message':'Unauthorized'}),401
    if 'file' not in request.files or not request.files['file'].filename:
        return jsonify({'status':'error','message':'Select an e-signature image first.'}),400
    f=request.files['file']; ext=f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
    if ext not in {'png','jpg','jpeg'}:
        return jsonify({'status':'error','message':'Use PNG, JPG, or JPEG for the e-signature.'}),400
    detected=_detected_image_ext(f)
    normalized_declared='jpg' if ext in {'jpg','jpeg'} else ext
    if not detected or detected != normalized_declared:
        return jsonify({'status':'error','message':'The selected e-signature file is not a valid PNG/JPG image.'}),400
    f.seek(0,os.SEEK_END); size=f.tell(); f.seek(0)
    if size > 3*1024*1024:
        return jsonify({'status':'error','message':'E-signature image must be 3MB or smaller.'}),400
    filename=secure_filename(f"esign_{secrets.token_hex(16)}.{ext}")
    path=os.path.join(app.config['SIGNATURE_FOLDER'],filename); f.save(path)
    conn=get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT e_signature_path FROM users WHERE id=%s",(session['user_id'],)); old=(cursor.fetchone() or {}).get('e_signature_path')
            cursor.execute("UPDATE users SET e_signature_path=%s,e_signature_updated_at=NOW() WHERE id=%s",(filename,session['user_id']))
        if old and old!=filename:
            oldp=_signature_abs(old)
            if oldp:
                try: os.remove(oldp)
                except OSError: pass
        log_audit_action(session.get('username'),session.get('role'),'Upload E-Signature','Account',old or None,filename)
        return jsonify({'status':'success','message':'E-signature updated. It will be used only on documents that require your role.','preview_url':url_for('view_esignature',user_id=session['user_id'])})
    finally: conn.close()

@app.route('/api/account/esign', methods=['DELETE'])
def remove_esignature():
    if 'user_id' not in session or session.get('role') not in OFFICER_ROLES:
        return jsonify({'status':'error','message':'Unauthorized'}),401
    conn=get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT e_signature_path FROM users WHERE id=%s",(session['user_id'],)); row=cursor.fetchone() or {}; old=row.get('e_signature_path')
            cursor.execute("UPDATE users SET e_signature_path=NULL,e_signature_updated_at=NOW() WHERE id=%s",(session['user_id'],))
        oldp=_signature_abs(old)
        if oldp:
            try: os.remove(oldp)
            except OSError: pass
        log_audit_action(session.get('username'),session.get('role'),'Remove E-Signature','Account',old or None,None)
        return jsonify({'status':'success','message':'E-signature removed.'})
    finally: conn.close()

@app.route('/account/esignature/<int:user_id>')
def view_esignature(user_id):
    if 'user_id' not in session or session.get('role') not in OFFICER_ROLES:
        return ('Unauthorized',401)
    if session.get('role')!='Admin' and session.get('user_id')!=user_id:
        return ('Forbidden',403)
    conn=get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT e_signature_path FROM users WHERE id=%s",(user_id,)); row=cursor.fetchone()
        path=_signature_abs((row or {}).get('e_signature_path'))
        if not path: return ('Not found',404)
        response=send_file(path,conditional=False,max_age=0)
        response.headers['Cache-Control']='no-store, private, max-age=0'
        response.headers['Pragma']='no-cache'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Disposition']='inline'
        return response
    finally: conn.close()


@app.route('/api/settings/update', methods=['POST'])
def update_settings():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    data = request.get_json() or {}
    user_id = session['user_id']
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            if 'emergency' in data:
                em = data['emergency']
                cursor.execute("""UPDATE users SET
                    emergency_contact_name=%s, emergency_contact_number=%s,
                    emergency_contact_relationship=%s WHERE id=%s""",
                               (em.get('name'), em.get('number'), em.get('relationship'), user_id))
            if 'preferences' in data:
                cursor.execute("UPDATE users SET email_notifications=%s WHERE id=%s",
                               (1 if data['preferences'].get('email') else 0, user_id))
        conn.close()
        log_audit_action(session.get('username'),session.get('role'),'Update Account Settings','Account',None,json.dumps(data,ensure_ascii=False))
        return jsonify({'status': 'success', 'message': 'Settings updated.'})
    except Exception as e:
        app.logger.exception('Homeowner API operation failed')
        return jsonify({'status': 'error', 'message': 'Unable to complete this operation right now. Please try again.'}), 500


@app.route('/api/settings/password', methods=['POST'])
def update_password():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    data = request.get_json() or {}
    if not all([data.get('current_password'), data.get('new_password')]):
        return jsonify({'status': 'error', 'message': 'All fields required.'}), 400
    if len(data.get('new_password','')) < 8:
        return jsonify({'status': 'error', 'message': 'New password must be at least 8 characters.'}), 400
    if data['new_password'] != data.get('confirm_password'):
        return jsonify({'status': 'error', 'message': 'Passwords do not match.'}), 400
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT password_hash FROM users WHERE id=%s", (session['user_id'],))
            u = cursor.fetchone()
            if not u or not check_password_hash(u['password_hash'], data['current_password']):
                conn.close()
                return jsonify({'status': 'error', 'message': 'Current password incorrect.'}), 400
            cursor.execute("UPDATE users SET password_hash=%s WHERE id=%s",
                           (generate_password_hash(data['new_password'], method='pbkdf2:sha256'), session['user_id']))
        conn.close()
        log_audit_action(session.get('username'),session.get('role'),'Update Account Password','Account','Password changed','Password changed')
        return jsonify({'status': 'success', 'message': 'Password changed successfully.'})
    except Exception as e:
        app.logger.exception('Homeowner API operation failed')
        return jsonify({'status': 'error', 'message': 'Unable to complete this operation right now. Please try again.'}), 500


# ---------------------------------------------------------------------------
# Submit request
# ---------------------------------------------------------------------------
VALID_CATEGORIES = ['Document Request', 'Property & Moving', 'Vehicle Services', 'Tenant Services']


@app.route('/api/requests/submit', methods=['POST'])
def submit_request():
    if 'user_id' not in session or session.get('role') != 'Homeowner':
        return jsonify({'status':'error','message':'Unauthorized'}),401
    data=request.get_json() or {}
    title=(data.get('title') or '').strip()
    form_data=data.get('formData') or {}
    user_id=session['user_id']
    if not title:
        return jsonify({'status':'error','message':'Select a valid service before submitting.'}),400
    try:
        conn=get_db_connection(autocommit=False)
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id=%s",(user_id,))
            user=cursor.fetchone()
            # Serialize requests for one homeowner, including promotional credit use.
            cursor.execute("SELECT id FROM users WHERE id=%s FOR UPDATE",(user_id,))
            if not user or user.get('verification_status') != 'Verified':
                conn.close()
                return jsonify({'status':'error','message':'Your homeowner account must be verified before submitting requests.'}),403

            # Global HOA eligibility rule: a homeowner with any outstanding monthly dues
            # cannot create a NEW document request. Existing correction/resubmission flows
            # remain available so historical requests are not stranded.
            dues = dues_summary(cursor, user_id)
            if dues.get('unpaid_months', 0) > 0 and title != 'Statement of Account':
                conn.close()
                return jsonify({
                    'status':'error', 'code':'OUTSTANDING_DUES',
                    'message':'Document requests are temporarily unavailable while you have outstanding monthly HOA dues. Please coordinate with the Treasurer first.',
                    'outstanding_balance': float(dues.get('outstanding_balance') or 0),
                    'unpaid_months': int(dues.get('unpaid_months') or 0)
                }), 403

            service = get_service_config(cursor, title, active_only=False)
            if service and service.get('status') != 'Active':
                conn.close()
                return jsonify({'status':'error','message':'This service is currently inactive. Please choose another available service or contact the HOA office.'}),400
            if not service:
                # Compatibility for an older database that has not yet run the
                # service-type migration. Unknown services are never accepted.
                legacy_titles = SECRETARY_FIRST_REQUEST_TYPES | TREASURER_FIRST_REQUEST_TYPES | SHARED_INITIAL_CHECK_REQUEST_TYPES
                if title not in legacy_titles:
                    conn.close()
                    return jsonify({'status':'error','message':'This service is not configured in the NFH-HOA system.'}),400
                cursor.execute("SELECT amount FROM fees WHERE item_name=%s AND status='Active'", (title,))
                fee_row = cursor.fetchone()
                service = {
                    'service_name': title,
                    'category': data.get('category') if data.get('category') in VALID_CATEGORIES else 'Document Request',
                    'fee': float(fee_row['amount']) if fee_row else 0.0,
                    'initial_reviewer': next(iter(initial_checker_roles(title))),
                    'requires_executive': 1,
                    'requires_payment': 1,
                    'requires_dues_clearance': 1,
                    'release_role': 'Secretary',
                    'form_template': {
                        'Gate Pass':'gate-pass','Proof of Residency':'proof-residency','Certificate of Improvement':'cert-improvement',
                        'Certificate of Membership':'cert-membership','Move-in Gate Pass':'move-in','Move-out Gate Pass':'move-out',
                        'Vehicle Sticker Application':'vehicle-sticker','Renters/Tenants Information Form':'tenant-form'
                    }.get(title,'generic'),
                    'purpose_required': 1 if title in PURPOSE_REQUIRED_REQUEST_TYPES else 0,
                }

            if title == 'Statement of Account':
                if not service or service.get('form_template') != 'statement-of-account':
                    conn.close()
                    return jsonify({'status':'error','message':'Statement of Account service configuration is invalid.'}),400
            user=complete_missing_request_profile(cursor,user_id,user,form_data)
            err=validate_request_payload(title,form_data,user,service)
            if err:
                conn.close()
                return jsonify({'status':'error','message':err}),400

            category=service.get('category') or 'Document Request'
            fee_amount=float(service.get('fee') or 0)
            if service.get('form_template') == 'vehicle-sticker':
                cursor.execute("SELECT item_name,amount FROM fees WHERE status='Active'")
                fmap={x['item_name']:float(x['amount']) for x in cursor.fetchall()}
                fee_amount=sum(
                    fmap.get('Vehicle Sticker (4 Wheels)',200.0) if v.get('type')=='4 Wheels'
                    else fmap.get('Vehicle Sticker (2/3 Wheels)',100.0)
                    for v in form_data.get('vehicles',[])
                )
            requires_payment=bool(service.get('requires_payment')) and fee_amount > 0
            if not bool(service.get('requires_payment')):
                fee_amount=0.0
            payment_status='Unpaid' if requires_payment else 'Not Required'
            if str(data.get('promo_code') or '').strip() and not requires_payment:
                conn.close()
                return jsonify({'status':'error','message':'Promo codes cannot be used for free services.'}), 400

            req_id=f"REQ-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000,9999)}"
            # Avoid a rare collision without exposing database errors to the user.
            for _ in range(5):
                cursor.execute("SELECT id FROM requests WHERE id=%s", (req_id,))
                if not cursor.fetchone():
                    break
                req_id=f"REQ-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000,9999)}"
            purpose=(form_data.get('purpose') or '').strip()
            purpose_details=(form_data.get('purposeDetails') or '').strip()
            cursor.execute("""INSERT INTO requests
                (id,user_id,request_type,category,submission_type,fee,details,purpose,purpose_details,status,payment_status,assigned_officer)
                VALUES (%s,%s,%s,%s,'Query',%s,%s,%s,%s,'Submitted',%s,%s)""",
                (req_id,user_id,title,category,fee_amount,json.dumps(form_data),purpose,purpose_details,payment_status,
                 'Treasurer' if title == 'Statement of Account' else None))
            # Preserve the normal approval/release workflow: only the processing fee changes.
            from advance_promo import CERTIFICATES, redeem_code
            selected_code=str(data.get('promo_code') or '').strip()
            if selected_code and not requires_payment:
                raise ValueError('Promo codes cannot be applied to a free service or a request without a payment fee.')
            if selected_code:
                redeem_code(cursor,user_id,req_id,title,selected_code,fee_amount)
                cursor.execute("UPDATE requests SET fee=0, payment_status='Not Required' WHERE id=%s",(req_id,))
                cursor.execute("INSERT INTO audit_logs(username,role,action,item,prev_val,new_val) VALUES (%s,'Homeowner','Redeem Free Certificate',%s,%s,%s)",
                               (str(user_id),req_id,str(fee_amount),f'Promo code {selected_code} applied'))
            assign_request_document_template(cursor, req_id, title)
        conn.commit()
        conn.close()
        history_note = f'Purpose: {purpose}' if purpose else 'Homeowner submitted the request.'
        record_request_history(req_id,'Submitted',None,'Submitted',history_note,session.get('full_name') or session.get('username'),'Homeowner')
        return jsonify({'status':'success','message':f'Request {req_id} submitted successfully.'})
    except ValueError as e:
        if 'conn' in locals() and conn:
            try: conn.rollback();conn.close()
            except Exception: pass
        return jsonify({'status':'error','message':str(e)}),400
    except Exception as e:
        app.logger.exception('Request submission failed')
        return jsonify({'status':'error','message':'Unable to submit the request right now. Please try again.'}),500


@app.route('/api/requests/concern', methods=['POST'])
def submit_request_concern():
    if 'user_id' not in session or session.get('role') != 'Homeowner':
        return jsonify({'status':'error','message':'Unauthorized'}), 401
    data=request.get_json() or {}; req_id=(data.get('request_id') or '').strip(); message=(data.get('message') or '').strip(); subject=(data.get('subject') or 'Request Concern').strip()[:150]
    if not req_id or len(message) < 5:
        return jsonify({'status':'error','message':'Please enter a clear concern.'}), 400
    try:
        conn=get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT request_type, assigned_officer FROM requests WHERE id=%s AND user_id=%s", (req_id,session['user_id']))
            req=cursor.fetchone()
            if not req: conn.close(); return jsonify({'status':'error','message':'Request not found.'}),404
            assigned=req.get('assigned_officer') if req.get('assigned_officer') in ('Secretary','Treasurer') else sorted(initial_checker_roles(req['request_type']))[0]
            if assigned not in ('Secretary','Treasurer'): assigned='Secretary'
            cursor.execute("""INSERT INTO request_concerns (request_id,user_id,assigned_role,subject,concern_text,status)
                              VALUES (%s,%s,%s,%s,%s,'Open')""",(req_id,session['user_id'],assigned,subject,message))
        conn.close()
        log_audit_action(session.get('username'),'Homeowner','Request Concern Submitted',req_id,None,f'Assigned to {assigned}')
        return jsonify({'status':'success','message':f'Your concern for {req_id} was submitted to the {assigned}.'})
    except Exception:
        app.logger.exception('Request concern submission failed for %s', req_id)
        return jsonify({'status':'error','message':'Unable to submit the concern right now. Please try again.'}),500

@app.route('/api/requests/concerns', methods=['GET'])
def homeowner_concerns():
    if 'user_id' not in session or session.get('role') != 'Homeowner': return jsonify({'status':'error'}),401
    conn=get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""SELECT c.id,c.request_id,c.assigned_role,c.subject,c.concern_text,c.response_text,c.status,c.responded_by, r.request_type,
                          DATE_FORMAT(c.created_at,'%%Y-%%m-%%d %%H:%%i') created_at,
                          DATE_FORMAT(c.responded_at,'%%Y-%%m-%%d %%H:%%i') responded_at
                          FROM request_concerns c JOIN requests r ON r.id=c.request_id WHERE c.user_id=%s ORDER BY c.updated_at DESC""",(session['user_id'],))
        rows=cursor.fetchall()
    conn.close(); return jsonify({'status':'success','concerns':rows})

@app.route('/officer/concerns/<int:concern_id>/respond', methods=['POST'])
def respond_request_concern(concern_id):
    if 'user_id' not in session or session.get('role') not in ('Secretary','Treasurer','Admin'):
        return redirect(url_for('index'))
    response=(request.form.get('response') or '').strip()
    if not response:
        flash('Please enter a response to the homeowner.', 'error')
        return redirect(request.referrer or _role_home_url(session.get('role')))
    try:
        conn=get_db_connection()
        with conn.cursor() as cursor:
            role_filter = "" if session.get('role') == 'Admin' else " AND c.assigned_role=%s"
            params = (concern_id,) if session.get('role') == 'Admin' else (concern_id,session.get('role'))
            cursor.execute(f"""SELECT c.*, r.request_type, CONCAT(u.first_name,' ',u.last_name) AS homeowner
                                FROM request_concerns c
                                JOIN requests r ON r.id=c.request_id
                                JOIN users u ON u.id=c.user_id
                                WHERE c.id=%s{role_filter}""", params)
            c=cursor.fetchone()
            if not c:
                conn.close(); flash('Concern not found or not available to your role.','error'); return redirect(request.referrer or _role_home_url(session.get('role')))
            previous = c.get('response_text') or c.get('status') or 'Open'
            cursor.execute("UPDATE request_concerns SET response_text=%s,status='Responded',responded_by=%s,responded_at=NOW() WHERE id=%s",
                           (response,session.get('full_name') or session.get('username'),concern_id))
        conn.close()
        homeowner_name = c.get('homeowner') or 'Homeowner'
        request_type = c.get('request_type') or 'Request'
        responder_label = 'Administrator' if session.get('role') == 'Admin' else session.get('role')
        body=(f"Dear {homeowner_name},\n\nYour concern regarding {request_type} request {c['request_id']} has received a response from the {responder_label}.\n\n"
              f"Response: {response}\n\n"
              "Please sign in to the NFH-HOA Homeowner Portal to review the request conversation.\n\n"
              "Thank you,\nNorth Fairway Homes Homeowners' Association")
        result=send_alert_and_email(c['user_id'],f"NFH-HOA Concern Response — {c['request_id']}",body,'request_concern',str(concern_id),f'concern-response-{concern_id}-{int(time.time())}')
        log_audit_action(session.get('username'),session.get('role'),'Request Concern Response Updated',c['request_id'],previous,response)
        record_request_history(c['request_id'],'Concern Response',None,None,f'{responder_label}: {response}')
        flash('Response saved and the homeowner was notified.','success')
        if not result.get('email_sent'): flash('The response was saved, but email delivery was unavailable.','warning')
    except Exception:
        app.logger.exception('Request concern response failed for %s', concern_id)
        flash('Unable to save the concern response right now. Please try again.','error')
    return redirect(request.referrer or _role_home_url(session.get('role')))

@app.route('/api/requests/concerns/<int:concern_id>/resolve', methods=['POST'])
def resolve_homeowner_concern(concern_id):
    if 'user_id' not in session or session.get('role') != 'Homeowner':
        return jsonify({'status':'error','message':'Unauthorized'}),401
    conn=get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT request_id,status FROM request_concerns WHERE id=%s AND user_id=%s",(concern_id,session['user_id']))
            row=cursor.fetchone()
            if not row: return jsonify({'status':'error','message':'Concern not found.'}),404
            cursor.execute("UPDATE request_concerns SET status='Resolved' WHERE id=%s",(concern_id,))
        log_audit_action(session.get('username'),'Homeowner','Resolve Request Concern',row['request_id'],row['status'],'Resolved')
        return jsonify({'status':'success','message':'Concern marked as resolved.'})
    finally:
        conn.close()


@app.route('/api/requests/resubmit', methods=['POST'])
def resubmit_request():
    """Homeowner updates an officer correction or a concern-approved temporary edit."""
    if 'user_id' not in session or session.get('role') != 'Homeowner':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    data = request.get_json() or {}
    request_id = data.get('request_id')
    form_data = data.get('formData', {})
    user_id = session['user_id']
    _expire_edit_access_for_request(request_id)
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT status, request_type, details, purpose, purpose_details, edit_access_expires_at, edit_access_expired_at FROM requests WHERE id=%s AND user_id=%s",
                           (request_id, user_id))
            req = cursor.fetchone()
            if not req:
                conn.close(); return jsonify({'status': 'error', 'message': 'Request not found.'}), 404
            standard_correction = req['status'] == 'For Correction'
            temporary_edit = _request_edit_access_active(req)
            if not standard_correction and not temporary_edit:
                conn.close(); return jsonify({'status': 'error', 'message': 'This request is not currently open for editing.'}), 400

            service = get_service_config(cursor, req['request_type'], active_only=False)
            cursor.execute("SELECT * FROM users WHERE id=%s",(user_id,))
            homeowner=cursor.fetchone()
            homeowner=complete_missing_request_profile(cursor,user_id,homeowner or {},form_data)
            err=validate_request_payload(req['request_type'],form_data,homeowner,service)
            if err:
                conn.close(); return jsonify({'status':'error','message':err}),400

            previous_status=req['status']; previous_details=req.get('details') or '{}'
            # Any homeowner-initiated change after initial checking invalidates that check.
            # Return to Submitted so the Secretary/Treasurer reviews the revised information again.
            cursor.execute("""UPDATE requests SET details=%s, purpose=%s, purpose_details=%s, status='Submitted', remarks=NULL,
                              edit_access_expires_at=NULL, edit_access_expired_at=NOW()
                              WHERE id=%s""",
                           (json.dumps(form_data, ensure_ascii=False), form_data.get('purpose'), form_data.get('purposeDetails'), request_id))
        conn.close()
        action='Resubmitted After Officer Correction' if standard_correction else 'Homeowner Edit Submitted'
        note='Homeowner corrected and resubmitted the request.' if standard_correction else 'Homeowner used time-limited edit access granted after a request concern. Initial review is required again.'
        record_request_history(request_id,action,previous_status,'Submitted',note)
        log_audit_action(session.get('username'), session.get('role'), action, request_id,
                         previous_details, json.dumps(form_data, ensure_ascii=False))
        return jsonify({'status': 'success', 'message': f'Request {request_id} updated and returned for initial review.'})
    except Exception:
        app.logger.exception('Request resubmission/edit failed for %s', request_id)
        return jsonify({'status': 'error', 'message': 'Unable to update the request right now.'}), 500


# ---------------------------------------------------------------------------
# Cancel request

# ---------------------------------------------------------------------------
@app.route('/api/requests/cancel', methods=['POST'])
def cancel_request():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    data = request.get_json() or {}
    request_id = data.get('request_id')
    reason = (data.get('reason') or '').strip()
    user_id = session['user_id']
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT status, request_type FROM requests WHERE id=%s AND user_id=%s",
                           (request_id, user_id))
            req = cursor.fetchone()
            if not req:
                conn.close()
                return jsonify({'status': 'error', 'message': 'Request not found.'}), 404
            if req['status'] not in ['Submitted', 'Under Review']:
                conn.close()
                return jsonify({'status': 'error', 'message': 'This request can no longer be cancelled.'}), 400
            cursor.execute("""UPDATE requests SET status='Cancelled', cancellation_reason=%s, cancelled_by=%s
                              WHERE id=%s""", (reason, session.get('username'), request_id))
            cursor.execute("SELECT id FROM nfh_advance_promo_redemptions WHERE request_id=%s",(request_id,))
            if cursor.fetchone():
                cursor.execute("INSERT INTO audit_logs(username,role,action,item,prev_val,new_val) VALUES (%s,%s,'Restore Promo Certificate Credit',%s,'Reserved','Available')",
                               (session.get('username'),session.get('role'),request_id))
        conn.close()
        record_request_history(request_id,'Cancelled',req['status'],'Cancelled',reason)
        log_audit_action(session.get('username'), session.get('role'), 'Cancel Request',
                         request_id, req['status'], 'Cancelled')
        return jsonify({'status': 'success', 'message': 'Request cancelled successfully.'})
    except Exception as e:
        app.logger.exception('Homeowner API operation failed')
        return jsonify({'status': 'error', 'message': 'Unable to complete this operation right now. Please try again.'}), 500


@app.route('/api/alerts/<int:alert_id>/read', methods=['POST'])
def read_one_alert(alert_id):
    if 'user_id' not in session:
        return jsonify({'status':'error','message':'Unauthorized'}), 401
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE alerts SET unread=0 WHERE id=%s AND user_id=%s', (alert_id, session['user_id']))
                found = cursor.rowcount
            conn.commit()
        finally:
            conn.close()
        return jsonify({'status':'success' if found else 'not_found'}), (200 if found else 404)
    except Exception:
        app.logger.exception('Unable to mark notification as read')
        return jsonify({'status':'error','message':'Unable to update notification'}), 500


@app.route('/api/alerts/read', methods=['POST'])
def read_alerts():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("UPDATE alerts SET unread=0 WHERE user_id=%s", (session['user_id'],))
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.exception('Homeowner API operation failed')
        return jsonify({'status': 'error', 'message': 'Unable to complete this operation right now. Please try again.'}), 500


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'status': 'success', 'message': 'Logged out successfully.'})


# ===========================================================================
# TREASURER — MISSING MONTHLY DUES (applied directly; no Executive approval)
# ===========================================================================


@app.route('/api/treasurer/payment-release/records', methods=['GET'])
def nfh_payment_release_records():
    """Treasurer-only, database-wide filtered workflow queues; read only."""
    if session.get('role') != 'Treasurer' or not session.get('user_id'):
        return jsonify({'status':'error','message':'Forbidden'}), 403
    term = (request.args.get('search') or '').strip()[:120]
    category = request.args.get('category','all')
    if category not in ('all','ready','awaiting','completed'):
        return jsonify({'status':'error','message':'Invalid category'}),400
    order = 'ASC' if request.args.get('sort') == 'asc' else 'DESC'
    try:
        page = max(1,int(request.args.get('page',1)))
        limit = min(100,max(5,int(request.args.get('limit',15))))
    except (TypeError,ValueError):
        return jsonify({'status':'error','message':'Invalid pagination'}),400
    like = '%' + term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
    base = """ FROM requests r JOIN users u ON u.id=r.user_id
        LEFT JOIN payment_transactions pt ON pt.request_id=r.id
        WHERE u.role='Homeowner' """
    if term:
        base += """ AND (r.id LIKE %s OR r.request_type LIKE %s
          OR u.first_name LIKE %s OR u.last_name LIKE %s
          OR CONCAT_WS(' ',u.first_name,u.middle_name,u.last_name) LIKE %s
          OR u.homeowner_public_id LIKE %s OR u.block LIKE %s OR u.lot LIKE %s
          OR CONCAT('Block ',COALESCE(u.block,''),' Lot ',COALESCE(u.lot,'')) LIKE %s) """
    params = [like]*9 if term else []
    stages={
      'ready': "r.status IN ('Ready for Payment & Release','Awaiting Payment Verification','Approved') AND r.payment_status='Unpaid'",
      'awaiting': "r.status='Paid - Awaiting Release' AND r.payment_status='Paid'",
      'completed': "pt.id IS NOT NULL"
    }
    out={}
    conn=None
    try:
        conn=get_db_connection()
        with conn.cursor() as cur:
            for key,condition in stages.items():
                if category != 'all' and category != key:
                    out[key]={'records':[],'total':0,'page':1,'pages':0}
                    continue
                where = base + ' AND ' + condition
                cur.execute('SELECT COUNT(DISTINCT r.id) AS total'+where,tuple(params))
                total=int(cur.fetchone()['total'])
                pages=max(1,(total+limit-1)//limit)
                current=min(page,pages)
                sql = """SELECT r.id, r.request_type, r.fee, r.status, r.payment_status,
                    r.date_submitted, r.payment_reference, u.first_name,u.last_name,
                    u.homeowner_public_id, u.block,u.lot,
                    pt.system_reference,pt.official_receipt_no,pt.payment_date,pt.document_released
                  """ + where + f' ORDER BY COALESCE(pt.payment_date,DATE(r.date_submitted)) {order}, r.id {order} LIMIT %s OFFSET %s'
                cur.execute(sql,tuple(params+[limit,(current-1)*limit]))
                items=[]
                for item in cur.fetchall():
                    items.append({
                      'id':item['id'],'service':item['request_type'],
                      'homeowner':f"{item['first_name']} {item['last_name']}",
                      'homeowner_id':item['homeowner_public_id'] or '',
                      'block':item['block'] or '', 'lot':item['lot'] or '',
                      'fee':float(item['fee'] or 0),'status':item['status'],
                      'payment_status':item['payment_status'],
                      'system_reference':item['system_reference'] or item['payment_reference'] or '',
                      'or_number':item['official_receipt_no'] or '',
                      'payment_date':item['payment_date'].isoformat() if item['payment_date'] else '',
                      'document_released':bool(item['document_released'])
                    })
                out[key]={'records':items,'total':total,'page':current,'pages':pages}
        return jsonify({'status':'success','sections':out})
    except Exception:
        app.logger.exception('Payment release filtered records failed')
        return jsonify({'status':'error','message':'Unable to load payment records'}),500
    finally:
        if conn:conn.close()

@app.route('/api/treasurer/adjustment', methods=['POST'])
def treasurer_submit_adjustment():
    """Record missing monthly dues as one atomic Treasurer operation."""
    if 'user_id' not in session or session.get('role') not in ['Treasurer', 'Admin']:
        return jsonify({'status': 'error', 'message': 'Permission denied.'}), 403
    data = request.get_json() or {}
    user_id = data.get('user_id')
    try:
        missing_months = int(data.get('missing_months') or 0)
    except (TypeError, ValueError):
        missing_months = 0
    reason = (data.get('reason') or '').strip()
    end_month_raw = (data.get('end_month') or '').strip()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'Please select a homeowner.'}), 400
    if missing_months <= 0 or missing_months > 120:
        return jsonify({'status': 'error', 'message': 'Missing months must be between 1 and 120.'}), 400
    if len(reason) < 3:
        return jsonify({'status': 'error', 'message': 'Provide a short reason for the missing dues entry.'}), 400
    try:
        end_month = datetime.strptime(end_month_raw, '%Y-%m').date().replace(day=1) if end_month_raw else datetime.now().date().replace(day=1)
    except ValueError:
        return jsonify({'status':'error','message':'Select a valid missing-dues month.'}), 400
    current_month = datetime.now().date().replace(day=1)
    if end_month > current_month:
        return jsonify({'status':'error','message':'Missing monthly dues cannot be recorded for a future month.'}), 400

    plan_req = (data.get('payment_plan') or {}) if isinstance(data.get('payment_plan'), dict) else {}
    if plan_req.get('enabled'):
        try:
            from inline_missing_dues_plan import schedule
            schedule(1, 1, str(plan_req['first_due']))  # date syntax check, full plan validated within the transaction
            plan_duration = int(plan_req['months'])
            if plan_duration<1 or plan_duration>240: raise ValueError()
        except (ValueError, TypeError, KeyError):
            return jsonify(status='error',message='Invalid payment plan duration or first due date'),400
    else:
        plan_duration = None
    conn = None
    inserted_months = []
    before_dues = {'outstanding_balance': 0}
    after_dues = {'outstanding_balance': 0}
    monthly_due = 0.0
    adj_id = None
    homeowner_name = None
    try:
        conn = get_db_connection(autocommit=False)
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, CONCAT(first_name,' ',last_name) AS name FROM users WHERE id=%s AND role='Homeowner' FOR UPDATE", (user_id,))
            u = cursor.fetchone()
            if not u:
                conn.rollback()
                return jsonify({'status': 'error', 'message': 'Homeowner not found.'}), 404
            homeowner_name = u['name']
            cursor.execute("SELECT amount FROM fees WHERE item_name='Monthly Dues' AND status='Active'")
            due_row = cursor.fetchone()
            from whole_peso import whole
            monthly_due = whole(due_row['amount'] if due_row else 100,positive=True)
            before_dues = dues_summary(cursor, user_id)

            month_cursor = end_month
            for i in range(missing_months):
                due_month = month_cursor - relativedelta(months=i)
                cursor.execute("""INSERT IGNORE INTO monthly_dues (user_id, due_month, amount, status)
                                  VALUES (%s,%s,%s,'Unpaid')""", (user_id, due_month, monthly_due))
                if cursor.rowcount == 1:
                    inserted_months.append(due_month)
            if not inserted_months:
                conn.rollback()
                return jsonify({'status':'error','message':'Those monthly dues are already recorded for this homeowner.'}),400

            total = monthly_due * len(inserted_months)
            if plan_duration:
                from inline_missing_dues_plan import create_plan
                plan_result = create_plan(cursor,user_id,plan_duration,str(plan_req['first_due']),session.get('username'),end_month.strftime('%B %Y'),len(inserted_months))
            after_dues = dues_summary(cursor, user_id)
            cursor.execute("""INSERT INTO financial_adjustments
                (user_id, homeowner_name, monthly_due, missing_months, proposed_adjustment,
                 previous_balance, new_balance, reason, submitted_by, status, decided_by, decided_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'Applied',%s,%s)""",
                (user_id, homeowner_name, monthly_due, len(inserted_months), total,
                 float(before_dues.get('outstanding_balance') or 0), float(after_dues.get('outstanding_balance') or 0),
                 reason, session.get('username'), session.get('username'), datetime.now()))
            adj_id = cursor.lastrowid
        conn.commit()
    except Exception:
        if conn:
            try: conn.rollback()
            except Exception: pass
        app.logger.exception('Missing dues adjustment failed')
        return jsonify({'status': 'error', 'message': 'Unable to record the missing dues right now.'}), 500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

    total = monthly_due * len(inserted_months)
    skipped = missing_months - len(inserted_months)
    periods = ', '.join(d.strftime('%B %Y') for d in sorted(inserted_months))
    log_audit_action(session.get('username'), session.get('role'),
                     'Missing Dues Adjustment Applied', f'Adjustment-{adj_id}',
                     f"₱{float(before_dues.get('outstanding_balance') or 0):.2f}",
                     f"{periods} | New outstanding: ₱{float(after_dues.get('outstanding_balance') or 0):.2f}")
    treasurer = get_treasurer_contact()
    # Read-only financial snapshot after the existing transaction has committed.
    # Failed presentation queries never roll back or alter financial records.
    from financial_notice_email import prepare_financial_notice
    email_subject = ('NFH-HOA | Delinquent Payment Plan Confirmation' if plan_duration
                     else 'NFH-HOA | Missing Monthly Dues Applied')
    try:
        email_conn = get_db_connection()
        try:
            with email_conn.cursor() as email_cursor:
                email_text, email_html = prepare_financial_notice(
                    email_cursor, user_id, homeowner_name, total, treasurer,
                    plan_id=plan_result['id'] if plan_duration else None,
                    reason=reason)
        finally:
            email_conn.close()
    except Exception:
        app.logger.exception('Could not build the financial email snapshot; using original text fallback')
        email_text = (f"Dear {homeowner_name},\n\nMissing monthly dues of ₱{total:,.2f} "
                      f"have been applied to your account for {periods}.\n"
                      f"Please contact the HOA Treasurer for your updated statement and payment details.\n"
                      f"{treasurer['name']} | {treasurer['phone']} | {treasurer['email']}")
        email_html = None
    send_alert_and_email(
        user_id, email_subject, email_text,
        related_type='financial_adjustment', related_id=str(adj_id),
        dedupe_key=f'missing-dues-{adj_id}', html_body=email_html)
    message = 'Missing dues recorded and the homeowner was notified.'
    if skipped:
        message += f' {skipped} duplicate month(s) were skipped.'
    return jsonify({'status': 'success', 'message': message, 'recorded_months': len(inserted_months),
                    'recorded_periods': [d.strftime('%B %Y') for d in sorted(inserted_months)], 'total': total})


# ===========================================================================
# TREASURER — CLEAR / SETTLE MONTHLY DUES
# ===========================================================================
@app.route('/api/treasurer/payment-overview/<int:user_id>', methods=['GET'])
def treasurer_payment_overview(user_id):
    if session.get('role')!='Treasurer': return jsonify(error='Treasurer access required'),403
    from restored_plan_payments import overview
    conn=None
    try:
        conn=get_db_connection()
        with conn.cursor() as cur:
            data=overview(cur,user_id)
        if data is None: return jsonify(error='Homeowner not found'),404
        return jsonify(data),200
    except Exception:
        app.logger.exception('Monthly dues payment overview failure for homeowner %s',user_id)
        return jsonify(error='Unable to load the verified monthly dues or payment plan. Check the MySQL migrations.'),503
    finally:
        if conn: conn.close()

@app.route('/api/treasurer/settle-dues', methods=['POST'])
def treasurer_settle_dues():
    if session.get('role')!='Treasurer': return jsonify(status='error',message='Treasurer access required'),403
    from whole_peso import whole
    from restored_plan_payments import record_payment
    data=request.get_json(silent=True) or {}
    try:
        homeowner_id=int(data['user_id'])
        amount=whole(data['amount'],positive=True)
        reference=str(data.get('reference') or '').strip()[:100]
        request_key=str(data['request_key']).strip()
        if not 10<=len(request_key)<=80: raise ValueError('Invalid payment request identifier')
        paid_date=datetime.strptime(str(data['payment_date']),'%Y-%m-%d')
        if paid_date.date()>datetime.now().date(): raise ValueError('Payment date cannot be in the future')
    except (KeyError, ValueError,TypeError) as exc:
        return jsonify(status='error',message=str(exc)),400
    conn=None
    try:
        conn=get_db_connection(autocommit=False)
        result=record_payment(conn,homeowner_id,amount,session.get('username','Treasurer'),paid_date,reference,request_key)
        conn.commit()
        return jsonify(status='success',message='Cash payment recorded.' if not result.get('duplicate') else 'This cash payment was already recorded.',**result)
    except ValueError as exc:
        if conn:conn.rollback()
        return jsonify(status='error',message=str(exc)),400
    except Exception:
        if conn:conn.rollback()
        app.logger.exception('Monthly dues payment failed for homeowner %s',homeowner_id)
        return jsonify(status='error',message='Payment failed; no financial changes were committed.'),503
    finally:
        if conn: conn.close()

# ===========================================================================
# EVALUATOR REVISION — HOMEOWNER VERIFICATION / SERVICE CONFIG / ISSUANCE
# ===========================================================================
@app.route('/admin/homeowner-verification/<int:user_id>/review', methods=['GET'])
def admin_homeowner_review(user_id):
    if session.get('role') != 'Admin' or not session.get('user_id'):
        return jsonify(status='error', message='Unauthorized'), 403
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""SELECT id,first_name,middle_name,last_name,suffix,gender,dob,civil_status,
                  block,lot,address_line,homeowner_public_id,email,mobile,household,created_at,
                  verification_status FROM users WHERE id=%s AND role='Homeowner'""", (user_id,))
            u = cursor.fetchone()
        if not u or u['verification_status'] != 'Pending Verification':
            return jsonify(status='error',message='Registration is no longer pending'),409
        for field in ('dob','created_at'):
            if u.get(field): u[field]=u[field].isoformat()
        return jsonify(status='success',homeowner=u)
    finally:
        conn.close()


def _registration_dependencies(cursor, user_id):
    """Inspect ALL actual FK relationships to users, avoiding cascade deletes.
    An inaccessible/unknown FK is an error, never a license to delete.
    """
    cursor.execute("""SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE
        WHERE REFERENCED_TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME='users'
          AND REFERENCED_COLUMN_NAME='id'""")
    refs=cursor.fetchall()
    occupied=[]
    for ref in refs:
        table=ref['TABLE_NAME']; col=ref['COLUMN_NAME']
        # identifiers originate from information_schema, not user input
        if not re.fullmatch(r'[A-Za-z0-9_]+',table) or not re.fullmatch(r'[A-Za-z0-9_]+',col):
            raise ValueError('Unsafe schema identifier')
        cursor.execute(f'SELECT 1 FROM `{table}` WHERE `{col}`=%s LIMIT 1',(user_id,))
        if cursor.fetchone(): occupied.append(table)
    return sorted(set(occupied))

@app.route('/admin/homeowner-verification/<int:user_id>', methods=['POST'])
def admin_homeowner_verification(user_id):
    if session.get('role') != 'Admin' or not session.get('user_id'):
        return jsonify(status='error',message='Unauthorized'),403
    action=(request.form.get('action') or '').strip().lower()
    if action not in ('verify','reject'):
        return jsonify(status='error',message='Invalid action'),400
    if request.form.get('final_confirmation') != 'yes':
        return jsonify(status='error',message='Final review confirmation required'),400
    reason=(request.form.get('remarks') or '').strip()
    if action == 'reject' and (len(reason)<12 or len(reason)>1000):
        return jsonify(status='error',message='Provide meaningful rejection remarks (12–1000 characters).'),400
    conn=get_db_connection(autocommit=False)
    archived=False; audit_id=None; details=None
    try:
        with conn.cursor() as cursor:
            cursor.execute("""SELECT id,first_name,middle_name,last_name,email,username,block,lot,
                homeowner_public_id,verification_status FROM users
                WHERE id=%s AND role='Homeowner' FOR UPDATE""",(user_id,))
            u=cursor.fetchone()
            if not u or u['verification_status']!='Pending Verification':
                conn.rollback(); return jsonify(status='error',message='Registration already reviewed or missing'),409
            cursor.execute("""SELECT id FROM users WHERE homeowner_public_id=%s AND id<>%s
                AND role='Homeowner' AND verification_status='Verified' LIMIT 1""",(u['homeowner_public_id'],user_id))
            if cursor.fetchone():
                conn.rollback();return jsonify(status='error',message='Homeowner ID is already verified elsewhere'),409
            # B12-11: account verification and property claims are separate HOA decisions.
            # New enrollment accounts must finish claim review before activation.
            cursor.execute("""SELECT COUNT(*) total,
                  SUM(status='Verified') verified,
                  SUM(status IN ('Pending','Disputed')) outstanding,
                  SUM(status='Verified' AND UPPER(TRIM(block))=UPPER(TRIM(%s))
                      AND UPPER(TRIM(lot))=UPPER(TRIM(%s))) primary_verified
                  FROM nfh_property_claims WHERE claimant_user_id=%s AND claim_type='Ownership'""",
                  (u['block'],u['lot'],user_id))
            claim_state=cursor.fetchone() or {}
            if action=='verify' and int(claim_state.get('total') or 0)>0:
                if (not int(claim_state.get('primary_verified') or 0)
                    or int(claim_state.get('outstanding') or 0)):
                    conn.rollback()
                    return jsonify(status='error',message='Complete individual property claim reviews and verify the primary property before activating this homeowner account.'),409
            if action=='reject' and int(claim_state.get('verified') or 0)>0:
                conn.rollback()
                return jsonify(status='error',message='A verified property ownership relationship exists. Resolve or revoke that relationship through an authorized HOA process before rejecting this account.'),409
            if action=='reject' and int(claim_state.get('total') or 0)>0:
                archived=True
                cursor.execute("""UPDATE nfh_property_claims SET status='Rejected',review_note=%s,
                    reviewed_by=%s,reviewed_at=UTC_TIMESTAMP()
                    WHERE claimant_user_id=%s AND status IN ('Pending','Disputed')""",
                    (reason[:500],session['user_id'],user_id))
            if action == 'verify':
                cursor.execute("""UPDATE users SET verification_status='Verified',status='Active',
                   verified_by=%s,verified_at=NOW() WHERE id=%s AND verification_status='Pending Verification'""",
                   (session.get('username'),user_id))
                if cursor.rowcount!=1: raise RuntimeError('Concurrent verification conflict')
            else:
                occupied=_registration_dependencies(cursor,user_id)
                archived=archived or bool(occupied)
                cursor.execute("""INSERT INTO nfh_registration_rejections
                    (original_user_id,homeowner_name,homeowner_public_id,block_no,lot_no,
                    email,rejection_reason,rejected_by,cleanup_result,notification_status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'Pending')""",
                    (user_id,' '.join(x for x in (u['first_name'],u.get('middle_name'),u['last_name']) if x),
                     u['homeowner_public_id'],u['block'],u['lot'],u['email'],reason,
                     session.get('username'), 'Archived' if archived else 'Deleted'))
                audit_id=cursor.lastrowid
                if archived:
                    # Retain all FK-linked history; vacate public property ID, never internal ID.
                    cursor.execute("""UPDATE users SET verification_status='Rejected',status='Inactive',
                         homeowner_public_id=NULL,verified_by=%s,verified_at=NOW() WHERE id=%s""",
                         (session.get('username'),user_id))
                else:
                    cursor.execute("DELETE FROM users WHERE id=%s AND role='Homeowner' AND verification_status='Pending Verification'",(user_id,))
                    if cursor.rowcount!=1: raise RuntimeError('Concurrent rejection conflict')
            cursor.execute("""INSERT INTO audit_logs(username,role,action,item,prev_val,new_val)
                 VALUES (%s,'Admin',%s,%s,'Pending Verification',%s)""",
                 (session.get('username'),'Homeowner Verified' if action=='verify' else 'Homeowner Rejected',
                  u['username'],'Verified' if action=='verify' else ('Rejected; '+('Archived' if archived else 'Deleted'))))
            if action == 'verify':
                # Apply only verified, exact ID + identity matches in the verification transaction.
                # Missing optional migration must not silently corrupt/interrupt verification.
                from homeowner_reconciliation import reconcile_future_account
                reconcile_future_account(cursor,user_id,session['user_id'])
            details=u.copy()
        conn.commit()
    except Exception:
        conn.rollback();app.logger.exception('Homeowner registration decision failed')
        return jsonify(status='error',message='Registration decision could not be committed.'),500
    finally:
        conn.close()
    # External mail is deliberately after commit. Rejected applications may no longer exist in users.
    try:
        if action=='verify':
            send_alert_and_email(user_id,'NFH-HOA | Your Homeowner Account Has Been Verified',
                'Your homeowner registration has been verified. You may now sign in.',
                related_type='homeowner_registration',related_id=str(user_id),
                dedupe_key=f'homeowner-registration-verified-{user_id}',important=True)
        else:
            from nfh_status_emails import render_status_email
            name=' '.join(x for x in (details['first_name'],details.get('middle_name'),details['last_name']) if x)
            html_text, plain_text=render_status_email('account_rejected', name,
                details={'Homeowner ID': details.get('homeowner_public_id') or '', 'remarks': reason})
            msg=Message('NFH-HOA | Homeowner Registration Not Approved',recipients=[details['email']])
            msg.body=plain_text;msg.html=html_text
            if not app.config.get('MAIL_USERNAME'): raise RuntimeError('SMTP is not configured')
            mail.send(msg)
            delivery='Sent'
    except Exception:
        delivery='Failed';app.logger.exception('Registration decision committed; email delivery failed')
    if action=='reject':
        track=get_db_connection(autocommit=False)
        try:
            with track.cursor() as cursor:
                cursor.execute("UPDATE nfh_registration_rejections SET notification_status=%s WHERE id=%s",(delivery,audit_id))
            track.commit()
        except Exception: track.rollback();app.logger.exception('Could not record mail status')
        finally: track.close()
    return jsonify(status='success',message='Account verified.' if action=='verify' else 'Registration rejected.',
                   cleanup='Archived' if archived else 'Deleted' if action=='reject' else None,
                   email_status=delivery if action=='reject' else 'Processed')

@app.route('/admin/homeowners/<int:user_id>/edit', methods=['POST'])
def admin_edit_homeowner(user_id):
    if 'user_id' not in session or session.get('role') != 'Admin':
        return redirect(url_for('index'))
    first=normalize_unicode_text(request.form.get('first_name'))
    middle=normalize_unicode_text(request.form.get('middle_name'))
    last=normalize_unicode_text(request.form.get('last_name'))
    suffix=normalize_unicode_text(request.form.get('suffix'))
    email=normalize_unicode_text(request.form.get('email')).lower()
    mobile=(request.form.get('mobile') or '').strip()
    block=normalize_unicode_text(request.form.get('block'))
    lot=normalize_unicode_text(request.form.get('lot'))
    address_line=normalize_unicode_text(request.form.get('address_line'))
    try:
        household=max(1,min(30,int(request.form.get('household') or 1)))
    except (TypeError,ValueError):
        flash('Household members must be a valid number between 1 and 30.', 'error')
        return redirect(url_for('admin')+'#homeowners')
    if not first or not last or not email or not mobile:
        flash('First name, last name, email, and mobile number are required.', 'error')
        return redirect(url_for('admin')+'#homeowners')
    if not valid_person_name(first) or not valid_person_name(last) or (middle and not valid_person_name(middle, required=False)):
        flash('Homeowner names contain invalid characters.', 'error')
        return redirect(url_for('admin')+'#homeowners')
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        flash('Enter a valid homeowner email address.', 'error')
        return redirect(url_for('admin')+'#homeowners')
    if not re.match(r'^09\d{9}$', mobile):
        flash('Mobile number must contain 11 digits and start with 09.', 'error')
        return redirect(url_for('admin')+'#homeowners')
    try:
        conn=get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id=%s AND role='Homeowner'", (user_id,))
            old=cursor.fetchone()
            if not old:
                conn.close(); flash('Homeowner account not found.', 'error'); return redirect(url_for('admin')+'#homeowners')
            cursor.execute("SELECT id FROM users WHERE id<>%s AND LOWER(email)=LOWER(%s)", (user_id,email))
            if cursor.fetchone():
                conn.close(); flash('That email address is already used by another account.', 'error'); return redirect(url_for('admin')+'#homeowners')
            cursor.execute("""UPDATE users SET first_name=%s,middle_name=%s,last_name=%s,suffix=%s,email=%s,mobile=%s,
                              block=%s,lot=%s,address_line=%s,household=%s WHERE id=%s""",
                           (first,middle or None,last,suffix or None,email,mobile,block or None,lot or None,address_line or None,household,user_id))
        conn.close()
        before={k:old.get(k) for k in ('first_name','middle_name','last_name','suffix','email','mobile','block','lot','address_line','household')}
        after={'first_name':first,'middle_name':middle,'last_name':last,'suffix':suffix,'email':email,'mobile':mobile,'block':block,'lot':lot,'address_line':address_line,'household':household}
        log_audit_action(session.get('username'),'Admin','Edit Homeowner Record',old.get('homeowner_public_id') or old.get('username'),json.dumps(before,default=str,ensure_ascii=False),json.dumps(after,ensure_ascii=False))
        flash('Homeowner record updated successfully.', 'success')
    except Exception:
        app.logger.exception('Admin homeowner update failed for %s', user_id)
        flash('Unable to update the homeowner record right now.', 'error')
    return redirect(url_for('admin')+'#homeowners')


@app.route('/admin/homeowners/<int:user_id>/toggle-status', methods=['POST'])
def admin_toggle_homeowner_status(user_id):
    if 'user_id' not in session or session.get('role') != 'Admin':
        return redirect(url_for('index'))
    try:
        conn=get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT username,homeowner_public_id,status,verification_status FROM users WHERE id=%s AND role='Homeowner'", (user_id,))
            homeowner=cursor.fetchone()
            if not homeowner:
                conn.close(); flash('Homeowner account not found.', 'error'); return redirect(url_for('admin')+'#homeowners')
            if homeowner.get('verification_status') != 'Verified':
                conn.close(); flash('Only verified homeowner accounts can be activated or deactivated here. Use Homeowner Verification for pending registrations.', 'warning'); return redirect(url_for('admin')+'#homeowners')
            new_status='Inactive' if homeowner.get('status') == 'Active' else 'Active'
            cursor.execute("UPDATE users SET status=%s WHERE id=%s AND role='Homeowner'", (new_status,user_id))
        conn.close()
        label=homeowner.get('homeowner_public_id') or homeowner.get('username')
        log_audit_action(session.get('username'),'Admin','Toggle Homeowner Status',label,homeowner.get('status'),new_status)
        flash(f'Homeowner account updated to {new_status}. Historical requests, dues, payments, and issued documents were preserved.', 'success')
    except Exception:
        app.logger.exception('Homeowner status update failed for %s', user_id)
        flash('Unable to update the homeowner account status right now.', 'error')
    return redirect(url_for('admin')+'#homeowners')


@app.route('/admin/service-types/save', methods=['POST'])
def save_service_type():
    if 'user_id' not in session or session.get('role') != 'Admin':
        return redirect(url_for('index'))

    service_id_raw = (request.form.get('service_id') or '').strip()
    name = (request.form.get('service_name') or '').strip()
    category = (request.form.get('category') or 'Document Request').strip()
    reviewer = (request.form.get('initial_reviewer') or 'Secretary').strip()
    release_role = (request.form.get('release_role') or 'Secretary').strip()
    form_template = (request.form.get('form_template') or 'generic').strip()
    description = (request.form.get('description') or '').strip()[:255]
    # An empty fee is not the same thing as an explicitly entered zero.
    fee_raw = str(request.form.get('fee') if request.form.get('fee') is not None else '').strip()
    requires_executive = int(bool(request.form.get('requires_executive')))
    requires_payment = int(bool(request.form.get('requires_payment')))
    requires_dues_clearance = int(bool(request.form.get('requires_dues_clearance')))
    purpose_required = int(bool(request.form.get('purpose_required')))

    valid_categories = set(VALID_CATEGORIES)
    valid_reviewers = {'Secretary', 'Treasurer', 'Shared'}
    valid_release_roles = {'Secretary', 'Treasurer', 'Initial Reviewer'}
    valid_templates = {'generic','gate-pass','proof-residency','cert-improvement','cert-membership','move-in','move-out','vehicle-sticker','tenant-form'}
    if not name or category not in valid_categories or reviewer not in valid_reviewers or release_role not in valid_release_roles or form_template not in valid_templates:
        flash('Provide a valid service name, category, reviewer, release role and form template.', 'error')
        return redirect(url_for('admin') + '#services')
    # DECIMAL(10,2) in the existing database; preserve exact cents and reject NaN/Infinity.
    from decimal import Decimal, InvalidOperation
    try:
        if not fee_raw:
            raise ValueError('Service fee is required (enter 0.00 for a free service).')
        amount = Decimal(fee_raw)
        if not amount.is_finite() or amount < 0 or amount > Decimal('99999999.99') or amount.as_tuple().exponent < -2:
            raise ValueError('Enter a non-negative service fee with at most two decimal places.')
        fee = amount
    except (InvalidOperation, ValueError) as exc:
        flash(str(exc) if isinstance(exc, ValueError) else 'Enter a valid numeric service fee.', 'error')
        return redirect(url_for('admin') + '#services')
    if not requires_payment and form_template != 'vehicle-sticker':
        fee = Decimal('0.00')
    # A zero-priced service never requires a request-fee cash transaction.
    # Vehicle stickers retain their independently configured per-vehicle pricing.
    if fee == 0 and form_template != 'vehicle-sticker':
        requires_payment = 0

    service_id = None
    if service_id_raw:
        try:
            service_id = int(service_id_raw)
        except ValueError:
            flash('Invalid service record selected.', 'error')
            return redirect(url_for('admin') + '#services')

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if service_id is not None:
                cursor.execute('SELECT * FROM service_types WHERE id=%s', (service_id,))
                old = cursor.fetchone()
                if not old:
                    flash('Service type not found.', 'error')
                    return redirect(url_for('admin') + '#services')
                cursor.execute('SELECT id FROM service_types WHERE LOWER(service_name)=LOWER(%s) AND id<>%s', (name, service_id))
                if cursor.fetchone():
                    flash('Another service already uses that name.', 'error')
                    return redirect(url_for('admin') + '#services')
                old_name = old['service_name']
                if old_name != name:
                    # Historical requests store the service name. Renaming a service
                    # that already has transactions would detach those requests from
                    # their workflow configuration, so preserve the identifier and
                    # require a new service record instead.
                    cursor.execute('SELECT COUNT(*) AS total FROM requests WHERE request_type=%s', (old_name,))
                    request_total = int((cursor.fetchone() or {}).get('total') or 0)
                    if request_total > 0:
                        flash('This service already has request history and cannot be renamed. Create a new service and deactivate the old service instead.', 'error')
                        return redirect(url_for('admin') + '#services')
                    cursor.execute('SELECT item_name FROM fees WHERE item_name=%s', (name,))
                    if cursor.fetchone():
                        flash('A fee record already uses the new service name. Choose another name.', 'error')
                        return redirect(url_for('admin') + '#services')
                cursor.execute("""UPDATE service_types
                                  SET service_name=%s, category=%s, fee=%s, initial_reviewer=%s,
                                      requires_executive=%s, requires_payment=%s, requires_dues_clearance=%s,
                                      purpose_required=%s, release_role=%s, form_template=%s, description=%s
                                  WHERE id=%s""",
                               (name, category, fee, reviewer, requires_executive, requires_payment,
                                requires_dues_clearance, purpose_required, release_role, form_template, description, service_id))
                if old_name != name:
                    cursor.execute('UPDATE fees SET item_name=%s, amount=%s WHERE item_name=%s', (name, fee, old_name))
                    if cursor.rowcount == 0 and form_template != 'vehicle-sticker':
                        cursor.execute("INSERT INTO fees(item_name,amount,status) VALUES(%s,%s,'Active')", (name, fee))
                elif form_template != 'vehicle-sticker':
                    cursor.execute("INSERT INTO fees(item_name,amount,status) VALUES(%s,%s,'Active') ON DUPLICATE KEY UPDATE amount=VALUES(amount)", (name, fee))
                previous = f"{old['service_name']} | {old['category']} | {old['fee']} | {old['initial_reviewer']}"
                current = f"{name} | {category} | {fee:.2f} | {reviewer} | exec={requires_executive} | payment={requires_payment} | dues={requires_dues_clearance} | release={release_role}"
                log_audit_action(session.get('username'), 'Admin', 'Edit Service Type', name, previous, current)
                flash('Service configuration updated successfully.', 'success')
            else:
                cursor.execute('SELECT id FROM service_types WHERE LOWER(service_name)=LOWER(%s)', (name,))
                if cursor.fetchone():
                    flash('That service already exists. Use Edit to update it.', 'error')
                    return redirect(url_for('admin') + '#services')
                cursor.execute("""INSERT INTO service_types
                                  (service_name,category,fee,initial_reviewer,requires_executive,requires_payment,
                                   requires_dues_clearance,purpose_required,release_role,form_template,description)
                                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                               (name, category, fee, reviewer, requires_executive, requires_payment,
                                requires_dues_clearance, purpose_required, release_role, form_template, description))
                if form_template != 'vehicle-sticker':
                    cursor.execute("INSERT INTO fees(item_name,amount,status) VALUES(%s,%s,'Active') ON DUPLICATE KEY UPDATE amount=VALUES(amount)", (name, fee))
                log_audit_action(session.get('username'), 'Admin', 'Create Service Type', name, None,
                                 f"{category} | {fee:.2f} | {reviewer} | release={release_role}")
                flash('Service type added successfully.', 'success')
    except pymysql.IntegrityError:
        flash('Unable to save the service because the name conflicts with an existing record.', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin') + '#services')


@app.route('/admin/service-types/<int:service_id>/toggle', methods=['POST'])
def toggle_service_type(service_id):
    if 'user_id' not in session or session.get('role')!='Admin': return redirect(url_for('index'))
    conn=get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT service_name,status FROM service_types WHERE id=%s",(service_id,)); row=cursor.fetchone()
            if row:
                new='Inactive' if row['status']=='Active' else 'Active'; cursor.execute("UPDATE service_types SET status=%s WHERE id=%s",(new,service_id)); log_audit_action(session.get('username'),'Admin','Toggle Service Type',row['service_name'],row['status'],new)
    finally: conn.close()
    return redirect(url_for('admin')+'#services')


@app.route('/admin/document-templates/<template_key>/save', methods=['POST'])
def save_document_template(template_key):
    if 'user_id' not in session or session.get('role') != 'Admin':
        return redirect(url_for('index'))
    title=(request.form.get('title') or '').strip()
    body=template_text_to_internal((request.form.get('body_text') or '').strip())
    footer=template_text_to_internal((request.form.get('footer_text') or '').strip())
    allowed_sig_roles={'Secretary','Treasurer','President'}
    required_signatures=','.join([r for r in request.form.getlist('required_signatures') if r in allowed_sig_roles])
    if not title or not body:
        flash('Template title and body are required.','error')
        return redirect(url_for('admin')+'#templates')
    try:
        conn=get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""SELECT * FROM document_templates WHERE template_key=%s AND status='Active'
                              ORDER BY version_no DESC LIMIT 1""",(template_key,))
            current=cursor.fetchone()
            if not current:
                conn.close(); flash('Document template not found.','error'); return redirect(url_for('admin')+'#templates')
            next_version=int(current.get('version_no') or 0)+1
            cursor.execute("UPDATE document_templates SET status='Archived' WHERE template_key=%s AND status='Active'",(template_key,))
            cursor.execute("""INSERT INTO document_templates
                (template_key,service_name,version_no,title,body_text,footer_text,required_signatures,status,updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'Active',%s)""",
                (template_key,current.get('service_name'),next_version,title,body,footer,required_signatures,
                 session.get('username') or 'Admin'))
        conn.close()
        log_audit_action(session.get('username'),'Admin','Update Document Template',template_key,
                         f"Version {current.get('version_no')}",f"Version {next_version}")
        flash(f'Document template updated to version {next_version}. Existing requests keep their original version.','success')
    except Exception:
        app.logger.exception('Document template update failed for %s',template_key)
        flash('Unable to update the document template right now.','error')
    return redirect(url_for('admin')+'#templates')


@app.route('/officer/issue_request/<req_id>', methods=['POST'])
def issue_request(req_id):
    if 'user_id' not in session or session.get('role') not in ['Secretary','Treasurer','Admin']:
        return redirect(url_for('index'))
    remarks=(request.form.get('release_remarks') or '').strip()
    sticker_from=(request.form.get('sticker_valid_from') or '').strip()
    sticker_until=(request.form.get('sticker_valid_until') or '').strip()
    conn=get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""SELECT status,user_id,request_type,assigned_officer
                              FROM requests WHERE id=%s""",(req_id,))
            req=cursor.fetchone()
            if not req or req['status']!='Ready for Release':
                flash('Only Ready for Release requests can be issued.','error')
                return redirect(url_for('officer'))
            service=get_service_config(cursor,req['request_type'],active_only=False)
            allowed=release_roles_for_request(service,req.get('assigned_officer'))
            if session.get('role')!='Admin' and session.get('role') not in allowed:
                flash('Your role is not authorized to issue this service.','error')
                return redirect(url_for('officer'))
            is_vehicle = bool(service and service.get('form_template')=='vehicle-sticker') or req['request_type']=='Vehicle Sticker Application'
            valid_from=None; valid_until=None
            if is_vehicle:
                if not sticker_from or not sticker_until:
                    flash('Vehicle sticker validity dates are required before issuance.','error')
                    return redirect(url_for('officer'))
                try:
                    valid_from=datetime.strptime(sticker_from,'%Y-%m-%d').date()
                    valid_until=datetime.strptime(sticker_until,'%Y-%m-%d').date()
                except ValueError:
                    flash('Enter valid sticker validity dates.','error')
                    return redirect(url_for('officer'))
                if valid_until < valid_from:
                    flash('Sticker expiration date cannot be earlier than the start date.','error')
                    return redirect(url_for('officer'))
            cursor.execute("""UPDATE requests SET status='Issued / Completed',issued_at=NOW(),issued_by=%s,
                              sticker_valid_from=%s,sticker_valid_until=%s WHERE id=%s""",
                           (session.get('full_name') or session.get('username'),valid_from,valid_until,req_id))
            template=get_active_document_template(cursor,request_type=req['request_type'])
            snapshot_request_signatures(cursor,req_id,template)
        record_note=remarks
        if valid_from and valid_until:
            record_note=(record_note + ' | ' if record_note else '') + f'Sticker valid {valid_from.isoformat()} to {valid_until.isoformat()}'
        record_request_history(req_id,'Issued / Completed','Ready for Release','Issued / Completed',record_note)
        log_audit_action(session.get('username'),session.get('role'),'Issue Document',req_id,'Ready for Release','Issued / Completed')
        body=f"Your {req['request_type']} request {req_id} has been issued/completed."
        if valid_from and valid_until:
            body += f" Sticker validity: {valid_from.strftime('%B %d, %Y')} to {valid_until.strftime('%B %d, %Y')}."
        send_alert_and_email(req['user_id'],'Request Completed',body,related_type='request',related_id=req_id,dedupe_key=f'issued-{req_id}')
        flash('Request marked as Issued / Completed.','success')
    finally:
        conn.close()
    return redirect(url_for('officer'))


# ===========================================================================
# ADMIN ACCOUNT MANAGEMENT
# ===========================================================================
@app.route('/create-officer', methods=['POST'])
def create_officer():
    if 'user_id' not in session or session.get('role') != 'Admin':
        return redirect(url_for('index'))
    full_name = normalize_unicode_text(request.form.get('full_name', ''))
    username = normalize_unicode_text(request.form.get('username', ''))
    email = normalize_unicode_text(request.form.get('email', '')).lower()
    phone = request.form.get('phone', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'Secretary')

    if not all([full_name, username, email, phone, password, role]):
        flash('Full Name, Username, Email, Phone Number, Password, and Role are all required.', 'error')
        return redirect(url_for('admin'))
    if not valid_person_name(full_name):
        flash('Full Name may contain letters, spaces, hyphens, apostrophes, and periods only.', 'error')
        return redirect(url_for('admin'))
    if len(password) < 8:
        flash('Password must be at least 8 characters.', 'error')
        return redirect(url_for('admin'))
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        flash('Please enter a valid email address.', 'error')
        return redirect(url_for('admin'))
    if not re.match(r'^09\d{9}$', phone):
        flash('Phone number must contain 11 digits and start with 09.', 'error')
        return redirect(url_for('admin'))
    if role not in ['Secretary', 'Treasurer', 'President', 'Vice President', 'Board Director']:
        flash('Invalid role selected.', 'error')
        return redirect(url_for('admin'))

    name_parts = full_name.split(' ', 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else 'Officer'
    pwd_hash = generate_password_hash(password, method='pbkdf2:sha256')
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE username=%s OR email=%s", (username, email))
            if cursor.fetchone():
                conn.close()
                flash('Username or email already exists.', 'error')
                return redirect(url_for('admin'))

            cursor.execute("""INSERT INTO users
                (first_name, last_name, username, email, mobile, password_hash, role, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'Active')""",
                           (first_name, last_name, username, email, phone, pwd_hash, role))
        conn.close()
        log_audit_action(session.get('username'), session.get('role'),
                         'Create Officer Account', username, None, role)
        flash(f'Officer account {username} created successfully.', 'success')
    except pymysql.IntegrityError:
        flash('Username or email already exists.', 'error')
    except Exception:
        app.logger.exception('Officer account creation failed')
        flash('Unable to create the officer account right now. Please try again.', 'error')
    return redirect(url_for('admin'))


@app.route('/edit-officer/<int:officer_id>', methods=['POST'])
def edit_officer(officer_id):
    if 'user_id' not in session or session.get('role') != 'Admin':
        return redirect(url_for('index'))
    full_name = normalize_unicode_text(request.form.get('full_name', ''))
    username = normalize_unicode_text(request.form.get('username', ''))
    email = normalize_unicode_text(request.form.get('email', '')).lower()
    phone = request.form.get('phone', '').strip()
    role = request.form.get('role', '').strip()
    if not all([full_name, username, email, phone, role]) or role not in ['Secretary','Treasurer','President','Vice President','Board Director']:
        flash('Provide valid officer information and an allowed officer role.', 'error')
        return redirect(url_for('admin') + '#officers')
    if not valid_person_name(full_name):
        flash('Full Name may contain letters, spaces, hyphens, apostrophes, and periods only.', 'error')
        return redirect(url_for('admin') + '#officers')
    if not re.match(r'^09\d{9}$', phone):
        flash('Phone number must contain 11 digits and start with 09.', 'error')
        return redirect(url_for('admin') + '#officers')
    parts = full_name.split(' ', 1); first = parts[0]; last = parts[1] if len(parts)>1 else 'Officer'
    try:
        conn=get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id=%s AND role IN ('Secretary','Treasurer','President','Vice President','Board Director')", (officer_id,))
            old=cursor.fetchone()
            if not old:
                conn.close(); flash('Officer account not found.', 'error'); return redirect(url_for('admin')+'#officers')
            cursor.execute("SELECT id FROM users WHERE id<>%s AND (LOWER(username)=LOWER(%s) OR LOWER(email)=LOWER(%s))", (officer_id,username,email))
            if cursor.fetchone():
                conn.close(); flash('Username or email already belongs to another account.', 'error'); return redirect(url_for('admin')+'#officers')
            cursor.execute("UPDATE users SET first_name=%s,last_name=%s,username=%s,email=%s,mobile=%s,role=%s WHERE id=%s",
                           (first,last,username,email,phone,role,officer_id))
        conn.close()
        log_audit_action(session.get('username'), 'Admin', 'Edit Officer Account', username,
                         f"{old['username']} | {old['email']} | {old['mobile']} | {old['role']}",
                         f"{username} | {email} | {phone} | {role}")
        flash(f'Officer account {username} updated successfully.', 'success')
    except pymysql.IntegrityError:
        flash('Username or email already exists.', 'error')
    except Exception:
        app.logger.exception('Officer account update failed for %s', officer_id)
        flash('Unable to update the officer account right now. Please try again.', 'error')
    return redirect(url_for('admin') + '#officers')


@app.route('/toggle-officer-status/<int:officer_id>', methods=['POST'])
def toggle_officer_status(officer_id):
    if 'user_id' not in session or session.get('role') != 'Admin':
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT username, status FROM users WHERE id=%s AND role IN ('Secretary','Treasurer','President','Vice President','Board Director')", (officer_id,))
            off = cursor.fetchone()
            if off:
                new_status = 'Inactive' if off['status'] == 'Active' else 'Active'
                cursor.execute("UPDATE users SET status=%s WHERE id=%s AND role IN ('Secretary','Treasurer','President','Vice President','Board Director')", (new_status, officer_id))
                log_audit_action(session.get('username'), session.get('role'),
                                 'Toggle Officer Status', off['username'], off['status'], new_status)
                flash(f'Status for {off["username"]} updated to {new_status}.', 'success')
        conn.close()
    except Exception:
        app.logger.exception('Officer status update failed for %s', officer_id)
        flash('Unable to update the officer status right now. Please try again.', 'error')
    return redirect(url_for('admin'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ===========================================================================
# AUTHENTICATION APIS
# ===========================================================================
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if not username or not password:
        return jsonify({'status': 'error', 'message': 'Username and password required.'}), 400
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE LOWER(username)=LOWER(%s) OR LOWER(email)=LOWER(%s)",
                           (username, username))
            user = cursor.fetchone()
        conn.close()
        if not user or not check_password_hash(user['password_hash'], password):
            return jsonify({'status': 'error', 'message': 'Invalid username or password.'}), 401
        if user.get('role')=='Renter' and user.get('verification_status')!='Verified':
            return jsonify({'status':'error','message':'Complete renter email verification before signing in.'}),403
        if user.get('role')=='Homeowner' and user.get('verification_status')=='Pending Verification':
            return jsonify({'status':'error','message':'Your homeowner registration is still pending HOA verification.'}),403
        if user.get('role')=='Homeowner' and user.get('verification_status')=='Rejected':
            return jsonify({'status':'error','message':'Your homeowner registration was not verified. Please contact the HOA office.'}),403
        if user['status'] != 'Active':
            return jsonify({'status':'error','message':'Your account is inactive. Please contact the HOA office.'}),403
        _set_login_session(user)
        redirect_url = _role_home_url(user['role'])
        log_audit_action(user['username'], user['role'], 'User Login', user['username'])
        return jsonify({'status': 'success', 'redirect': redirect_url})
    except Exception as e:
        app.logger.exception('Login failed due to an internal error')
        return jsonify({'status': 'error', 'message': 'Unable to sign in right now. Please try again.'}), 500


@app.route('/api/send-registration-code', methods=['POST'])
def send_reg_code():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) or len(email) > 254:
        return jsonify({'status':'error','message':'Enter a valid email address.'}), 400
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT id FROM users WHERE LOWER(email)=LOWER(%s) LIMIT 1', (email,))
                if cursor.fetchone():
                    return jsonify({'status':'error','message':'An account already uses this email address.'}), 409
        finally:
            conn.close()
    except Exception:
        app.logger.exception('Registration email uniqueness lookup failed')
        return jsonify({'status':'error','message':'Unable to check registration information right now.'}), 500
    previous = VERIFICATION_CODES.get(email)
    code, wait_seconds = _issue_one_time_code(VERIFICATION_CODES, email)
    if code is None:
        return jsonify({'status':'error','message':f'Please wait {wait_seconds} second(s) before requesting another code.', 'retry_after':wait_seconds}), 429
    try:
        msg = Message('NFH-HOA | Verify Your Account', recipients=[email])
        msg.body = (f'Your NFH-HOA registration verification code is: {code}\n\n'
                    f'This code expires in {OTP_TTL_SECONDS // 60} minutes.\n'
                    'Do not share this code with anyone.\n'
                    'If you did not request this code, please disregard this email.')
        msg.html = render_template('emails/verification.html', code=code,
            title='Verify Your Account', description='Enter the verification code below to complete your registration.',
            expiry_minutes=OTP_TTL_SECONDS // 60,
            security_message='If you did not request this code, please disregard this email.')
        _send_system_message(msg, 'registration_otp')
        return jsonify({'status':'success','message':'Verification code sent successfully. Please check your email.'})
    except (ValueError, smtplib.SMTPException, ssl.SSLError, OSError, TimeoutError):
        if previous is None: VERIFICATION_CODES.pop(email, None)
        else: VERIFICATION_CODES[email] = previous
        return jsonify({'status':'error','message':"We couldn't send your verification code. Please try again shortly."}), 503
    except Exception:
        if previous is None: VERIFICATION_CODES.pop(email, None)
        else: VERIFICATION_CODES[email] = previous
        app.logger.exception('Unexpected registration email delivery failure')
        return jsonify({'status':'error','message':"We couldn't send your verification code. Please try again shortly."}), 503

@app.route('/api/verify-registration-code', methods=['POST'])
def verify_reg_code():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    code = (data.get('code') or '').strip()
    ok, message = _verify_one_time_code(VERIFICATION_CODES, email, code, mark_verified=True)
    if ok:
        return jsonify({'status': 'success', 'message': 'Email verified.'})
    return jsonify({'status': 'error', 'message': 'The verification code is invalid or has expired. Please request a new code.'}), 400

@app.route('/api/register', methods=['POST'])
def api_register():
    data=request.get_json() or {}
    first=normalize_unicode_text(data.get('first_name')); middle=normalize_unicode_text(data.get('middle_name')); last=normalize_unicode_text(data.get('last_name')); suffix=normalize_unicode_text(data.get('suffix'))
    email=(data.get('email') or '').strip().lower(); username=(data.get('username') or '').strip(); mobile=(data.get('phone') or '').strip(); password=data.get('password') or ''
    block=(data.get('block') or '').strip(); lot=(data.get('lot') or '').strip(); address_line=(data.get('address_line') or '').strip()
    from first_time_enrollment import normalize_claim, save_claim
    try:
        claims=[normalize_claim({'block':block,'lot':lot,'evidence_note':data.get('evidence_note')})]
        for item in (data.get('additional_properties') or []):claims.append(normalize_claim(item))
        if len(claims)>10 or len(set((b,l) for b,l,_ in claims))!=len(claims):
            return jsonify({'status':'error','message':'Provide up to 10 distinct property claims.'}),400
    except (ValueError,TypeError):
        return jsonify({'status':'error','message':'Invalid property claim details.'}),400
    gender=(data.get('gender') or 'NA').strip(); dob=(data.get('dob') or '').strip() or None; civil_status=(data.get('civil_status') or 'Single').strip()
    try: household=max(1, min(30, int(data.get('household') or 1)))
    except (TypeError, ValueError): household=1
    emergency_name=(data.get('emergency_name') or '').strip(); emergency_number=(data.get('emergency_number') or '').strip(); emergency_relationship=(data.get('emergency_relationship') or '').strip()
    if not all([first,last,email,username,mobile,password,block,lot,address_line]):
        return jsonify({'status':'error','message':'Complete all required identity, contact, Block/Lot, and address fields.'}),400
    if not valid_person_name(first) or not valid_person_name(last) or (middle and not valid_person_name(middle, required=False)):
        return jsonify({'status':'error','message':'Names may contain Unicode letters such as Ñ/ñ, spaces, hyphens, apostrophes, and periods only.'}),400
    if not _registration_email_verified(email):
        return jsonify({'status':'error','message':'Verify your email address before creating the account.'}),400
    if len(password)<8: return jsonify({'status':'error','message':'Password must be at least 8 characters.'}),400
    if not re.match(r'^09\d{9}$',mobile): return jsonify({'status':'error','message':'Phone number must contain 11 digits and start with 09.'}),400
    if emergency_number and not re.match(r'^09\d{9}$', emergency_number):
        return jsonify({'status':'error','message':'Emergency contact number must contain 11 digits and start with 09, or be left blank.'}),400
    conn=None
    try:
        conn=get_db_connection(autocommit=False)
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(%s) OR LOWER(username)=LOWER(%s) LIMIT 1", (email, username))
            if cursor.fetchone():
                conn.close()
                return jsonify({'status':'error','message':'Email or username already registered.'}), 409
            public_id=generate_homeowner_public_id(cursor,block,lot)
            cursor.execute("""INSERT INTO users
                              (first_name,middle_name,last_name,suffix,gender,dob,civil_status,block,lot,address_line,household,
                               email,username,mobile,password_hash,role,status,homeowner_public_id,verification_status,
                               emergency_contact_name,emergency_contact_number,emergency_contact_relationship)
                              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Homeowner','Inactive',%s,'Pending Verification',%s,%s,%s)""",
                           (first,middle or None,last,suffix or None,gender,dob,civil_status,block,lot,address_line,household,
                            email,username,mobile,generate_password_hash(password,method='pbkdf2:sha256'),public_id,
                            emergency_name or None,emergency_number or None,emergency_relationship or None))
            account_id=cursor.lastrowid
            for cb,cl,ce in claims:
                save_claim(cursor,account_id,'Ownership',cb,cl,ce)
        conn.commit()
        conn.close(); VERIFICATION_CODES.pop(email,None)
        return jsonify({'status':'success','message':'Registration submitted. Your account is pending HOA homeowner verification before sign-in.'})
    except pymysql.IntegrityError:
        if conn:conn.rollback();conn.close()
        return jsonify({'status':'error','message':'Username, email, or Homeowner ID already exists.'}),400
    except Exception:
        if conn:conn.rollback();conn.close()
        app.logger.exception('Homeowner registration failed for %s', email)
        return jsonify({'status':'error','message':'Unable to complete registration right now. Please try again.'}),500


@app.route('/api/forgot-password/send-code', methods=['POST'])
def forgot_send_code():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    generic_message = 'If that email is registered, a reset code will be sent.'
    if not email:
        return jsonify({'status': 'error', 'message': 'Enter the email address registered to your account.'}), 400
    if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        return jsonify({'status': 'error', 'message': 'Enter a valid email address.'}), 400

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, email, status FROM users WHERE LOWER(email)=LOWER(%s) LIMIT 1", (email,))
            user = cursor.fetchone()
        conn.close()
    except Exception:
        app.logger.exception('Password reset lookup failed')
        return jsonify({'status': 'error', 'message': 'Unable to process the reset request right now.'}), 500

    # Do not reveal whether an arbitrary public email has an account.
    if not user:
        time.sleep(0.15)
        return jsonify({'status': 'success', 'message': generic_message})

    code, wait_seconds = _issue_one_time_code(RESET_CODES, email)
    if code is None:
        return jsonify({'status': 'error', 'message': f'Please wait {wait_seconds} second(s) before requesting another reset code.'}), 429

    # Seeded @nfhhoa.local accounts cannot receive real mail. For localhost-only
    # capstone/demo use, expose the OTP explicitly instead of silently failing.
    if _is_local_demo_reset(email):
        app.logger.warning('[LOCAL DEMO OTP] Password reset code for %s: %s', email, code)
        return jsonify({
            'status': 'success',
            'message': 'Local demo account detected. Use the verification code shown below.',
            'demo_code': code,
            'delivery': 'local_demo'
        })

    if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
        if DEV_SHOW_OTP:
            app.logger.warning('[DEV OTP] Password reset code for %s: %s', email, code)
            return jsonify({
                'status': 'success',
                'message': 'Development mode: use the verification code shown below.',
                'demo_code': code,
                'delivery': 'development'
            })
        RESET_CODES.pop(email, None)
        return jsonify({
            'status': 'error',
            'message': 'Password reset email is not configured. Configure MAIL_USERNAME and MAIL_PASSWORD in .env, or enable DEV_SHOW_OTP=True for local testing.'
        }), 503

    try:
        msg = Message('NFH-HOA | Password Reset Verification Code', recipients=[email])
        msg.body = (f"Your NFH-HOA password reset code is: {code}\n\n"
                    f"This code expires in {OTP_TTL_SECONDS // 60} minutes.\n"
                    "Do not share this code with anyone.\n"
                    "If you did not request a password reset, please disregard this email.")
        msg.html = render_template(
            'emails/verification.html', code=code, title='Password Reset Verification',
            description='Enter the verification code below to reset your password.',
            expiry_minutes=OTP_TTL_SECONDS // 60,
            security_message='If you did not request a password reset, please disregard this email.')
        mail.send(msg)
        return jsonify({'status': 'success', 'message': generic_message, 'delivery': 'email'})
    except Exception as e:
        app.logger.warning('Password reset email failed for %s: %s', email, e)
        RESET_CODES.pop(email, None)
        return jsonify({'status': 'error', 'message': 'Email delivery failed. Check the SMTP settings in .env and try again.'}), 503


@app.route('/api/forgot-password/verify-code', methods=['POST'])
def forgot_verify_code():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    code = (data.get('code') or '').strip()
    if not email or not re.match(r'^\d{6}$', code):
        return jsonify({'status': 'error', 'message': 'Enter the 6-digit verification code.'}), 400

    ok, message = _verify_one_time_code(RESET_CODES, email, code, mark_verified=True)
    if not ok:
        return jsonify({'status': 'error', 'message': message}), 400

    reset_token = _issue_password_reset_token(email)
    if not reset_token:
        return jsonify({'status': 'error', 'message': 'The verification session expired. Request a new code.'}), 400

    return jsonify({
        'status': 'success',
        'message': 'Email verified. You can now create a new password.',
        'reset_token': reset_token
    })


@app.route('/api/forgot-password/reset', methods=['POST'])
def forgot_reset_password():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    reset_token = (data.get('reset_token') or '').strip()
    new_password = data.get('new_password', '')
    confirm_password = data.get('confirm_password', '')

    if not email or not reset_token:
        return jsonify({'status': 'error', 'message': 'Verify the reset code before creating a new password.'}), 400
    if len(new_password) < 8:
        return jsonify({'status': 'error', 'message': 'New password must be at least 8 characters.'}), 400
    if confirm_password and new_password != confirm_password:
        return jsonify({'status': 'error', 'message': 'New password and confirmation do not match.'}), 400
    if not _password_reset_token_valid(email, reset_token):
        return jsonify({'status': 'error', 'message': 'Password-reset verification is invalid or expired. Request a new code.'}), 400

    pwd_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET password_hash=%s WHERE LOWER(email)=LOWER(%s)", (pwd_hash, email))
            if cursor.rowcount != 1:
                conn.close()
                RESET_CODES.pop(email, None)
                return jsonify({'status': 'error', 'message': 'Unable to reset this account.'}), 400
        conn.close()
        RESET_CODES.pop(email, None)
        return jsonify({'status': 'success', 'message': 'Password reset successful. You can now sign in with your new password.'})
    except Exception:
        app.logger.exception('Password reset database error')
        return jsonify({'status': 'error', 'message': 'Unable to reset the password right now.'}), 500


# ===========================================================================
# APPROVAL EMAIL

# ===========================================================================
# APPROVAL EMAIL
# ===========================================================================
def send_approval_email(req_id, req_type, user_id, executive_name=None, executive_role=None):
    """Notify the request owner after a committed Executive approval using the actual next workflow stage."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT email, CONCAT(first_name,' ',last_name) AS name FROM users WHERE id=%s", (user_id,))
            u = cursor.fetchone()
            cursor.execute("SELECT status,payment_status,fee FROM requests WHERE id=%s", (req_id,))
            req = cursor.fetchone()
        conn.close()
        if not u or not req:
            app.logger.warning('[EMAIL FAILURE] Approval %s: homeowner/request record not found', req_id)
            return {'created': False, 'email_sent': False, 'reason': 'Homeowner or request not found.'}

        subject = f"NFH-HOA | Document Request Approved — {req_id}"
        actor = executive_name or 'Authorized Executive'
        position = executive_role or 'Executive'
        status = req.get('status') or 'Approved'
        if status == 'Ready for Payment & Release':
            next_step = ("The request is approved and prepared for face-to-face payment and release. "
                         "Please visit the Treasurer; payment and physical document release may be completed in the same visit.")
        elif status == 'Paid - Awaiting Release':
            next_step = "Your payment has been recorded. The document is still awaiting physical release confirmation."
        elif status == 'Awaiting Payment Verification':
            next_step = ("This is a legacy payment stage. Please coordinate with the Treasurer so it can be processed under the current face-to-face payment and release workflow.")
        elif status == 'Ready for Release':
            next_step = "The request is approved and cleared. It is now ready for release/issuance by the authorized HOA officer."
        elif status == 'Awaiting Dues Clearance':
            next_step = "The request is approved but cannot proceed until outstanding monthly dues are cleared with the Treasurer."
        else:
            next_step = "Open the NFH-HOA Homeowner Portal to view the current request stage and any required next action."
        body = (
            f"Dear {u['name']},\n\n"
            f"Your {req_type} request ({req_id}) has been approved.\n\n"
            f"Request ID: {req_id}\nRequest Type: {req_type}\nCurrent Status: {status}\n\n"
            f"Approved by: {actor}\nPosition: {position}\n\n{next_step}\n\n"
            "Thank you,\nNorth Fairway Homes Homeowners' Association"
        )
        return send_alert_and_email(user_id, subject, body, related_type='request', related_id=req_id,
                                    dedupe_key=f'approval-{req_id}', important=True)
    except Exception as e:
        app.logger.warning('[EMAIL FAILURE] Approval email helper for %s: %s: %s', req_id, type(e).__name__, e)
        return {'created': False, 'email_sent': False, 'reason': 'Notification delivery failed.'}



# ===========================================================================
# PDF GENERATION (individual requests + admin reports)
# ===========================================================================
def _pdf_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='NFHTitle', fontSize=13, leading=16, alignment=TA_CENTER, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='NFHSub', fontSize=8.5, leading=11, alignment=TA_CENTER, textColor=colors.HexColor('#444444')))
    styles.add(ParagraphStyle(name='NFHHeading', fontSize=11, leading=14, fontName='Helvetica-Bold',
                              textColor=colors.HexColor('#1B4332'), spaceBefore=10, spaceAfter=4))
    styles.add(ParagraphStyle(name='NFHBody', fontSize=9.5, leading=13))
    styles.add(ParagraphStyle(name='NFHRight', fontSize=8.5, leading=11, alignment=TA_RIGHT))
    return styles


def _pdf_letterhead(elements, styles, doc_title):
    elements.append(Paragraph(HOA_NAME, styles['NFHTitle']))
    elements.append(Paragraph(HOA_ADDRESS, styles['NFHSub']))
    elements.append(Paragraph(HOA_REG, styles['NFHSub']))
    elements.append(Spacer(1, 8))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#1B4332')))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(doc_title, styles['NFHHeading']))


def _kv_table(pairs, col_widths=(1.8 * inch, 4.4 * inch)):
    rows = [[Paragraph(f"<b>{k}</b>", getSampleStyleSheet()['Normal']), Paragraph(str(v), getSampleStyleSheet()['Normal'])]
            for k, v in pairs]
    t = Table(rows, colWidths=list(col_widths))
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor('#DDDDDD')),
    ]))
    return t


def _response_pdf(buffer, filename):
    """Return PDFs as normal downloads, or inline when the UI asks for an in-system preview."""
    buffer.seek(0)
    preview_mode = str(request.args.get('preview', '')).strip().lower() in {'1', 'true', 'yes', 'inline'}
    response = send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=not preview_mode,
        download_name=filename,
        max_age=0,
    )
    if preview_mode:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
    return response


REQUEST_TYPE_FIELD_LABELS = {
    'fullName': 'Full Name', 'blockNum': 'Block Number', 'lotNum': 'Lot Number',
    'materialsList': 'List of Materials',
    'verifiedOwner': 'Verified Owner', 'issuanceDate': 'Date of Issuance Request',
    'requestDate': 'Date', 'applicationDate': 'Application Date',
    'moveInDate': 'Move-in Date', 'moveOutDate': 'Move-out Date',
    'applicantName': "Applicant's Name", 'blockLot': 'Block and Lot',
    'phoneNum': 'Cellphone No.', 'emailAddr': 'Email Address',
}


def generate_request_pdf(req):
    """Builds a PDF document tailored to the request's type."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            leftMargin=0.7 * inch, rightMargin=0.7 * inch)
    styles = _pdf_styles()
    elements = []

    req_type = req['request_type']
    _pdf_letterhead(elements, styles, f"{req_type} — Request Form")

    try:
        details = json.loads(req.get('details') or '{}')
    except Exception:
        details = {}

    elements.append(_kv_table([
        ('Request ID', req['id']),
        ('Homeowner', req['homeowner']),
        ('Category', req.get('category') or 'Document Request'),
        ('Date Submitted', format_pdf_datetime(req.get('date_submitted'))),
        ('Status', req['status']),
        ('Payment Status', req['payment_status']),
        ('Fee', f"₱{float(req['fee']):.2f}"),
        *([('Sticker Valid From', str(req.get('sticker_valid_from') or '—')), ('Sticker Valid Until', str(req.get('sticker_valid_until') or '—'))]
          if req_type == 'Vehicle Sticker Application' and (req.get('sticker_valid_from') or req.get('sticker_valid_until')) else []),
    ]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph('Request Details', styles['NFHHeading']))

    if req_type == 'Vehicle Sticker Application' and 'vehicles' in details:
        top_pairs = [(REQUEST_TYPE_FIELD_LABELS.get(k, k), v) for k, v in details.items() if k != 'vehicles']
        if top_pairs:
            elements.append(_kv_table(top_pairs))
            elements.append(Spacer(1, 8))
        veh_rows = [['#', 'Type', 'Plate No.', 'Model / Year', 'Color']]
        for i, v in enumerate(details.get('vehicles', []), start=1):
            veh_rows.append([str(i), v.get('type', ''), v.get('plate', ''), v.get('model', ''), v.get('color', '')])
        vt = Table(veh_rows, colWidths=[0.3 * inch, 1.2 * inch, 1.4 * inch, 1.7 * inch, 1.4 * inch])
        vt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E2EBE2')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#CCCCCC')),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ]))
        elements.append(vt)
    elif details:
        pairs = [(REQUEST_TYPE_FIELD_LABELS.get(k, k.replace('_', ' ').title()), v)
                 for k, v in details.items() if k not in ('oathAgreed',)]
        elements.append(_kv_table(pairs))
    else:
        elements.append(Paragraph('No additional details recorded.', styles['NFHBody']))

    if req.get('remarks'):
        elements.append(Spacer(1, 10))
        elements.append(Paragraph('Officer Remarks', styles['NFHHeading']))
        elements.append(Paragraph(req['remarks'], styles['NFHBody']))

    elements.append(Spacer(1, 24))
    elements.append(Paragraph(f"Generated on {now_str()} — For official HOA processing use only.", styles['NFHSub']))

    doc.build(elements)
    safe_id = re.sub(r'[^A-Za-z0-9_\-]', '_', req['id'])
    return buffer, f"NFH_{safe_id}.pdf"



def _safe_details(raw):
    try:
        return json.loads(raw or '{}') if not isinstance(raw, dict) else raw
    except Exception:
        return {}


def _pdf_logo(width=0.78*inch):
    logo_path=os.path.join(app.static_folder,'logo.png')
    if os.path.exists(logo_path):
        return Image(logo_path,width=width,height=width)
    return Spacer(1,width)


def _official_header(elements, styles):
    name=Paragraph('<b>NORTH FAIRWAY HOMES HOMEOWNERS ASSOCIATION INC.</b>', styles['NFHTitle'])
    addr=Paragraph('Sitio Pastol, Brgy. Muzon West, City of San Jose del Monte, Bulacan 3023', styles['NFHSub'])
    reg=Paragraph('HLURB Registration Number: NTR-20986-R', styles['NFHSub'])
    tin=Paragraph('TIN NO: 486-778-923-000', styles['NFHSub'])
    head=Table([[_pdf_logo(), [name,addr,reg,tin]]], colWidths=[0.95*inch,5.75*inch])
    head.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    elements.append(head)
    elements.append(Spacer(1,12))


def _officer_display_names(cursor):
    result={'Secretary':'NFH-HOA Secretary','President':'NFH-HOA President','Treasurer':'HOA Treasurer'}
    cursor.execute("""SELECT role, CONCAT(first_name,' ',last_name) AS full_name
                      FROM users WHERE role IN ('Secretary','President','Treasurer') AND status='Active'
                      ORDER BY id ASC""")
    for row in cursor.fetchall():
        if row['role'] not in result or result[row['role']].startswith('NFH') or result[row['role']].startswith('HOA'):
            result[row['role']]=row['full_name']
    return result


def _official_doc_context(req):
    details=_safe_details(req.get('details'))
    # The official issuance date belongs to the released document. Before actual
    # issuance, previews intentionally leave the issuance date blank instead of
    # pretending that the preview date is the legal/official issue date.
    issue_dt=req.get('issued_at')
    if isinstance(issue_dt,str):
        issue_text=issue_dt
    else:
        issue_text=issue_dt.strftime('%B %d, %Y') if issue_dt else ''
    vehicles=details.get('vehicles') or []
    first_vehicle=vehicles[0] if vehicles else {}
    vehicle_summary='; '.join(f"{v.get('type','')} — {v.get('plate','')} — {v.get('model','')} — {v.get('color','')}" for v in vehicles) or '—'
    submitted=req.get('date_submitted')
    if isinstance(submitted,str): request_date=submitted
    else: request_date=submitted.strftime('%B %d, %Y') if submitted else ''
    return {
        'homeowner': req.get('homeowner') or '', 'block': req.get('block') or details.get('blockNum') or '',
        'lot': req.get('lot') or details.get('lotNum') or '', 'address': req.get('address_line') or details.get('addressLine') or '',
        'issue_date': issue_text, 'request_date': request_date,
        'permit_no': details.get('permitNo') or details.get('constructionPermit') or '—',
        'materials': details.get('materialsList') or '—', 'mobile': req.get('mobile') or details.get('phoneNum') or '',
        'email': req.get('email') or details.get('emailAddr') or '', 'vehicle_summary': vehicle_summary,
        'vehicle_plate': first_vehicle.get('plate') or '', 'vehicle_brand': first_vehicle.get('brand') or '',
        'vehicle_model': first_vehicle.get('model') or '', 'vehicle_color': first_vehicle.get('color') or '',
        'vehicle_type': first_vehicle.get('type') or '',
        'tenant_name': details.get('fullName') or req.get('homeowner') or '',
        'previous_address': details.get('previousAddress') or '—', 'rented_address': details.get('rentedAddress') or '—',
        'owner_name': details.get('ownerName') or '—',
        'emergency_contact': f"{details.get('emergencyName') or '—'} / {details.get('emergencyPhone') or '—'}",
        'request_id': req.get('id') or '', 'request_type': req.get('request_type') or '', 'purpose': req.get('purpose') or '',
    }


def _fill_template_text(text, context):
    out=str(text or '')
    for k,v in context.items():
        out=out.replace('{'+k+'}', str(v if v is not None else ''))
    return out


def generate_official_document_pdf(req, template, officer_names=None):
    """Generate the actual NFH-HOA document requested by the homeowner.

    This is intentionally different from generate_request_pdf(), which is only an
    internal request record. The official document preview must look like the HOA
    document that will be printed/released and must not expose request-report
    metadata such as status, payment state, Request ID, or template version.
    """
    buffer = BytesIO()
    styles = _pdf_styles()
    elements = []
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        topMargin=0.40 * inch, bottomMargin=0.48 * inch,
        leftMargin=0.62 * inch, rightMargin=0.62 * inch,
    )
    _official_header(elements, styles)

    ctx = _official_doc_context(req)
    details = _safe_details(req.get('details'))
    key = (template or {}).get('template_key') or 'generic'
    names = officer_names or {
        'Secretary': 'NFH-HOA Secretary',
        'President': 'NFH-HOA President',
        'Treasurer': 'HOA Treasurer',
    }
    ctx.update({
        'secretary_name': names.get('Secretary', 'NFH-HOA Secretary'),
        'treasurer_name': names.get('Treasurer', 'HOA Treasurer'),
        'president_name': names.get('President', 'NFH-HOA President'),
    })
    body = _fill_template_text((template or {}).get('body_text') or '', ctx)
    footer = _fill_template_text((template or {}).get('footer_text') or '', ctx)
    title = ((template or {}).get('title') or req.get('request_type') or 'NFH-HOA DOCUMENT').strip()

    title_style = ParagraphStyle(
        'OfficialDocTitle', parent=styles['NFHTitle'], fontSize=17, leading=21,
        alignment=TA_CENTER, fontName='Helvetica-Bold', spaceAfter=20,
        textColor=colors.black,
    )
    body_style = ParagraphStyle(
        'OfficialDocBody', parent=styles['NFHBody'], fontSize=10.5, leading=16,
        textColor=colors.black, spaceAfter=10,
    )
    body_center = ParagraphStyle(
        'OfficialDocBodyCenter', parent=body_style, alignment=TA_CENTER,
    )
    small_style = ParagraphStyle(
        'OfficialSmall', parent=styles['NFHBody'], fontSize=9, leading=12,
        textColor=colors.black,
    )

    def official_title(text=None):
        elements.append(Paragraph(html.escape(text or title), title_style))

    def line_value(value, width=2.0*inch):
        text = html.escape(str(value or ''))
        return Paragraph(f'<u>{text if text else "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"}</u>', body_style)

    def role_signature_flow(role, caption=None):
        asset = ((req or {}).get('_signature_assets') or {}).get(role) or {}
        officer_name = asset.get('name') or names.get(role) or f'NFH-HOA {role}'
        flows = []
        if caption:
            flows.append(Paragraph(f'<b>{html.escape(caption)}</b>', body_center))
            flows.append(Spacer(1, 7))
        if asset.get('path'):
            try:
                im = Image(asset['path'], width=1.35*inch, height=0.52*inch)
                im.hAlign = 'CENTER'
                flows.append(im)
            except Exception:
                flows.append(Spacer(1, 0.52*inch))
        else:
            flows.append(Spacer(1, 0.52*inch))
        flows.append(Paragraph('____________________________', styles['NFHSub']))
        flows.append(Paragraph(
            f'<b>{html.escape(officer_name)}</b><br/>NFH-HOA {html.escape(role)}',
            styles['NFHSub'],
        ))
        return flows

    def add_signature_row(role_specs):
        # role_specs: [(role, caption), ...]
        cells = [role_signature_flow(role, caption) for role, caption in role_specs]
        if not cells:
            return
        table = Table([cells], colWidths=[6.25*inch/len(cells)]*len(cells))
        table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ]))
        elements.append(table)

    # ------------------------------------------------------------------
    # Official NFH-HOA forms based on the supplied physical documents.
    # ------------------------------------------------------------------
    if key == 'cert-improvement':
        official_title('CERTIFICATE OF IMPROVEMENT')
        elements.append(Spacer(1, 18))
        elements.append(Paragraph(
            f'This is to certify that <b>{html.escape(ctx["homeowner"])}</b>, the owner of the unit in '
            f'Blk <b>{html.escape(str(ctx["block"]))}</b> Lot <b>{html.escape(str(ctx["lot"]))}</b> of North '
            f'Fairway Homes, Brgy. Muzon West, City of San Jose del Monte, Bulacan, is going to '
            f'<b>IMPROVE</b> their unit.', body_style))
        elements.append(Spacer(1, 24))
        elements.append(Paragraph(
            f'<b>ISSUED</b> this {html.escape(ctx["issue_date"] or "____________")} at North Fairway Homes, '
            'Brgy. Muzon West, City of San Jose del Monte, Bulacan.', body_style))
        elements.append(Spacer(1, 38))
        add_signature_row([('Secretary', None), ('President', None)])

    elif key == 'proof-residency':
        official_title('Proof of Residency')
        elements.append(Spacer(1, 20))
        elements.append(Paragraph(
            f'This is to certify that <b>{html.escape(ctx["homeowner"])}</b> of Block '
            f'<b>{html.escape(str(ctx["block"]))}</b> Lot <b>{html.escape(str(ctx["lot"]))}</b> of North '
            'Fairway Homes, Brgy. Muzon West, City of San Jose del Monte, Bulacan is a bona fide resident '
            'of North Fairway Homes Homeowners Association Inc.', body_style))
        elements.append(Spacer(1, 15))
        elements.append(Paragraph(f'<b>Owner/Member:</b> {html.escape(ctx["homeowner"])}', body_style))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(
            f'Issued this {html.escape(ctx["issue_date"] or "____________")} at North Fairway Homes, '
            'Brgy. Muzon West, City of San Jose del Monte, Bulacan.', body_style))
        elements.append(Spacer(1, 36))
        add_signature_row([('Secretary', None), ('President', None)])

    elif key in {'move-in', 'move-out'}:
        official_title('NFH/HOA GATE PASS FOR MOVE-IN' if key == 'move-in' else 'NFH/HOA GATE PASS FOR MOVE-OUT')
        elements.append(Paragraph('<b>TO WHOM IT MAY CONCERN:</b>', body_style))
        elements.append(Spacer(1, 12))
        if key == 'move-in':
            sentence = (
                f'This is to certify that <b>{html.escape(ctx["homeowner"])}</b>, the owner of the unit in '
                f'Blk <b>{html.escape(str(ctx["block"]))}</b> Lot <b>{html.escape(str(ctx["lot"]))}</b>, is going '
                'to move in to their unit. They are allowed to bring the needed things inside the subdivision '
                'for their transfer to North Fairway Homes.'
            )
        else:
            sentence = (
                f'This is to certify that <b>{html.escape(ctx["homeowner"])}</b>, the owner of the unit in '
                f'Blk <b>{html.escape(str(ctx["block"]))}</b> Lot <b>{html.escape(str(ctx["lot"]))}</b>, is going '
                'to move out to another place. They are allowed to bring the needed things outside the '
                'subdivision for their transfer.'
            )
        elements.append(Paragraph(sentence, body_style))
        elements.append(Spacer(1, 15))
        elements.append(Paragraph(
            f'<b>ISSUED</b> this {html.escape(ctx["issue_date"] or "____________")} at North Fairway Homes, '
            'Brgy. Muzon West, City of San Jose del Monte, Bulacan. This is upon the request of the interested '
            'party for whatever legal purpose it may serve.', body_style))
        elements.append(Spacer(1, 34))
        add_signature_row([('Secretary', None), ('President', None)])

    elif key == 'cert-membership':
        official_title('Certificate of Membership')
        elements.append(Spacer(1, 20))
        elements.append(Paragraph(
            f'This is to certify that <b>{html.escape(ctx["homeowner"])}</b> of Block '
            f'<b>{html.escape(str(ctx["block"]))}</b> Lot <b>{html.escape(str(ctx["lot"]))}</b> of North '
            'Fairway Homes Subdivision, Brgy. Muzon West, City of San Jose del Monte, Bulacan is now a bona fide '
            'member of the North Fairway Homes Homeowners Association Inc.', body_style))
        elements.append(Spacer(1, 18))
        elements.append(Paragraph(
            f'Issued this {html.escape(ctx["issue_date"] or "____________")} at North Fairway Homes, '
            'Brgy. Muzon West, City of San Jose del Monte, Bulacan.', body_style))
        elements.append(Spacer(1, 36))
        add_signature_row([('Secretary', None), ('President', None)])

    elif key == 'gate-pass':
        official_title('GATE PASS')
        # The supplied NFH-HOA Gate Pass is a printable permit, not a request report.
        top = Table([
            [Paragraph('<b>NAME:</b>', body_style), Paragraph(html.escape(ctx['homeowner']), body_style)],
            [Paragraph('<b>ADDRESS:</b>', body_style), Paragraph(
                f'BLK {html.escape(str(ctx["block"]))} &nbsp;&nbsp;&nbsp; LOT {html.escape(str(ctx["lot"]))}', body_style)],
        ], colWidths=[1.05*inch, 5.05*inch])
        top.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('LINEBELOW',(1,0),(1,-1),0.65,colors.black),
            ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),4),
            ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ]))
        elements.append(top)
        elements.append(Spacer(1, 22))
        permit = html.escape(str(ctx['permit_no'] or ''))
        materials = [x.strip() for x in str(ctx['materials'] or '').split('\n') if x.strip()]
        left_lines = [Paragraph('<b>List of Materials</b>', body_style)]
        for i in range(6):
            value = materials[i] if i < len(materials) else ''
            left_lines.append(Paragraph(html.escape(value) + ('_'*1 if value else '&nbsp;'), small_style))
            left_lines.append(HRFlowable(width='100%', thickness=0.55, color=colors.black, spaceBefore=1, spaceAfter=3))
        right_lines = [Paragraph('<b>Major/Minor Construction Permit number:</b>', body_style),
                       Paragraph(permit or '&nbsp;', small_style),
                       HRFlowable(width='100%', thickness=0.55, color=colors.black, spaceBefore=1, spaceAfter=3)]
        for _ in range(5):
            right_lines.extend([Paragraph('&nbsp;', small_style), HRFlowable(width='100%', thickness=0.55, color=colors.black, spaceBefore=1, spaceAfter=3)])
        grid = Table([[left_lines, right_lines]], colWidths=[3.0*inch, 3.0*inch], hAlign='CENTER')
        grid.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8)]))
        elements.append(grid)
        elements.append(Spacer(1, 15))
        elements.append(Paragraph('<b>Remarks:</b> _________________________________________________', body_style))
        elements.append(Spacer(1, 26))
        add_signature_row([('Treasurer', 'Checked By:'), ('President', 'Approved By:')])

    elif key == 'vehicle-sticker':
        official_title('VEHICLE STICKER APPLICATION FORM')
        if body.strip():
            elements.append(Paragraph(html.escape(body.strip()), ParagraphStyle(
                'VehicleIntroOfficial', parent=small_style, fontSize=8.9, leading=13, spaceAfter=14)))
        app_type = details.get('applicationType') or 'New'
        resident_type = details.get('residentType') or 'HOA Member'
        app_info = Table([
            [Paragraph(f'☐ New &nbsp;&nbsp; ☐ Renewal &nbsp;&nbsp; <b>Selected:</b> {html.escape(str(app_type))}', small_style),
             Paragraph(f'<b>Date:</b> {html.escape(str(details.get("applicationDate") or ctx["request_date"] or ""))}', small_style)],
            [Paragraph(f'☐ HOA MEMBER &nbsp;&nbsp; ☐ Renter &nbsp;&nbsp; <b>Selected:</b> {html.escape(str(resident_type))}', small_style),
             Paragraph(f'<b>Term of Lease:</b> {html.escape(str(details.get("termOfLease") or "—"))}', small_style)],
        ], colWidths=[3.7*inch,2.35*inch])
        app_info.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        elements.append(app_info)
        elements.append(Spacer(1,10))
        elements.append(_kv_table([
            ("Applicant's Name", ctx['homeowner']), ('Cellphone No.', ctx['mobile']),
            ('Block and Lot', f"{ctx['block']} / {ctx['lot']}"), ('Email Address', ctx['email']),
        ], col_widths=(1.45*inch,4.65*inch)))
        elements.append(Spacer(1,12))
        elements.append(Paragraph('<b>VEHICLE INFORMATION</b>', body_center))
        rows=[['PLATE NO.','BRAND','YEAR / MODEL','BODY COLOR','VEHICLE TYPE','STICKER NO.']]
        for v in details.get('vehicles',[]):
            rows.append([v.get('plate',''),v.get('brand',''),v.get('model',''),v.get('color',''),v.get('type',''),''])
        while len(rows)<5: rows.append(['','','','','',''])
        t=Table(rows,colWidths=[1.0*inch,0.9*inch,1.2*inch,0.95*inch,1.05*inch,0.95*inch])
        t.setStyle(TableStyle([
            ('GRID',(0,0),(-1,-1),0.55,colors.black),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
            ('FONTSIZE',(0,0),(-1,-1),7.7),('ALIGN',(0,0),(-1,0),'CENTER'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ]))
        elements.append(t)
        elements.append(Spacer(1,12))
        elements.append(Paragraph('I hereby certify that all information provided herein is true and correct.', small_style))
        if req.get('sticker_valid_from') or req.get('sticker_valid_until'):
            elements.append(Spacer(1,8))
            elements.append(Paragraph(
                f'<b>Sticker Validity:</b> {html.escape(str(req.get("sticker_valid_from") or "—"))} to '
                f'{html.escape(str(req.get("sticker_valid_until") or "—"))}', small_style))
        elements.append(Spacer(1,30))
        elements.append(Paragraph('Applicant Signature over Printed Name: _______________________________', body_center))
        elements.append(Spacer(1,22))
        required = _signature_roles(template)
        if required:
            add_signature_row([(r, 'Verified/Issued by:' if i == 0 else None) for i, r in enumerate(required)])
        else:
            elements.append(Paragraph('Verified/Issued by: _______________________________<br/>HOA Representative', body_center))

    elif key == 'tenant-form':
        official_title('RENTER’S / TENANT’S INFORMATION FORM')
        pairs = [
            ('Full Name Head of Renter / Tenant', details.get('fullName') or ctx['homeowner']),
            ('Gender', details.get('gender') or '—'), ('Age', details.get('age') or '—'),
            ('Cellphone Number / Tel. #', details.get('phoneNum') or '—'),
            ('Occupation', details.get('occupation') or '—'), ('Birthdate', details.get('dob') or '—'),
            ('Civil Status', details.get('civilStatus') or '—'), ('Spouse Name', details.get('spouseName') or '—'),
            ('Spouse Age', details.get('spouseAge') or '—'), ('Spouse Contact', details.get('spousePhone') or '—'),
            ('Children / House Companions', details.get('houseCompanions') or '—'),
            ('Previous Address', details.get('previousAddress') or '—'),
            ('Address of Unit to be Rented', details.get('rentedAddress') or '—'),
            ('Name of Unit Owner', details.get('ownerName') or '—'),
            ('Cellphone / Tel. # of Unit Owner', details.get('ownerPhone') or '—'),
            ('Emergency Contact', ctx['emergency_contact']),
        ]
        elements.append(_kv_table(pairs, col_widths=(2.15*inch,3.95*inch)))
        elements.extend([
            Spacer(1,10), Paragraph('<b>Requirements to be submitted to HOA:</b>', body_style),
            Paragraph('• Barangay Clearance from Previous Address<br/>• Authorization Letter to Occupy from the Owner of the Unit<br/>• Move-in Permit from NFH-HOA<br/>• Xerox Copy of Valid ID of Renter and companion(s)', small_style),
            Spacer(1,12), Paragraph('<b>OATH OF RENTER / TENANT</b>', body_center),
        ])
        oath = _fill_template_text((template or {}).get('body_text') or '', ctx)
        elements.append(Paragraph(html.escape(oath).replace('\n','<br/>'), small_style))
        elements.append(Spacer(1,20))
        elements.append(Paragraph('Signature of Renter: _______________________________', small_style))
        elements.append(Spacer(1,20))
        elements.append(Paragraph('Witnessed by: _______________________________', small_style))

    else:
        # Generic administrator-created service: still render as an official HOA
        # document, not as a request-status report.
        official_title(title)
        for para in body.split('\n'):
            if para.strip():
                elements.append(Paragraph(html.escape(para.strip()), body_style))
        if footer.strip():
            elements.extend([Spacer(1,14), Paragraph(html.escape(footer).replace('\n','<br/>'), body_style)])
        required = _signature_roles(template)
        if required:
            elements.append(Spacer(1,28))
            add_signature_row([(role, None) for role in required])

    # NOTE: Deliberately no Request ID, workflow status, payment status, template
    # version, audit metadata, or "generated on" footer here. Those belong to the
    # internal request record, not to the official HOA document being previewed.
    doc.build(elements)
    return buffer, f"NFH_{re.sub(r'[^A-Za-z0-9_-]','_', req.get('id') or 'document')}_{key}.pdf"



def generate_verified_soa_pdf(req, dues_rows, adjustments):
    """Render recorded assessments, settlement states and applied adjustments."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, topMargin=.6*inch, bottomMargin=.6*inch)
    styles = _pdf_styles()
    elements = []
    _pdf_letterhead(elements, styles, 'Statement of Account')
    details = json.loads(req.get('details') or '{}')
    elements.append(_kv_table([
        ('Homeowner', req.get('homeowner') or ''),
        ('Property', f"Block {req.get('block') or '—'}, Lot {req.get('lot') or '—'}"),
        ('Statement Date', datetime.now().strftime('%Y-%m-%d')),
        ('Coverage Start', details.get('coverageStart') or details.get('periodStart') or details.get('startDate') or 'All recorded months'),
        ('Coverage End', details.get('coverageEnd') or details.get('periodEnd') or details.get('endDate') or 'All recorded months'),
    ]))
    rows = [['Month', 'Assessment', 'Status', 'Verified settlement']]
    assessed = paid = outstanding = 0.0
    for d in dues_rows:
        amount = float(d['amount'] or 0)
        assessed += amount
        if d['status'] == 'Paid': paid += amount
        if d['status'] == 'Unpaid': outstanding += amount
        rows.append([str(d['due_month']), f"PHP {amount:.2f}", d['status'], str(d.get('settled_at') or '—')])
    t = Table(rows, repeatRows=1, colWidths=[1.25*inch,1.25*inch,1.0*inch,2.35*inch])
    t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.3,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('VALIGN',(0,0),(-1,-1),'TOP')]))
    elements.extend([Spacer(1,12), t, Spacer(1,12)])
    elements.append(_kv_table([('Total recorded assessments', f'PHP {assessed:.2f}'),('Verified paid assessments',f'PHP {paid:.2f}'),('Outstanding monthly dues',f'PHP {outstanding:.2f}')]))
    if adjustments:
        elements.append(Spacer(1,12))
        elements.append(Paragraph('Recorded financial adjustments', styles['NFHHeading']))
        for a in adjustments:
            elements.append(Paragraph(html.escape(f"{a['created_at']}: {a['status']} — {a.get('reason') or 'No reason recorded'}; amount PHP {float(a.get('proposed_adjustment') or 0):.2f}"), styles['Normal']))
    elements.append(Spacer(1,12))
    elements.append(Paragraph('Verified from the NFH-HOA financial ledger. Processing fee is recorded separately from monthly dues.', styles['Normal']))
    doc.build(elements)
    return buffer, f"NFH_SOA_{req['id']}.pdf"


@app.route('/requests/<req_id>/document.pdf')
def request_document_pdf(req_id):
    if 'user_id' not in session: return redirect(url_for('index'))
    conn=get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""SELECT r.*, CONCAT(u.first_name,' ',u.last_name) AS homeowner,u.block,u.lot,u.address_line,u.email,u.mobile
                              FROM requests r JOIN users u ON u.id=r.user_id WHERE r.id=%s""",(req_id,)); req=cursor.fetchone()
            if not req: flash('Request not found.','error'); return redirect(url_for('index'))
            if req['request_type'] == 'Statement of Account' and session.get('role') not in ('Treasurer','Homeowner'):
                return redirect(url_for('officer'))
            if session.get('role')=='Homeowner' and req['user_id']!=session.get('user_id'): return redirect(url_for('homeowner'))
            if session.get('role')=='Homeowner' and req['status'] != 'Issued / Completed':
                flash('The official document becomes available in your portal after it has been physically released to you.','warning'); return redirect(url_for('homeowner'))
            template=None
            if req.get('document_template_id'):
                cursor.execute("SELECT * FROM document_templates WHERE id=%s",(req['document_template_id'],)); template=cursor.fetchone()
            if not template: template=get_active_document_template(cursor,request_type=req['request_type'])
            names=_officer_display_names(cursor)
            req['_signature_assets']=request_signature_assets(cursor, req_id, template) if template else {}

            # Treasurer/Admin may prepare the official print copy during the
            # face-to-face payment/release transaction. The selected transaction
            # date is used only for this generated PDF; the database is not marked
            # Issued until release is actually confirmed.
            requested_issue_date=(request.args.get('issue_date') or '').strip()
            if requested_issue_date and session.get('role') in ['Treasurer','Admin'] and req.get('status') in ('Ready for Payment & Release','Paid - Awaiting Release','Awaiting Payment Verification','Approved'):
                try:
                    req['issued_at']=datetime.strptime(requested_issue_date,'%Y-%m-%d')
                except ValueError:
                    pass
        if req['request_type'] == 'Statement of Account':
            with conn.cursor() as cursor:
                cursor.execute("SELECT due_month,amount,status,settled_at FROM monthly_dues WHERE user_id=%s ORDER BY due_month", (req['user_id'],))
                soa_dues = cursor.fetchall()
                cursor.execute("SELECT created_at,status,reason,proposed_adjustment FROM financial_adjustments WHERE user_id=%s ORDER BY created_at", (req['user_id'],))
                soa_adjustments = cursor.fetchall()
            buffer,filename=generate_verified_soa_pdf(req,soa_dues,soa_adjustments)
        elif not template:
            buffer,filename=generate_request_pdf(req)
        else:
            buffer,filename=generate_official_document_pdf(req,template,names)
        if session.get('role') != 'Homeowner':
            audit_action='Download Document for Printing' if str(request.args.get('download','')).lower() in {'1','true','yes'} else 'View Generated Document'
            log_audit_action(session.get('username'),session.get('role'),audit_action,req_id)
        return _response_pdf(buffer,filename)
    finally: conn.close()


@app.route('/document-templates/<template_key>/preview')
def document_template_preview(template_key):
    if 'user_id' not in session or session.get('role') not in OFFICER_ROLES: return redirect(url_for('index'))
    conn=get_db_connection()
    try:
        with conn.cursor() as cursor:
            template=get_active_document_template(cursor,template_key=template_key)
            names=_officer_display_names(cursor)
            sample_signatures={}
            for role in _signature_roles(template):
                officer=_current_role_signature(cursor,role)
                sample_signatures[role]={'name':(officer or {}).get('full_name') or f'NFH-HOA {role}','path':_signature_abs((officer or {}).get('e_signature_path'))}
        if not template: flash('Template not found.','error'); return redirect(url_for('officer'))
        sample={'id':'SAMPLE-PREVIEW','request_type':template.get('service_name') or template.get('title'),'homeowner':'Juan Dela Cruz','block':'1','lot':'12','email':'homeowner@example.com','mobile':'09170000000','details':json.dumps({'materialsList':'Cement\nSand\nSteel Bars','vehicles':[{'type':'4 Wheels','plate':'ABC 1234','brand':'Toyota','model':'Vios 2026','color':'Black'}],'fullName':'Sample Tenant','previousAddress':'Previous Address','rentedAddress':'Block 1 Lot 12','ownerName':'Juan Dela Cruz','emergencyName':'Maria Dela Cruz','emergencyPhone':'09170000000'}),'status':'Preview','payment_status':'Not Required','fee':0,'date_submitted':datetime.now(),'document_prepared_at':datetime.now()}
        sample['_signature_assets']=sample_signatures
        buffer,filename=generate_official_document_pdf(sample,template,names); return _response_pdf(buffer,'PREVIEW_'+filename)
    finally: conn.close()




# ---------------------------------------------------------------------------
# Administrator existing-record import / migration
# ---------------------------------------------------------------------------
IMPORT_DATASETS = {
    'homeowners': {
        'label': 'Homeowners',
        'fields': ['first_name','middle_name','last_name','suffix','email','username','mobile','block','lot','address_line','gender','dob','civil_status','household','temporary_password'],
        'required': {'first_name','last_name','email','username','mobile','block','lot','address_line','temporary_password'},
        'aliases': {
            'first_name': ['first name','firstname','given name'], 'middle_name':['middle name','middlename'],
            'last_name':['last name','lastname','surname'], 'suffix':['suffix'], 'email':['email','email address'],
            'username':['username','user name'], 'mobile':['mobile','phone','phone number','contact number'],
            'block':['block','block number','blk'], 'lot':['lot','lot number'], 'address_line':['address','complete address','address line','street/phase'],
            'gender':['gender','sex'], 'dob':['dob','birth date','date of birth'], 'civil_status':['civil status'],
            'household':['household','household members','number of household members'], 'temporary_password':['temporary password','initial password','password']
        }
    },
    'monthly_dues': {
        'label':'Monthly Dues',
        'fields':['homeowner_identifier','due_month','amount','status'],
        'required':{'homeowner_identifier','due_month','amount'},
        'aliases':{'homeowner_identifier':['homeowner id','homeowner','email','username','homeowner identifier'], 'due_month':['due month','month','period'], 'amount':['amount','monthly due'], 'status':['status','dues status']}
    },
    'fees': {
        'label':'Fees',
        'fields':['item_name','amount','proposed_amount','status'],
        'required':{'item_name','amount'},
        'aliases':{'item_name':['item name','fee item','service','service name'], 'amount':['amount','fee'], 'proposed_amount':['proposed amount'], 'status':['status']}
    },
    'historical_requests': {
        'label':'Historical Requests',
        'fields':['id','homeowner_identifier','request_type','category','assigned_officer','fee','details','remarks','purpose','status','payment_status','date_submitted','last_updated'],
        'required':{'id','homeowner_identifier','request_type','status','date_submitted'},
        'aliases':{'id':['request id','id'], 'homeowner_identifier':['homeowner id','homeowner','email','username','homeowner identifier'], 'request_type':['request type','service','service type'], 'category':['category'], 'assigned_officer':['assigned officer','reviewer'], 'fee':['fee','amount'], 'details':['details'], 'remarks':['remarks'], 'purpose':['purpose'], 'status':['status'], 'payment_status':['payment status'], 'date_submitted':['date submitted','submitted','submission date'], 'last_updated':['last updated','updated']}
    }
}


def _clean_header(value):
    return re.sub(r'\s+', ' ', normalize_search_text(value).replace('_',' ')).strip()


def _auto_mapping(dataset, headers):
    cfg=IMPORT_DATASETS[dataset]
    normalized={_clean_header(h): h for h in headers if h is not None}
    mapping={}
    for field in cfg['fields']:
        candidates=[field.replace('_',' ')] + cfg.get('aliases',{}).get(field,[])
        for candidate in candidates:
            hit=normalized.get(_clean_header(candidate))
            if hit is not None:
                mapping[field]=hit
                break
    return mapping


def _cleanup_import_staging(max_age_seconds=3600):
    """Remove abandoned temporary imports without touching protected e-signatures."""
    now=time.time()
    try:
        for staged in Path(app.config['IMPORT_STAGING_FOLDER']).iterdir():
            if not staged.is_file():
                continue
            try:
                if now-staged.stat().st_mtime > max_age_seconds:
                    staged.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        pass


def _stage_import_file(file_storage, allowed_exts):
    _cleanup_import_staging()
    if not file_storage or not file_storage.filename:
        raise ValueError('Choose a file to import.')
    if request.content_length and request.content_length > MAX_IMPORT_FILE_SIZE:
        raise ValueError('Import file is too large. Maximum size is 10MB.')
    filename=secure_filename(file_storage.filename)
    ext=os.path.splitext(filename)[1].lower()
    if ext not in allowed_exts:
        raise ValueError('Unsupported import file type.')
    token=secrets.token_urlsafe(24)
    path=os.path.join(app.config['IMPORT_STAGING_FOLDER'], f'{token}{ext}')
    file_storage.save(path)
    return token, filename, path


def _import_path(token, ext):
    _cleanup_import_staging()
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,80}', token or ''):
        return None
    path=os.path.join(app.config['IMPORT_STAGING_FOLDER'], f'{token}{ext}')
    return path if os.path.isfile(path) else None


def _excel_rows(path, dataset=None):
    wb=load_workbook(path, read_only=True, data_only=True)
    try:
        ws=wb.active
        if dataset in IMPORT_DATASETS:
            desired=IMPORT_DATASETS[dataset]['label']
            if desired in wb.sheetnames:
                ws=wb[desired]
        values=list(ws.iter_rows(values_only=True))
        if not values:
            return [], []
        header_positions=[]
        seen=set()
        for idx,value in enumerate(values[0]):
            header=normalize_unicode_text(value)
            if not header:
                continue
            folded=normalize_search_text(header)
            if folded in seen:
                raise ValueError(f'Duplicate column header: {header}')
            seen.add(folded)
            header_positions.append((idx,header))
        headers=[header for _,header in header_positions]
        rows=[]
        for row_no, raw in enumerate(values[1:], start=2):
            record={header:(raw[idx] if idx < len(raw) else None) for idx,header in header_positions}
            if any(v not in (None,'') for v in record.values()):
                rows.append((row_no,record))
        return headers, rows
    finally:
        wb.close()


def _serialize_preview_value(value):
    if isinstance(value,(datetime,)):
        return value.isoformat(sep=' ')
    if hasattr(value,'isoformat'):
        try: return value.isoformat()
        except Exception: pass
    return value


def _parse_import_date(value, field_label='date'):
    if value in (None,''): return None
    if isinstance(value, datetime): return value
    if hasattr(value,'year') and hasattr(value,'month') and hasattr(value,'day'):
        return datetime(value.year,value.month,value.day)
    text=normalize_unicode_text(value)
    for fmt in ('%Y-%m-%d','%m/%d/%Y','%d/%m/%Y','%Y-%m-%d %H:%M:%S','%Y-%m-%d %H:%M'):
        try: return datetime.strptime(text,fmt)
        except ValueError: pass
    raise ValueError(f'Invalid {field_label}: {text}')


def _resolve_homeowner(cursor, identifier):
    ident=normalize_unicode_text(identifier)
    if not ident: return None
    cursor.execute("""SELECT id,homeowner_public_id,email,username,block,lot FROM users
                      WHERE role='Homeowner' AND (homeowner_public_id=%s OR LOWER(email)=LOWER(%s) OR LOWER(username)=LOWER(%s)) LIMIT 1""", (ident,ident,ident))
    return cursor.fetchone()


def _import_history(cursor, import_type, filename, dataset, total, success, rejected, duplicates, status, summary=None):
    cursor.execute("""INSERT INTO import_history
        (import_type,source_filename,dataset,total_rows,successful_rows,rejected_rows,duplicate_rows,status,summary_json,imported_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (import_type,filename,dataset,total,success,rejected,duplicates,status,json.dumps(summary or {},ensure_ascii=False),session.get('username','Admin')))


def _mapped_value(row, mapping, field):
    header=mapping.get(field)
    return row.get(header) if header else None


@app.route('/api/admin/import/excel/preview', methods=['POST'])
def admin_import_excel_preview():
    return jsonify({'status':'error','message':'Admin imports are disabled. Use the Treasurer portal.'}),403
    if not _require_admin():
        return jsonify({'status':'error','message':'Administrator access required.'}),403
    dataset=(request.form.get('dataset') or '').strip()
    if dataset not in IMPORT_DATASETS:
        return jsonify({'status':'error','message':'Choose a supported dataset type.'}),400
    try:
        token,filename,path=_stage_import_file(request.files.get('file'), {'.xlsx'})
        headers,rows=_excel_rows(path,dataset)
        if not headers:
            os.remove(path); return jsonify({'status':'error','message':'The workbook has no header row.'}),400
        mapping=_auto_mapping(dataset,headers)
        cfg=IMPORT_DATASETS[dataset]
        preview=[]
        for row_no,row in rows[:10]:
            preview.append({'row':row_no,'values':{h:_serialize_preview_value(row.get(h)) for h in headers}})
        return jsonify({'status':'success','token':token,'filename':filename,'dataset':dataset,
                        'headers':headers,'mapping':mapping,'fields':[{'name':f,'required':f in cfg['required']} for f in cfg['fields']],
                        'row_count':len(rows),'preview':preview})
    except ValueError as exc:
        if 'path' in locals():
            try: os.remove(path)
            except OSError: pass
        return jsonify({'status':'error','message':str(exc)}),400
    except Exception:
        if 'path' in locals():
            try: os.remove(path)
            except OSError: pass
        app.logger.exception('Excel import preview failed')
        return jsonify({'status':'error','message':'Unable to read the Excel file. Confirm that it is a valid .xlsx workbook.'}),400


@app.route('/api/admin/import/excel/commit', methods=['POST'])
def admin_import_excel_commit():
    return jsonify({'status':'error','message':'Admin imports are disabled. Use the Treasurer portal.'}),403
    if not _require_admin():
        return jsonify({'status':'error','message':'Administrator access required.'}),403
    data=request.get_json() or {}
    dataset=(data.get('dataset') or '').strip(); token=(data.get('token') or '').strip()
    mapping=data.get('mapping') or {}; conflict=(data.get('conflict_action') or 'skip').strip()
    filename=secure_filename(data.get('filename') or 'import.xlsx')
    if dataset not in IMPORT_DATASETS or conflict not in {'skip','update'}:
        return jsonify({'status':'error','message':'Invalid import settings.'}),400
    path=_import_path(token,'.xlsx')
    if not path: return jsonify({'status':'error','message':'Import preview expired. Select the file again.'}),400
    cfg=IMPORT_DATASETS[dataset]
    missing=[f for f in cfg['required'] if not mapping.get(f)]
    if missing:
        return jsonify({'status':'error','message':'Map all required fields before importing: '+', '.join(missing)}),400
    total=success=rejected=duplicates=0; errors=[]
    conn=None
    try:
        headers,rows=_excel_rows(path,dataset); total=len(rows)
        valid_headers=set(headers)
        if any(h not in valid_headers for h in mapping.values() if h):
            return jsonify({'status':'error','message':'Column mapping no longer matches this workbook.'}),400
        conn=get_db_connection(autocommit=False)
        with conn.cursor() as cursor:
            for row_no,row in rows:
                try:
                    values={f:_mapped_value(row,mapping,f) for f in cfg['fields']}
                    if dataset=='homeowners':
                        first=normalize_unicode_text(values['first_name']); middle=normalize_unicode_text(values.get('middle_name')); last=normalize_unicode_text(values['last_name'])
                        email=normalize_unicode_text(values['email']).lower(); username=normalize_unicode_text(values['username']); mobile=re.sub(r'\s+','',normalize_unicode_text(values['mobile']))
                        block=normalize_unicode_text(values['block']); lot=normalize_unicode_text(values['lot']); address=normalize_unicode_text(values['address_line']); temp_password=str(values.get('temporary_password') or '')
                        if not all([first,last,email,username,mobile,block,lot,address,temp_password]): raise ValueError('Missing required homeowner field(s).')
                        if not valid_person_name(first) or not valid_person_name(last) or (middle and not valid_person_name(middle,required=False)): raise ValueError('Invalid homeowner name.')
                        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$',email): raise ValueError('Invalid email address.')
                        if not re.match(r'^09\d{9}$',mobile): raise ValueError('Mobile must be 11 digits starting with 09.')
                        if len(temp_password)<8: raise ValueError('Temporary password must be at least 8 characters.')
                        public_id=''  # Existing HOA imports receive a system-generated Homeowner ID
                        cursor.execute("""SELECT * FROM users
                                          WHERE LOWER(username)=LOWER(%s)
                                             OR LOWER(email)=LOWER(%s)
                                             OR (role='Homeowner' AND block=%s AND lot=%s)
                                          LIMIT 1""",(username,email,block,lot))
                        existing=cursor.fetchone()
                        if existing:
                            # Never allow an Excel homeowner import to overwrite an officer/Admin account
                            # merely because a username or email happens to match.
                            if existing.get('role') != 'Homeowner':
                                raise ValueError('This username or email belongs to a non-homeowner account and cannot be replaced by import.')
                            duplicates+=1
                            if conflict=='skip': continue
                            if not existing.get('homeowner_public_id'):
                                public_id=generate_homeowner_public_id(cursor,block,lot)
                            else:
                                public_id=existing.get('homeowner_public_id')
                            cursor.execute("""UPDATE users SET first_name=%s,middle_name=%s,last_name=%s,suffix=%s,email=%s,mobile=%s,block=%s,lot=%s,address_line=%s,
                                gender=%s,dob=%s,civil_status=%s,household=%s,homeowner_public_id=%s,verification_status='Verified',status='Active',verified_by=%s,verified_at=NOW() WHERE id=%s""",
                                (first,middle or None,last,normalize_unicode_text(values.get('suffix')) or None,email,mobile,block,lot,address,
                                 normalize_unicode_text(values.get('gender')) or 'NA',_parse_import_date(values.get('dob'),'date of birth').date() if values.get('dob') else None,
                                 normalize_unicode_text(values.get('civil_status')) or 'Single',max(1,int(values.get('household') or 1)),public_id,session.get('username'),existing['id']))
                        else:
                            if not public_id: public_id=generate_homeowner_public_id(cursor,block,lot)
                            cursor.execute("""INSERT INTO users (first_name,middle_name,last_name,suffix,gender,dob,civil_status,block,lot,address_line,homeowner_public_id,verification_status,verified_by,verified_at,household,email,username,mobile,password_hash,role,status)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Verified',%s,NOW(),%s,%s,%s,%s,%s,'Homeowner','Active')""",
                                (first,middle or None,last,normalize_unicode_text(values.get('suffix')) or None,normalize_unicode_text(values.get('gender')) or 'NA',
                                 _parse_import_date(values.get('dob'),'date of birth').date() if values.get('dob') else None,normalize_unicode_text(values.get('civil_status')) or 'Single',
                                 block,lot,address,public_id,session.get('username'),max(1,int(values.get('household') or 1)),
                                 email,username,mobile,generate_password_hash(temp_password,method='pbkdf2:sha256')))
                        success+=1
                    elif dataset=='monthly_dues':
                        u=_resolve_homeowner(cursor,values['homeowner_identifier'])
                        if not u: raise ValueError('Homeowner identifier was not found.')
                        due=_parse_import_date(values['due_month'],'due month').date().replace(day=1); amount=float(values['amount']); status=normalize_unicode_text(values.get('status')) or 'Unpaid'
                        if amount<0 or status not in {'Unpaid','Paid','Adjusted'}: raise ValueError('Invalid dues amount or status.')
                        # Lock the billing period and preserve any previously verified settlement.
                        cursor.execute("SELECT id,amount,status,settled_at FROM monthly_dues WHERE user_id=%s AND due_month=%s FOR UPDATE",(u['id'],due))
                        existing=cursor.fetchone()
                        if existing:
                            duplicates+=1
                            if conflict=='skip': continue
                            # Never replace a settled obligation or an allocated payment
                            # with an imported Unpaid/Paid/Adjusted label. Imports are
                            # billing history, NOT evidence of a verified payment.
                            cursor.execute("""SELECT COUNT(*) AS n FROM monthly_dues_allocations a
                                JOIN monthly_dues_payments p ON p.id=a.payment_id
                                WHERE a.monthly_due_id=%s AND p.voided_at IS NULL""",(existing['id'],))
                            allocation=cursor.fetchone()
                            if existing['status'] in ('Paid','Adjusted') or existing.get('settled_at') or allocation['n']:
                                errors.append(f'Row {row_no}: existing settled/allocated billing period preserved')
                                continue
                            if status!='Unpaid':
                                errors.append(f'Row {row_no}: imported payment status is not verified; period preserved')
                                continue
                            cursor.execute("UPDATE monthly_dues SET amount=%s WHERE id=%s AND status='Unpaid'",(amount,existing['id']))
                        else:
                            if status!='Unpaid':
                                errors.append(f'Row {row_no}: imported Paid/Adjusted status requires a separate verified payment workflow')
                                continue
                            cursor.execute("INSERT INTO monthly_dues (user_id,due_month,amount,status) VALUES (%s,%s,%s,'Unpaid')",(u['id'],due,amount))
                        cursor.execute("""INSERT INTO audit_logs(username,role,action,item,new_val)
                            VALUES (%s,%s,'Monthly Dues Import',%s,%s)""",
                            (session.get('username'),session.get('role'),str(u['id']),
                             f'period={due}; amount={amount:.2f}; status=Unpaid; file={filename}'))
                        success+=1
                    elif dataset=='fees':
                        item=normalize_unicode_text(values['item_name']); amount=float(values['amount']); proposed=values.get('proposed_amount'); status=normalize_unicode_text(values.get('status')) or 'Active'
                        if not item or amount<0 or status not in {'Active','Pending Executive Approval'}: raise ValueError('Invalid fee item, amount, or status.')
                        cursor.execute("SELECT item_name FROM fees WHERE item_name=%s",(item,)); existing=cursor.fetchone()
                        if existing:
                            duplicates+=1
                            if conflict=='skip': continue
                            cursor.execute("UPDATE fees SET amount=%s,proposed_amount=%s,status=%s WHERE item_name=%s",(amount,float(proposed) if proposed not in (None,'') else None,status,item))
                        else:
                            cursor.execute("INSERT INTO fees (item_name,amount,proposed_amount,status) VALUES (%s,%s,%s,%s)",(item,amount,float(proposed) if proposed not in (None,'') else None,status))
                        success+=1
                    elif dataset=='historical_requests':
                        req_id=normalize_unicode_text(values['id']); u=_resolve_homeowner(cursor,values['homeowner_identifier']); req_type=normalize_unicode_text(values['request_type']); status=normalize_unicode_text(values['status'])
                        allowed_status={'Submitted','Under Review','Checked','For Correction','Pending Executive Approval','Approved','Awaiting Dues Clearance','Awaiting Payment Verification','Ready for Payment & Release','Paid - Awaiting Release','Ready for Release','Issued / Completed','Rejected','Paid and Approved','Cancelled'}
                        if not req_id or not u or not req_type or status not in allowed_status: raise ValueError('Invalid request ID, homeowner, request type, or status.')
                        cursor.execute("SELECT id FROM requests WHERE id=%s",(req_id,)); existing=cursor.fetchone()
                        if existing:
                            duplicates+=1
                            if conflict=='skip': continue
                            cursor.execute("UPDATE requests SET request_type=%s,category=%s,assigned_officer=%s,fee=%s,details=%s,remarks=%s,purpose=%s,status=%s,payment_status=%s,last_updated=%s WHERE id=%s",
                                           (req_type,normalize_unicode_text(values.get('category')) or 'Document Request',normalize_unicode_text(values.get('assigned_officer')) or None,float(values.get('fee') or 0),
                                            normalize_unicode_text(values.get('details')) or None,normalize_unicode_text(values.get('remarks')) or None,normalize_unicode_text(values.get('purpose')) or None,status,
                                            normalize_unicode_text(values.get('payment_status')) or 'Unpaid',_parse_import_date(values.get('last_updated'),'last updated') or datetime.now(),req_id))
                        else:
                            submitted=_parse_import_date(values['date_submitted'],'date submitted')
                            cursor.execute("""INSERT INTO requests (id,user_id,request_type,category,submission_type,assigned_officer,fee,details,remarks,purpose,status,payment_status,date_submitted,last_updated)
                                              VALUES (%s,%s,%s,%s,'Query',%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                           (req_id,u['id'],req_type,normalize_unicode_text(values.get('category')) or 'Document Request',normalize_unicode_text(values.get('assigned_officer')) or None,
                                            float(values.get('fee') or 0),normalize_unicode_text(values.get('details')) or None,normalize_unicode_text(values.get('remarks')) or None,normalize_unicode_text(values.get('purpose')) or None,
                                            status,normalize_unicode_text(values.get('payment_status')) or 'Unpaid',submitted,_parse_import_date(values.get('last_updated'),'last updated') or submitted))
                        success+=1
                except Exception as row_exc:
                    rejected+=1; errors.append({'row':row_no,'message':str(row_exc)[:220]})
            _import_history(cursor,'Excel',filename,cfg['label'],total,success,rejected,duplicates,'Completed with errors' if rejected else 'Completed',{'errors':errors[:50],'conflict_action':conflict})
        conn.commit()
        log_audit_action(session.get('username'),'Admin','Import Existing Records',filename,None,f"{cfg['label']}: {success} imported/updated, {rejected} rejected, {duplicates} duplicates")
        try: os.remove(path)
        except OSError: pass
        return jsonify({'status':'success','message':'Import completed.','summary':{'total':total,'successful':success,'rejected':rejected,'duplicates':duplicates,'errors':errors[:50]}})
    except Exception:
        if conn:
            try: conn.rollback()
            except Exception: pass
        app.logger.exception('Excel import commit failed')
        return jsonify({'status':'error','message':'The import could not be completed. No pending transaction was committed.'}),500
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@app.route('/admin/import-template/<dataset>.xlsx')
def admin_import_template(dataset):
    if not _require_admin(): return redirect(url_for('index'))
    if dataset not in IMPORT_DATASETS: return redirect(url_for('admin')+'#data-import')
    cfg=IMPORT_DATASETS[dataset]
    wb=Workbook(); ws=wb.active; ws.title=cfg['label'][:31]
    ws.append(cfg['fields'])
    examples={
        'homeowners':['Juan','Santos','Dela Cruz','','juan@example.com','juandelacruz','09171234567','12','8','Phase 1, North Fairway Homes','Male','1990-01-01','Married',4,'REPLACE-WITH-UNIQUE-TEMP-PASSWORD'],
        'monthly_dues':['NFH-B12-L8','2026-09-01',100,'Unpaid'],
        'fees':['Proof of Residency',50,'','Active'],
        'historical_requests':['REQ-HIST-0001','NFH-B12-L8','Proof of Residency','Document Request','Secretary',50,'Imported historical request','','Employment requirement','Issued / Completed','Paid','2026-01-15 09:30','2026-01-15 11:00']
    }
    ws.append(examples[dataset])
    for cell in ws[1]: cell.font=cell.font.copy(bold=True)
    ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
    for col in ws.columns:
        width=min(32,max(12,max(len(str(c.value or '')) for c in col)+2)); ws.column_dimensions[col[0].column_letter].width=width
    out=BytesIO(); wb.save(out); out.seek(0)
    return send_file(out,as_attachment=True,download_name=f"NFH_HOA_{dataset}_Import_Template.xlsx",mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')



# ---------------------------------------------------------------------------
# Dedicated request review page (all roles)
# ---------------------------------------------------------------------------
@app.route('/requests/<req_id>/review')
def request_review(req_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
    _expire_edit_access_for_request(req_id)
    role=session.get('role'); user_id=session.get('user_id')
    conn=get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""SELECT r.*, u.homeowner_public_id, u.first_name, u.middle_name, u.last_name, u.email, u.mobile,
                              u.block, u.lot, u.address_line,
                              CONCAT(u.first_name,' ',COALESCE(NULLIF(u.middle_name,''),''),
                                     CASE WHEN u.middle_name IS NULL OR u.middle_name='' THEN '' ELSE ' ' END,u.last_name) AS homeowner
                              FROM requests r JOIN users u ON u.id=r.user_id WHERE r.id=%s""",(req_id,))
            req=cursor.fetchone()
            if not req:
                flash('Request not found.','error'); return redirect(_role_home_url(role))
            service=get_service_config(cursor,req['request_type'],active_only=False)
            if not _request_review_access_allowed(req,role,user_id,service):
                flash('You are not authorized to review this request.','error'); return redirect(_role_home_url(role))
            dues=dues_summary(cursor,req['user_id'])
            cursor.execute("SELECT * FROM request_history WHERE request_id=%s ORDER BY created_at ASC",(req_id,)); history=cursor.fetchall()
            cursor.execute("SELECT * FROM request_concerns WHERE request_id=%s ORDER BY created_at ASC",(req_id,)); concerns=cursor.fetchall()
            cursor.execute("SELECT * FROM payment_transactions WHERE request_id=%s",(req_id,)); payment_tx=cursor.fetchone()
            template=None
            if req.get('document_template_id'):
                cursor.execute("SELECT * FROM document_templates WHERE id=%s",(req['document_template_id'],)); template=cursor.fetchone()
            if not template:
                template=get_active_document_template(cursor,request_type=req['request_type'])
        details=_safe_details(req.get('details'))
        active_edit=_request_edit_access_active(req)
        checker_allowed=role in {'Secretary','Treasurer'} and role_can_initial_check(role,req['request_type'],req.get('assigned_officer'))
        has_open_concern=any(c.get('status') in {'Open','Under Review','Responded'} for c in concerns)
        can_grant_edit=(checker_allowed and has_open_concern and not active_edit and req.get('status') in {'Submitted','Under Review','Pending Executive Approval'})
        can_initial_review=(role in {'Secretary','Treasurer'} and req.get('status') in {'Submitted','Under Review'} and checker_allowed and not active_edit)
        can_exec_approve=(role in EXECUTIVE_ROLES) and req.get('status')=='Pending Executive Approval' and not active_edit
        can_cancel=(role=='Homeowner' and req.get('user_id')==user_id and req.get('status') in {'Submitted','Under Review'})
        can_edit=(role=='Homeowner' and req.get('user_id')==user_id and (req.get('status')=='For Correction' or active_edit))
        return render_template('request_review.html', req=req, service=service, dues=dues, history=history,
                               concerns=concerns, payment_tx=payment_tx, details=details, template=template,
                               active_edit=active_edit, can_grant_edit=can_grant_edit, can_initial_review=can_initial_review,
                               can_exec_approve=can_exec_approve, can_cancel=can_cancel, can_edit=can_edit,
                               edit_durations=REQUEST_EDIT_ACCESS_MINUTES, role=role)
    finally:
        conn.close()


@app.route('/officer/requests/<req_id>/grant-edit-access', methods=['POST'])
def grant_request_edit_access(req_id):
    if 'user_id' not in session or session.get('role') not in {'Secretary','Treasurer'}:
        return redirect(url_for('index'))
    role=session.get('role')
    try:
        minutes=int(request.form.get('duration_minutes') or 60)
    except ValueError:
        minutes=60
    if minutes not in REQUEST_EDIT_ACCESS_MINUTES:
        minutes=60
    reason=(request.form.get('reason') or 'Homeowner requested correction through Request Concern.').strip()[:1000]
    expires=datetime.now()+timedelta(minutes=minutes)
    conn=get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id,user_id,request_type,status,assigned_officer,edit_access_expires_at FROM requests WHERE id=%s",(req_id,))
            req=cursor.fetchone()
            if not req:
                flash('Request not found.','error'); return redirect(url_for('officer'))
            service=get_service_config(cursor,req['request_type'],active_only=False)
            if not role_can_initial_check(role,req['request_type'],req.get('assigned_officer')):
                flash('Only the responsible initial reviewer may grant edit access.','error'); return redirect(url_for('request_review',req_id=req_id))
            if req.get('status') not in {'Submitted','Under Review','Pending Executive Approval'}:
                flash('Temporary edit access is not available at this request stage.','error'); return redirect(url_for('request_review',req_id=req_id))
            cursor.execute("SELECT id FROM request_concerns WHERE request_id=%s AND status IN ('Open','Under Review','Responded') ORDER BY created_at DESC LIMIT 1",(req_id,))
            concern=cursor.fetchone()
            if not concern:
                flash('Edit access can be granted only after the homeowner reports a Request Concern.','error'); return redirect(url_for('request_review',req_id=req_id))
            previous=req.get('edit_access_expires_at')
            cursor.execute("""UPDATE requests SET edit_access_granted_at=NOW(),edit_access_expires_at=%s,
                              edit_access_granted_by=%s,edit_access_reason=%s,edit_access_expired_at=NULL WHERE id=%s""",
                           (expires,session.get('full_name') or session.get('username'),reason,req_id))
        deadline=expires.strftime('%B %d, %Y at %I:%M %p')
        record_request_history(req_id,'Temporary Edit Access Granted',req.get('status'),req.get('status'),
                               f'Edit access granted until {deadline}. Reason: {reason}')
        log_audit_action(session.get('username'),role,'Grant Temporary Request Edit Access',req_id,previous,deadline)
        body=(f"Temporary edit access was granted for your {req['request_type']} request {req_id}.\n\n"
              f"Edit deadline: {deadline}\nReason: {reason}\n\n"
              "Open Request Review in the NFH-HOA portal, update only the incorrect information, and resubmit before the deadline. "
              "After you submit an edit, the request returns to initial review so the revised information can be checked again.")
        result=send_alert_and_email(req['user_id'],f'Edit Access Granted — {req_id}',body,'request',req_id,f'edit-access-{req_id}-{int(time.time())}')
        flash(f'Temporary edit access granted until {deadline}.','success')
        if not result.get('email_sent'):
            flash('The in-app notification was created, but email delivery was unavailable.','warning')
    finally:
        conn.close()
    return redirect(url_for('request_review',req_id=req_id))

# ---------------------------------------------------------------------------
# Admin PDF reports (with filters)
# ---------------------------------------------------------------------------
def _require_admin():
    return 'user_id' in session and session.get('role') == 'Admin'


def _filters_paragraph(styles, filters):
    active = [f"{k}: {v}" for k, v in filters.items() if v]
    text = 'Filters applied: ' + (', '.join(active) if active else 'None (showing all records)')
    return Paragraph(text, styles['NFHSub'])


@app.route('/admin/reports/audit-trail/pdf')
def report_audit_trail_pdf():
    if not _require_admin():
        return redirect(url_for('index'))
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    username = request.args.get('username', '')
    role = request.args.get('role', '')
    action = request.args.get('action', '')

    query = "SELECT * FROM audit_logs WHERE 1=1"
    params = []
    if date_from:
        query += " AND timestamp >= %s"; params.append(date_from + ' 00:00:00')
    if date_to:
        query += " AND timestamp <= %s"; params.append(date_to + ' 23:59:59')
    if username:
        query += " AND username LIKE %s"; params.append(f"%{username}%")
    if role:
        query += " AND role = %s"; params.append(role)
    if action:
        query += " AND action LIKE %s"; params.append(f"%{action}%")
    query += " ORDER BY timestamp ASC"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
    conn.close()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch)
    styles = _pdf_styles()
    elements = []
    _pdf_letterhead(elements, styles, 'Audit Trail Report')
    elements.append(_filters_paragraph(styles, {
        'Date From': date_from, 'Date To': date_to, 'User': username, 'Role': role, 'Action': action}))
    elements.append(Spacer(1, 10))

    from nfh_report_layout import report_table, page_footer
    from reportlab.lib.pagesizes import landscape, A4
    # Landscape width protects timestamps and preserves full before/after values.
    doc.pagesize = landscape(A4)
    audit_rows = [[format_pdf_datetime(r['timestamp'])[:16], r['username'] or '-', r['role'] or '-',
                   r['action'] or '-', r['item'] or '-', r['prev_val'] or '-', r['new_val'] or '-'] for r in rows]
    elements.append(report_table(['Timestamp','User','Role','Action','Affected Item','Previous Value','New Value'],
                                audit_rows,[90,86,65,111,110,132,132],font_size=7))
    elements.append(Spacer(1, 16))
    elements.append(Paragraph(f"Generated on {now_str()} by {session.get('username')}.", styles['NFHSub']))
    doc.build(elements,onFirstPage=page_footer,onLaterPages=page_footer)
    log_audit_action(session.get('username'), session.get('role'), 'Generate Audit Trail PDF', 'audit_logs')
    return _response_pdf(buffer, 'NFH_Audit_Trail_Report.pdf')


@app.route('/admin/reports/requests/pdf')
def report_requests_pdf():
    if not _require_admin():
        return redirect(url_for('index'))
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    status = request.args.get('status', '')
    req_type = request.args.get('request_type', '')
    payment_status = request.args.get('payment_status', '')

    query = """SELECT r.*, CONCAT(u.first_name,' ',u.last_name) AS homeowner FROM requests r
               JOIN users u ON r.user_id = u.id WHERE 1=1"""
    params = []
    if date_from:
        query += " AND r.date_submitted >= %s"; params.append(date_from + ' 00:00:00')
    if date_to:
        query += " AND r.date_submitted <= %s"; params.append(date_to + ' 23:59:59')
    if status:
        query += " AND r.status = %s"; params.append(status)
    if req_type:
        query += " AND r.request_type = %s"; params.append(req_type)
    if payment_status:
        query += " AND r.payment_status = %s"; params.append(payment_status)
    query += " ORDER BY r.date_submitted DESC"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
    conn.close()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch)
    styles = _pdf_styles()
    elements = []
    _pdf_letterhead(elements, styles, 'Request Monitoring Report')
    elements.append(_filters_paragraph(styles, {
        'Date From': date_from, 'Date To': date_to, 'Status': status,
        'Type': req_type, 'Payment': payment_status}))
    elements.append(Spacer(1, 10))

    table_rows = [['ID', 'Homeowner', 'Type', 'Status', 'Payment', 'Submitted']]
    for r in rows:
        table_rows.append([r['id'], r['homeowner'], r['request_type'], r['status'], r['payment_status'],
                           format_pdf_datetime(r['date_submitted'])])
    if len(table_rows) == 1:
        table_rows.append(['No matching records', '', '', '', '', ''])
    t = Table(table_rows, repeatRows=1, colWidths=[1.3 * inch, 1.3 * inch, 1.5 * inch, 1.1 * inch, 0.8 * inch, 1.1 * inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B4332')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#CCCCCC')),
    ]))
    elements.append(t)
    doc.build(elements)
    log_audit_action(session.get('username'), session.get('role'), 'Generate Request Monitoring PDF', 'requests')
    return _response_pdf(buffer, 'NFH_Request_Monitoring_Report.pdf')


@app.route('/admin/reports/adjustments/pdf')
def report_adjustments_pdf():
    if not _require_admin():
        return redirect(url_for('index'))
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    query = "SELECT * FROM financial_adjustments WHERE 1=1"
    params = []
    if date_from:
        query += " AND created_at >= %s"; params.append(date_from + ' 00:00:00')
    if date_to:
        query += " AND created_at <= %s"; params.append(date_to + ' 23:59:59')
    query += " ORDER BY created_at DESC"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
    conn.close()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch)
    styles = _pdf_styles()
    elements = []
    _pdf_letterhead(elements, styles, 'Missing Monthly Dues Report')
    elements.append(_filters_paragraph(styles, {'Date From': date_from, 'Date To': date_to}))
    elements.append(Spacer(1, 10))

    table_rows = [['ID', 'Homeowner', 'Monthly Due', 'Missing Months', 'Total', 'Submitted By', 'Date']]
    for r in rows:
        table_rows.append([r['id'], r['homeowner_name'], f"₱{float(r['monthly_due']):.2f}",
                           r['missing_months'], f"₱{float(r['proposed_adjustment']):.2f}",
                           r['submitted_by'], str(r['created_at'])])
    if len(table_rows) == 1:
        table_rows.append(['No matching records', '', '', '', '', '', ''])
    t = Table(table_rows, repeatRows=1, colWidths=[0.5 * inch, 1.3 * inch, 0.9 * inch, 0.9 * inch, 0.8 * inch, 1.0 * inch, 1.1 * inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B4332')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#CCCCCC')),
    ]))
    elements.append(t)
    doc.build(elements)
    log_audit_action(session.get('username'), session.get('role'), 'Generate Missing Dues PDF', 'financial_adjustments')
    return _response_pdf(buffer, 'NFH_Missing_Dues_Report.pdf')



@app.route('/admin/reports/homeowners/pdf', methods=['GET'])
def report_homeowners_pdf():
    """Verified homeowner roster, filtered by actual Admin-controlled account status."""
    if not _require_admin():
        return redirect(url_for('index'))

    status = (request.args.get('status') or 'All').strip().title()
    if status not in {'All', 'Active', 'Inactive'}:
        return jsonify({'error': 'Invalid homeowner status filter.'}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""SELECT status, COUNT(*) AS total
                              FROM users WHERE role='Homeowner'
                                AND verification_status='Verified'
                                AND status IN ('Active', 'Inactive')
                              GROUP BY status""")
            counts = {row['status']: row['total'] for row in cursor.fetchall()}
            query = """SELECT homeowner_public_id, first_name, middle_name, last_name,
                              suffix, block, lot, address_line, status
                       FROM users
                       WHERE role='Homeowner' AND verification_status='Verified'
                         AND status IN ('Active', 'Inactive')"""
            params = []
            if status != 'All':
                query += ' AND status=%s'
                params.append(status)
            query += " ORDER BY CASE WHEN status='Active' THEN 0 ELSE 1 END, last_name, first_name, id"
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
    finally:
        conn.close()

    from nfh_report_layout import report_table, page_footer
    from reportlab.lib.pagesizes import landscape
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(LETTER),
                            topMargin=0.6*inch, bottomMargin=0.6*inch,
                            leftMargin=0.5*inch, rightMargin=0.5*inch)
    styles = _pdf_styles()
    elements = []
    _pdf_letterhead(elements, styles, 'Homeowner Account Status Report')
    elements.append(_filters_paragraph(styles, {'Account Status': status}))
    elements.append(Spacer(1, 8))
    active = counts.get('Active', 0)
    inactive = counts.get('Inactive', 0)
    elements.append(Paragraph(
        f'All verified homeowners: {active + inactive} | Active: {active} | '
        f'Inactive: {inactive} | Records in report: {len(rows)}', styles['NFHBody']))
    elements.append(Paragraph(
        'Account status controls system access. Pending and rejected registrations are excluded.',
        styles['NFHSub']))
    elements.append(Spacer(1, 10))
    entries = []
    for row in rows:
        name = ' '.join(str(row.get(k) or '').strip() for k in
                        ('first_name', 'middle_name', 'last_name', 'suffix')).strip()
        property_number = ' / '.join(part for part in
            (f"Blk {row['block']}" if row.get('block') else '',
             f"Lot {row['lot']}" if row.get('lot') else '') if part)
        entries.append((row.get('homeowner_public_id') or '-', name,
                        property_number or '-', row.get('address_line') or '-', row['status']))
    elements.append(report_table(
        ['Homeowner ID', 'Full Name', 'Block / Lot', 'Registered Address', 'Account Status'],
        entries, [1.1*inch, 2.0*inch, 1.1*inch, 3.0*inch, 1.0*inch], font_size=8))
    doc.build(elements, onFirstPage=page_footer, onLaterPages=page_footer)
    log_audit_action(session.get('username'), 'Admin',
                     'Generate Homeowner Account Status PDF', f'users: {status}')
    return _response_pdf(buffer, f'NFH_Homeowner_Account_Status_{status}.pdf')


@app.route('/admin/reports/officers/pdf')
def report_officers_pdf():
    if not _require_admin():
        return redirect(url_for('index'))
    role = request.args.get('role', '')
    status = request.args.get('status', '')

    query = "SELECT * FROM users WHERE role IN ('Secretary','Treasurer','President','Vice President','Board Director')"
    params = []
    if role:
        query += " AND role = %s"; params.append(role)
    if status:
        query += " AND status = %s"; params.append(status)
    query += " ORDER BY created_at DESC"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
    conn.close()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch)
    styles = _pdf_styles()
    elements = []
    _pdf_letterhead(elements, styles, 'Officer Account Records Report')
    elements.append(_filters_paragraph(styles, {'Role': role, 'Status': status}))
    elements.append(Spacer(1, 10))

    table_rows = [['ID', 'Full Name', 'Username', 'Email', 'Phone', 'Role', 'Status']]
    for r in rows:
        table_rows.append([r['id'], f"{r['first_name']} {r['last_name']}", r['username'],
                           r['email'], r['mobile'], r['role'], r['status']])
    if len(table_rows) == 1:
        table_rows.append(['No matching records', '', '', '', '', '', ''])
    t = Table(table_rows, repeatRows=1, colWidths=[0.4 * inch, 1.3 * inch, 1.0 * inch, 1.5 * inch, 0.9 * inch, 0.8 * inch, 0.7 * inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B4332')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#CCCCCC')),
    ]))
    elements.append(t)
    doc.build(elements)
    log_audit_action(session.get('username'), session.get('role'), 'Generate Officer Account Records PDF', 'users')
    return _response_pdf(buffer, 'NFH_Officer_Account_Records_Report.pdf')


@app.route('/admin/reports/processing-time/pdf')
def report_processing_time_pdf():
    if not _require_admin():
        return redirect(url_for('index'))
    request_type = (request.args.get('request_type') or '').strip()
    query = """SELECT r.id, r.request_type,
                      CONCAT(u.first_name,' ',u.last_name) AS homeowner,
                      r.date_submitted, h.reviewed_at, r.executive_decided_at,
                      r.ready_for_release_at, r.issued_at,
                      ROUND(TIMESTAMPDIFF(MINUTE,r.date_submitted,r.issued_at)/60,2) AS total_hours
               FROM requests r
               JOIN users u ON u.id=r.user_id
               LEFT JOIN (
                   SELECT request_id, MIN(created_at) AS reviewed_at
                   FROM request_history WHERE action='Initial Review' GROUP BY request_id
               ) h ON h.request_id=r.id
               WHERE r.status='Issued / Completed' AND r.issued_at IS NOT NULL"""
    params=[]
    if request_type:
        query += " AND r.request_type=%s"
        params.append(request_type)
    query += " ORDER BY r.issued_at DESC"
    conn=get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute(query, tuple(params))
        rows=cursor.fetchall()
    conn.close()
    buffer=BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=LETTER,topMargin=0.6*inch,bottomMargin=0.6*inch,leftMargin=0.45*inch,rightMargin=0.45*inch)
    styles=_pdf_styles(); elements=[]
    _pdf_letterhead(elements,styles,'Document Request Processing Time Report')
    elements.append(_filters_paragraph(styles,{'Request Type':request_type}))
    elements.append(Spacer(1,10))
    table_rows=[['Request ID','Service Type','Submitted','Initial Review','Executive Approval','Ready for Release','Issued / Completed','Total Hrs']]
    for r in rows:
        table_rows.append([r['id'],r['request_type'],format_pdf_datetime(r['date_submitted']),
                           format_pdf_datetime(r.get('reviewed_at')),format_pdf_datetime(r.get('executive_decided_at')),
                           format_pdf_datetime(r.get('ready_for_release_at')),format_pdf_datetime(r.get('issued_at')),
                           r.get('total_hours') if r.get('total_hours') is not None else '—'])
    if len(table_rows)==1:
        table_rows.append(['No completed requests','','','','','','',''])
    t=Table(table_rows,repeatRows=1,colWidths=[0.8*inch,1.0*inch,1.05*inch,1.0*inch,0.9*inch,0.9*inch,0.9*inch,0.6*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1B4332')),('TEXTCOLOR',(0,0),(-1,0),colors.white),
        ('FONTSIZE',(0,0),(-1,-1),6.8),('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#CCCCCC')),
        ('VALIGN',(0,0),(-1,-1),'TOP')]))
    elements.append(t); doc.build(elements)
    log_audit_action(session.get('username'),session.get('role'),'Generate Processing Time PDF','requests')
    return _response_pdf(buffer,'NFH_Document_Request_Processing_Time_Report.pdf')


from nfh_extensions import init_extensions
app.register_blueprint(init_extensions(get_db_connection))

# ===========================================================================

# Additive monthly dues automation endpoints; existing routes remain unchanged.
from dues_automation import allocate_payment as _allocate_monthly_payment

@app.route('/api/treasurer/monthly-dues/allocate', methods=['POST'])
def treasurer_allocate_monthly_dues():
    if session.get('role') != 'Treasurer' or not session.get('user_id'):
        return jsonify({'status':'error','message':'Treasurer access required.'}), 403
    data = request.get_json(silent=True) or {}
    try:
        homeowner_id = int(data.get('user_id'))
        from decimal import Decimal
        amount = Decimal(str(data.get('amount')))
        if not amount.is_finite() or amount <= 0:
            raise ValueError('Invalid payment amount')
    except (ValueError, TypeError, ArithmeticError):
        return jsonify({'status':'error','message':'Enter a valid homeowner and positive payment amount.'}), 400
    conn = None
    try:
        conn = get_db_connection(autocommit=False)
        result = _allocate_monthly_payment(conn, homeowner_id, amount,
                                            session.get('username','Treasurer'),
                                            preview=bool(data.get('preview')))
        return jsonify({'status':'success', **result})
    except Exception:
        if conn:
            conn.rollback()
        app.logger.exception('Monthly dues allocation failed')
        return jsonify({'status':'error','message':'Unable to process monthly dues payment.'}), 500
    finally:
        if conn:
            conn.close()


# Treasurer-only advance dues (face-to-face verified cash; no online checkout).
@app.route('/api/treasurer/advance-dues/homeowners', methods=['GET'])
def nfh_advance_homeowners():
    if session.get('role')!='Treasurer':return jsonify(error='Forbidden'),403
    query=(request.args.get('search') or '').strip()[:100]
    conn=get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("""SELECT u.id,CONCAT(u.first_name,' ',u.last_name) name,u.block,u.lot,
                COALESCE((SELECT SUM(GREATEST(d.amount-COALESCE(a.paid,0)-COALESCE(x.discount,0),0))
                 FROM monthly_dues d
                 LEFT JOIN (SELECT al.monthly_due_id,SUM(al.amount) paid FROM monthly_dues_allocations al
                   JOIN monthly_dues_payments p ON p.id=al.payment_id WHERE p.voided_at IS NULL GROUP BY al.monthly_due_id) a ON a.monthly_due_id=d.id
                 LEFT JOIN (SELECT monthly_due_id,SUM(discount_amount) discount FROM nfh_advance_periods GROUP BY monthly_due_id) x ON x.monthly_due_id=d.id
                 WHERE d.user_id=u.id AND d.due_month<=CURRENT_DATE()),0) outstanding,
                (SELECT COUNT(*) FROM nfh_advance_periods ap JOIN monthly_dues d2 ON d2.id=ap.monthly_due_id
                  WHERE d2.user_id=u.id AND ap.due_month>DATE_FORMAT(CURRENT_DATE(),'%%Y-%%m-01')) coverage
                FROM users u WHERE u.role='Homeowner' AND u.status='Active'
                AND (%s='' OR LOWER(CONCAT_WS(' ',u.first_name,u.last_name,COALESCE(u.homeowner_public_id,''),COALESCE(u.block,''),COALESCE(u.lot,''))) LIKE CONCAT('%%',LOWER(%s),'%%'))
                ORDER BY u.last_name,u.first_name LIMIT 100""",(query,query))
            homeowners=c.fetchall()
            c.execute("SELECT amount FROM fees WHERE item_name='Monthly Dues' AND status='Active' LIMIT 1")
            fee=c.fetchone()
        return jsonify(homeowners=[dict(id=r['id'],name=r['name'],block=r['block'],lot=r['lot'],outstanding=str(r['outstanding']),coverage=r['coverage']) for r in homeowners],
                      rate=str(fee['amount']) if fee else '0')
    except Exception:
        app.logger.exception('Advance homeowners lookup failed')
        return jsonify(error='Unable to retrieve advance dues records. Confirm the additive migration was applied.'),503
    finally:conn.close()

@app.route('/api/treasurer/advance-dues', methods=['POST'])
def nfh_record_advance_dues():
    if session.get('role')!='Treasurer' or not session.get('user_id'):
        return jsonify(error='Treasurer authorization required'),403
    data=request.get_json(silent=True) or {}
    from advance_dues import pay_advance
    from datetime import date
    if data.get('policy_id') not in (None, '', 0):
        return jsonify(error='Advance payment discount policies are not supported'),400
    conn=None
    try:
        conn=get_db_connection(autocommit=False)
        result=pay_advance(conn,int(data['user_id']),str(data['start_month']),int(data['months']),
           None, data['cash_received'],
           str(data.get('method','Cash')),str(data.get('reference') or ''),date.fromisoformat(data['payment_date']),
           str(data.get('remarks') or ''),str(session.get('username','Treasurer')),str(data['request_key']),
           manual_discount=data.get('discount_amount',0))
        # Physical raffle distribution requires an explicit Treasurer confirmation.
        # The award itself never implies that paper tickets were handed out.
        if (not result.get('duplicate') and data.get('raffle_distributed') is True
                and int(data['months']) == 12 and str(data['start_month']).endswith('-01')):
            with conn.cursor() as promo_cursor:
                promo_cursor.execute("""SELECT a.id, a.raffle_tickets FROM nfh_advance_promo_awards a
                    JOIN nfh_advance_transactions t ON t.user_id=a.user_id
                    WHERE t.id=%s AND a.coverage_year IN
                    (SELECT YEAR(due_month) FROM nfh_advance_periods WHERE transaction_id=%s)
                    FOR UPDATE""", (result['id'], result['id']))
                for awarded in promo_cursor.fetchall():
                    if int(awarded['raffle_tickets']) == 12:
                        promo_cursor.execute("""INSERT IGNORE INTO nfh_advance_promo_distributions
                            (award_id,tickets_distributed,confirmed_by)
                            VALUES (%s,12,%s)""", (awarded['id'], str(session.get('username','Treasurer'))))
        conn.commit()
        # Notify only for newly committed payments. The stable payment transaction ID
        # is the notification dedupe key, not the browser request timestamp.
        if not result.get('duplicate'):
            try:
                from advance_payment_email import prepare_advance_email
                email_conn=get_db_connection()
                try:
                    with email_conn.cursor() as email_cursor:
                        notice=prepare_advance_email(email_cursor,result['id'])
                finally:
                    email_conn.close()
                send_alert_and_email(
                    int(data['user_id']), 'Advance Payment Confirmation and Promo Codes – NFH-HOA',
                    notice[0], related_type='advance_payment', related_id=str(result['id']),
                    dedupe_key=f'advance-dues-confirm-{result["id"]}', html_body=notice[1])
            except Exception:
                # Mail/presentation problems must never reverse a committed payment.
                app.logger.exception('Advance dues confirmation notification failed for transaction %s', result['id'])
        return jsonify(status='success',**result)
    except (ValueError,KeyError,TypeError,ArithmeticError) as e:
        if conn:conn.rollback()
        return jsonify(error=str(e)),400
    except Exception:
        if conn:conn.rollback()
        app.logger.exception('Advance dues transaction failed')
        return jsonify(error='Advance payment was not recorded. Check server logs and migration.'),503
    finally:
        if conn:conn.close()

@app.route('/api/homeowner/promo-codes',methods=['GET'])
def nfh_homeowner_promo_codes():
    if session.get('role') != 'Homeowner' or not session.get('user_id'):
        return jsonify(error='Homeowner authorization required'),403
    from advance_promo import list_codes, CERTIFICATES
    service=request.args.get('service','').strip()
    if service and service not in CERTIFICATES:
        return jsonify(codes=[])
    conn=get_db_connection()
    try:
        with conn.cursor() as cur:
            if service:
                config = get_service_config(cur, service, active_only=False)
                if not config or not bool(config.get('requires_payment')) or float(config.get('fee') or 0) <= 0:
                    return jsonify(codes=[])
            return jsonify(codes=[{'code':r['code'],'expires_at':r['expires_at'],
                 'coverage_year':r['coverage_year']} for r in list_codes(cur,homeowner=session['user_id'],status='Active')])
    finally:conn.close()

@app.route('/api/promo-codes', methods=['GET'])
def nfh_officer_promo_codes():
    """Shared Treasurer/Admin promo listing; JSON on both success and failure."""
    if not session.get('user_id'):
        return jsonify(status='error', error='Session expired. Please sign in again.', session_expired=True), 401
    if session.get('role') not in ('Treasurer', 'Admin'):
        return jsonify(status='error', error='Promo Code Management is restricted to authorized officers.'), 403
    from advance_promo import list_codes
    query = request.args.get('search', '').strip()[:100]
    year = request.args.get('year', '').strip()
    if year and (not year.isdigit() or not 2000 <= int(year) <= 2200):
        return jsonify(status='error', error='Invalid coverage year.'), 400
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            codes = list_codes(cur, search=query, year=int(year) if year else None, limit=None)
        return jsonify(status='success', codes=codes)
    except pymysql.err.ProgrammingError as exc:
        app.logger.exception('Promo code listing query or schema failure')
        if exc.args and exc.args[0] in (1054, 1146):
            return jsonify(status='error', error='Promo code database setup is incomplete. Ask the administrator to apply the Batch 3 migration.'), 503
        return jsonify(status='error', error='Promo codes could not be loaded. Please contact the administrator.'), 503
    except Exception:
        app.logger.exception('Promo code listing failed')
        return jsonify(status='error', error='Promo codes are temporarily unavailable. Please try again or contact the administrator.'), 503
    finally:
        if conn is not None:
            conn.close()

@app.route('/api/treasurer/advance-promo/<int:homeowner_id>', methods=['GET'])
def nfh_advance_promo_summary(homeowner_id):
    if session.get('role') != 'Treasurer':
        return jsonify(error='Treasurer authorization required'),403
    from advance_promo import promo_summary
    conn=get_db_connection()
    try:
        with conn.cursor() as c:
            return jsonify(awards=promo_summary(c,homeowner_id))
    finally:
        conn.close()

@app.route('/api/homeowner/advance-dues', methods=['GET'])
def nfh_homeowner_advance_dues():
    if session.get('role')!='Homeowner' or not session.get('user_id'):
        return jsonify(error='Homeowner authorization required'),403
    conn=get_db_connection()
    try:
        with conn.cursor() as c:
            c.execute("""SELECT t.id,t.gross_amount,t.cash_received,t.discount_amount,t.payment_method,
                t.payment_reference,t.created_at,ap.due_month,ap.cash_amount,ap.discount_amount AS period_discount
                FROM nfh_advance_transactions t JOIN nfh_advance_periods ap ON ap.transaction_id=t.id
                WHERE t.user_id=%s ORDER BY ap.due_month DESC""",(session['user_id'],))
            rows=c.fetchall()
        return jsonify(records=[dict(transaction=r['id'],month=str(r['due_month']),gross=str(r['gross_amount']),
            cash_received=str(r['cash_received']),discount=str(r['discount_amount']),period_cash=str(r['cash_amount']),
            period_discount=str(r['period_discount']),method=r['payment_method'],reference=r['payment_reference'] or '',date=str(r['created_at'])) for r in rows])
    except Exception:
        app.logger.exception('Advance dues homeowner lookup failed')
        return jsonify(error='Advance dues history unavailable'),503
    finally:conn.close()


# HOA Documents: isolated protected routes and existing persistence/audit services.
from hoa_documents import bp as hoa_documents_blueprint
hoa_documents_blueprint.nfh_connection = get_db_connection
hoa_documents_blueprint.nfh_audit = log_audit_action
app.register_blueprint(hoa_documents_blueprint)

from treasurer_financial import bp as treasurer_financial_bp
import treasurer_financial
treasurer_financial.connection = get_db_connection
treasurer_financial.notification_sender = send_alert_and_email
app.register_blueprint(treasurer_financial_bp)

from homeowner_reconciliation import bp as homeowner_reconciliation_bp
import homeowner_reconciliation
homeowner_reconciliation.connection = get_db_connection
app.register_blueprint(homeowner_reconciliation_bp)



# Shared read-only income reporting for Treasurer and Admin.
import transaction_history
transaction_history.connection = get_db_connection
app.register_blueprint(transaction_history.bp)

# ---------------------------------------------------------------------------
# Batch 12: read-only property ledger visibility (requires approved migration).
# IMPORTANT: Legacy homeowner monthly dues remain authoritative until cutover.
# ---------------------------------------------------------------------------
@app.route('/api/property-ledger/properties', methods=['GET'])
def batch12_properties():
    role = session.get('role')
    if not session.get('user_id') or role not in {'Homeowner','Treasurer','Admin'}:
        return jsonify(error='Not authorized'), 403
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            if role == 'Homeowner':
                cur.execute('''SELECT p.id,p.property_code,p.block,p.lot,p.status
                               FROM nfh_properties p JOIN nfh_property_owners o ON o.property_id=p.id
                               WHERE o.homeowner_id=%s AND o.verified_at IS NOT NULL
                                 AND o.effective_from<=CURDATE()
                                 AND (o.effective_to IS NULL OR o.effective_to>=CURDATE())
                               ORDER BY p.block,p.lot''', (session['user_id'],))
            else:
                cur.execute('''SELECT id,property_code,block,lot,status
                               FROM nfh_properties ORDER BY block,lot LIMIT 500''')
            rows = cur.fetchall()
        return jsonify(properties=rows), 200
    except Exception:
        app.logger.exception('Property ledger list unavailable')
        return jsonify(error='Property ledger unavailable; check Batch 12 migration.'), 503
    finally:
        if conn: conn.close()


@app.route('/api/property-ledger/properties/<int:property_id>/dues', methods=['GET'])
def batch12_property_dues(property_id):
    role = session.get('role')
    if not session.get('user_id') or role not in {'Homeowner','Treasurer','Admin'}:
        return jsonify(error='Not authorized'), 403
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            if role == 'Homeowner':
                cur.execute('''SELECT 1 FROM nfh_property_owners WHERE property_id=%s
                               AND homeowner_id=%s AND verified_at IS NOT NULL
                               AND effective_from<=CURDATE()
                               AND (effective_to IS NULL OR effective_to>=CURDATE()) LIMIT 1''',
                            (property_id,session['user_id']))
                if not cur.fetchone():
                    return jsonify(error='Property access denied'), 403
            cur.execute('''SELECT d.billing_period,d.amount_due,d.status,d.payer_type,
                           d.responsible_payer_id,d.rental_agreement_id,
                           COALESCE(SUM(CASE WHEN r.voided_at IS NULL THEN r.amount ELSE 0 END),0) amount_paid
                           FROM nfh_property_monthly_dues d
                           LEFT JOIN nfh_property_due_receipts r ON r.obligation_id=d.id
                           WHERE d.property_id=%s
                           GROUP BY d.id,d.billing_period,d.amount_due,d.status,d.payer_type,
                                    d.responsible_payer_id,d.rental_agreement_id
                           ORDER BY d.billing_period DESC LIMIT 240''', (property_id,))
            dues = cur.fetchall()
        for row in dues:
            row['outstanding_balance'] = str(max(0, row['amount_due']-row['amount_paid']))
            row['amount_due'] = str(row['amount_due'])
            row['amount_paid'] = str(row['amount_paid'])
            row['billing_period'] = row['billing_period'].isoformat()
        return jsonify(property_id=property_id,dues=dues), 200
    except Exception:
        app.logger.exception('Property dues ledger unavailable')
        return jsonify(error='Property dues unavailable; check Batch 12 migration.'), 503
    finally:
        if conn: conn.close()

from renter_accounts import register_renter_routes
register_renter_routes(app, get_db_connection, mail, _registration_email_verified, _send_system_message, _set_login_session)
from first_time_enrollment import register_enrollment_routes
register_enrollment_routes(app, get_db_connection, _registration_email_verified)

from officer_task_queue import register_officer_task_routes
register_officer_task_routes(app, get_db_connection)

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in {'1','true','yes','on'}
    app.run(debug=debug_mode, host=os.getenv('FLASK_HOST','127.0.0.1'), port=int(os.getenv('FLASK_PORT','5000')))


