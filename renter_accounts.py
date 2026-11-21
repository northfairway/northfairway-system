"""Batch 12 invitation and verified-occupancy account integration.

Important: Renter request submission and property-billing cutover are deliberately
not enabled here. Those require migration and service-level approval integration.
"""
import hashlib
import secrets
import re
from datetime import datetime, timedelta, date
from flask import request, session, jsonify, render_template, redirect, url_for, current_app
from flask_mail import Message
from werkzeug.security import generate_password_hash
from pymysql import IntegrityError

EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

def _email(value):
    return (value or '').strip().lower()

def _hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def _error(message, code=400):
    return jsonify(status='error', message=message), code

def register_renter_routes(app, get_db_connection, mail, registration_email_verified, send_mail, set_login_session):
    def current_user(*roles):
        return session.get('user_id') if session.get('role') in roles else None

    def owned(cur, property_id, owner_id, lock=False):
        cur.execute('''SELECT id FROM nfh_property_owners WHERE property_id=%s AND homeowner_id=%s
                       AND verified_at IS NOT NULL AND effective_from<=CURDATE()
                       AND (effective_to IS NULL OR effective_to>=CURDATE()) LIMIT 1''' + (' FOR UPDATE' if lock else ''),
                    (property_id,owner_id))
        return bool(cur.fetchone())

    def invitation(cur, token, lock=False):
        cur.execute('''SELECT i.*,r.account_user_id,r.verification_status renter_status,a.id agreement_id,
                             a.verification_status agreement_status
                       FROM nfh_renter_invitations i JOIN nfh_renters r ON r.id=i.renter_id
                       JOIN nfh_rental_agreements a ON a.id=i.agreement_id
                       WHERE i.token_hash=%s AND i.revoked_at IS NULL AND i.expires_at>UTC_TIMESTAMP()
                       ORDER BY a.id DESC LIMIT 1''' + (' FOR UPDATE' if lock else ''), (_hash(token),))
        return cur.fetchone()

    @app.route('/my-properties')
    def homeowner_properties_page():
        if not current_user('Homeowner'):return redirect(url_for('index'))
        return render_template('renter_manage.html')

    @app.route('/admin/renter-verification')
    def renter_admin_page():
        if not current_user('Admin'):return redirect(url_for('index'))
        return render_template('renter_manage.html')

    @app.route('/api/renter/properties', methods=['GET'])
    def renter_owner_properties():
        uid=current_user('Homeowner','Admin')
        if not uid: return _error('Not authorized',403)
        conn=get_db_connection()
        try:
            with conn.cursor() as cur:
                if session['role']=='Admin':
                    cur.execute('''SELECT p.id,p.property_code,p.block,p.lot FROM nfh_properties p
                                   JOIN nfh_property_owners o ON o.property_id=p.id
                                   WHERE o.verified_at IS NOT NULL AND o.effective_from<=CURDATE()
                                   AND (o.effective_to IS NULL OR o.effective_to>=CURDATE())
                                   ORDER BY p.id LIMIT 500''')
                else:
                    cur.execute('''SELECT p.id,p.property_code,p.block,p.lot FROM nfh_properties p
                                   JOIN nfh_property_owners o ON o.property_id=p.id
                                   WHERE o.homeowner_id=%s AND o.verified_at IS NOT NULL
                                   AND o.effective_from<=CURDATE()
                                   AND (o.effective_to IS NULL OR o.effective_to>=CURDATE())
                                   ORDER BY p.id''',(uid,))
                return jsonify(properties=cur.fetchall())
        except Exception:
            app.logger.exception('Failed renter property listing')
            return _error('Property records unavailable. Verify the Batch 12 migration.',503)
        finally: conn.close()

    @app.route('/api/renter/invitations',methods=['POST'])
    def renter_invite():
        user_id=current_user('Homeowner')
        if not user_id:return _error('Only the verified homeowner can issue invitations until administrator-assisted authorization is implemented.',403)
        data=request.get_json(silent=True) or {}
        try:
            property_id=int(data.get('property_id'))
            start=date.fromisoformat(data.get('starts_on',''))
            end=date.fromisoformat(data.get('ends_on',''))
        except (TypeError,ValueError):return _error('Provide a property and valid occupancy dates.')
        name=(data.get('full_name') or '').strip()
        email=_email(data.get('email'))
        payer=data.get('payer_type')
        if len(name)<3 or len(name)>180 or not EMAIL_PATTERN.fullmatch(email) or len(email)>150:
            return _error('Provide a valid renter name and email address.')
        if payer not in ('Homeowner','Renter') or start>end or end<date.today():
            return _error('Invalid agreement dates or payment responsibility.')
        conn=get_db_connection(autocommit=False)
        token=secrets.token_urlsafe(32)
        try:
            with conn.cursor() as cur:
                cur.execute('''SELECT o.homeowner_id FROM nfh_property_owners o
                               JOIN nfh_properties p ON p.id=o.property_id AND p.status='Active'
                               WHERE o.property_id=%s AND o.verified_at IS NOT NULL
                               AND o.effective_from<=CURDATE()
                               AND (o.effective_to IS NULL OR o.effective_to>=CURDATE()) FOR UPDATE''',(property_id,))
                owner_rows=cur.fetchall()
                if len(owner_rows)!=1: return _error('Property ownership must be uniquely verified before inviting a renter.',409)
                owner_id=owner_rows[0]['homeowner_id']
                if int(owner_id)!=int(user_id):return _error('Property access denied',403)
                cur.execute('''SELECT COUNT(*) invite_count FROM nfh_renter_invitations
                               WHERE homeowner_id=%s AND created_at>=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 1 HOUR)''',(user_id,))
                if int(cur.fetchone()['invite_count'])>=5:
                    return _error('Invitation limit reached. Try again later.',429)
                cur.execute('''SELECT id FROM nfh_rental_agreements WHERE property_id=%s
                               AND verification_status IN ('Pending','Verified')
                               AND starts_on<=%s AND ends_on>=%s FOR UPDATE''',(property_id,end,start))
                if cur.fetchall():return _error('A pending or verified agreement already overlaps this occupancy.',409)
                cur.execute('''SELECT id FROM users WHERE LOWER(email)=%s LIMIT 1''',(email,))
                existing=cur.fetchone()
                if existing:
                    cur.execute("SELECT role FROM users WHERE id=%s",(existing['id'],))
                    if cur.fetchone()['role']!='Renter':return _error('Email already belongs to a non-renter account.',409)
                if existing:
                    cur.execute('SELECT id FROM nfh_renters WHERE account_user_id=%s LIMIT 1 FOR UPDATE',(existing['id'],))
                    linked=cur.fetchone()
                    if linked: renter_id=linked['id']
                    else:
                        cur.execute('''INSERT INTO nfh_renters(full_name,email,verification_status,account_user_id) VALUES (%s,%s,'Pending',%s)''',(name,email,existing['id']))
                        renter_id=cur.lastrowid
                else:
                    cur.execute('''SELECT id FROM nfh_renters WHERE LOWER(email)=%s
                                   AND account_user_id IS NULL ORDER BY id DESC LIMIT 1 FOR UPDATE''',(email,))
                    pending=cur.fetchone()
                    if pending: renter_id=pending['id']
                    else:
                        cur.execute('''INSERT INTO nfh_renters(full_name,email,verification_status) VALUES (%s,%s,'Pending')''',(name,email))
                        renter_id=cur.lastrowid
                cur.execute('''INSERT INTO nfh_rental_agreements
                               (property_id,homeowner_id,renter_id,starts_on,ends_on,effective_from,payer_type)
                               VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                            (property_id,owner_id,renter_id,start,end,start,payer))
                agreement_id=cur.lastrowid
                cur.execute('''INSERT INTO nfh_renter_invitations
                               (property_id,homeowner_id,renter_id,agreement_id,token_hash,email,expires_at)
                               VALUES (%s,%s,%s,%s,%s,%s,DATE_ADD(UTC_TIMESTAMP(),INTERVAL 48 HOUR))''',
                            (property_id,owner_id,renter_id,agreement_id,_hash(token),email))
            # Email before commit: delivery failure leaves no invitation or agreement.
            link=url_for('renter_invitation_page', token=token, _external=True)
            msg=Message('NFH-HOA | Renter Registration Invitation',recipients=[email])
            msg.body=('You have been invited to create or connect your independent NFH-HOA renter account.\n'
                      'Open this private single-use link within 48 hours:\n'+link+'\n'
                      'Do not forward this invitation. HOA verification is required before property access.')
            send_mail(msg,'renter_invitation')
            conn.commit()
            return jsonify(status='success',message='Invitation email sent. Await renter acceptance and administrator verification.'),201
        except Exception:
            conn.rollback()
            app.logger.exception('Failed renter invitation')
            return _error('Unable to send renter invitation. No new invitation was committed.',503)
        finally:conn.close()

    @app.route('/renter/invitation/<token>',methods=['GET'])
    def renter_invitation_page(token):
        if len(token)>256:return _error('Invalid invitation',404)
        conn=get_db_connection()
        try:
            with conn.cursor() as cur:
                inv=invitation(cur,token)
            if not inv or inv['accepted_at'] is not None:
                return render_template('renter_invite.html',invalid=True,token=''),410
            return render_template('renter_invite.html',invalid=False,token=token, email=inv['email'],existing=bool(inv['account_user_id']))
        finally:conn.close()

    @app.route('/api/renter/accept-invitation',methods=['POST'])
    def renter_accept_invitation():
        data=request.get_json(silent=True) or {}
        token=data.get('token') or ''
        if not isinstance(token,str) or len(token)<30 or len(token)>256:return _error('Invalid invitation',400)
        conn=get_db_connection(autocommit=False)
        try:
            with conn.cursor() as cur:
                inv=invitation(cur,token,True)
                if not inv or inv['accepted_at'] is not None:return _error('Invitation is invalid, expired, or already used.',410)
                if inv['agreement_status']!='Pending':return _error('Agreement is not pending.',409)
                email=inv['email']
                if inv['account_user_id']:
                    if session.get('role')!='Renter' or int(session.get('user_id') or 0)!=int(inv['account_user_id']):
                        return _error('Sign in to the invited renter account before accepting.',403)
                    uid=inv['account_user_id']
                else:
                    if session.get('user_id'):return _error('Sign out before creating a renter account.',409)
                    if not registration_email_verified(email):return _error('Verify the invited email using the registration verification code first.',403)
                    first=(data.get('first_name') or '').strip(); last=(data.get('last_name') or '').strip()
                    username=(data.get('username') or '').strip(); password=data.get('password') or ''
                    phone=(data.get('phone') or '').strip()
                    if not all([first,last,username]) or len(password)<8 or not re.fullmatch(r'09\d{9}',phone):
                        return _error('Provide name, username, 11-digit mobile number, and password of at least 8 characters.')
                    cur.execute('''SELECT id FROM users WHERE LOWER(email)=%s OR LOWER(username)=%s LIMIT 1''',(email,username.lower()))
                    if cur.fetchone():return _error('Email or username already registered.',409)
                    cur.execute('''INSERT INTO users(first_name,last_name,email,username,mobile,password_hash,role,status,verification_status)
                                   VALUES (%s,%s,%s,%s,%s,%s,'Renter','Active','Verified')''',
                                (first,last,email,username,phone,generate_password_hash(password,method='pbkdf2:sha256')))
                    uid=cur.lastrowid
                    cur.execute('UPDATE nfh_renters SET account_user_id=%s WHERE id=%s',(uid,inv['renter_id']))
                cur.execute('UPDATE nfh_rental_agreements SET renter_acknowledged_at=UTC_TIMESTAMP() WHERE id=%s',(inv['agreement_id'],))
                cur.execute('UPDATE nfh_renter_invitations SET accepted_at=UTC_TIMESTAMP() WHERE id=%s',(inv['id'],))
            conn.commit()
            return jsonify(status='success',message='Invitation accepted. Homeowner acknowledgment and HOA verification are still required.'),200
        except IntegrityError:
            conn.rollback();return _error('Account or invitation conflict. Please contact the HOA office.',409)
        except Exception:
            conn.rollback();app.logger.exception('Renter invitation acceptance failed')
            return _error('Unable to complete renter registration.',503)
        finally:conn.close()

    @app.route('/api/renter/agreements/<int:agreement_id>/acknowledge',methods=['POST'])
    def renter_acknowledge(agreement_id):
        uid=current_user('Homeowner','Renter')
        if not uid:return _error('Not authorized',403)
        conn=get_db_connection(autocommit=False)
        try:
            with conn.cursor() as cur:
                cur.execute('''SELECT a.*,r.account_user_id FROM nfh_rental_agreements a
                               JOIN nfh_renters r ON r.id=a.renter_id WHERE a.id=%s FOR UPDATE''',(agreement_id,))
                a=cur.fetchone()
                if not a or a['verification_status']!='Pending':return _error('Agreement unavailable.',404)
                if session['role']=='Homeowner' and int(a['homeowner_id'])==int(uid) and owned(cur,a['property_id'],uid):
                    field='homeowner_acknowledged_at'
                elif session['role']=='Renter' and a['account_user_id'] and int(a['account_user_id'])==int(uid):
                    field='renter_acknowledged_at'
                else:return _error('Access denied',403)
                cur.execute('UPDATE nfh_rental_agreements SET '+field+'=UTC_TIMESTAMP() WHERE id=%s',(agreement_id,))
            conn.commit();return jsonify(status='success',message='Agreement acknowledged. Administrator approval is still required.')
        except Exception:
            conn.rollback();app.logger.exception('Agreement acknowledgment failed');return _error('Unable to acknowledge agreement.',503)
        finally:conn.close()

    @app.route('/api/homeowner/renter-agreements',methods=['GET'])
    def renter_agreements_owner():
        uid=current_user('Homeowner')
        if not uid:return _error('Not authorized',403)
        conn=get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute('''SELECT a.id,a.property_id,a.payer_type,a.starts_on,a.ends_on,a.verification_status,
                               a.homeowner_acknowledged_at,a.renter_acknowledged_at,r.full_name,p.property_code
                               FROM nfh_rental_agreements a
                               JOIN nfh_property_owners o ON o.property_id=a.property_id AND o.homeowner_id=a.homeowner_id
                               JOIN nfh_renters r ON r.id=a.renter_id
                               JOIN nfh_properties p ON p.id=a.property_id
                               WHERE a.homeowner_id=%s AND o.verified_at IS NOT NULL
                               AND o.effective_from<=CURDATE() AND (o.effective_to IS NULL OR o.effective_to>=CURDATE())
                               ORDER BY a.id DESC LIMIT 250''',(uid,))
                return jsonify(agreements=cur.fetchall())
        except Exception:
            app.logger.exception('Homeowner rental agreement listing failed');return _error('Agreements unavailable.',503)
        finally:conn.close()

    @app.route('/api/admin/renter-agreements',methods=['GET'])
    def renter_agreements_admin():
        if not current_user('Admin'):return _error('Not authorized',403)
        conn=get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute('''SELECT a.id,a.property_id,a.homeowner_id,a.renter_id,a.starts_on,a.ends_on,
                               a.payer_type,a.verification_status,a.homeowner_acknowledged_at,
                               a.renter_acknowledged_at,r.full_name,r.email,p.property_code
                               FROM nfh_rental_agreements a JOIN nfh_renters r ON r.id=a.renter_id
                               JOIN nfh_properties p ON p.id=a.property_id
                               ORDER BY a.id DESC LIMIT 250''')
                rows=cur.fetchall()
            return jsonify(agreements=rows)
        except Exception:
            app.logger.exception('Renter agreement list failed');return _error('Agreement records unavailable.',503)
        finally:conn.close()

    @app.route('/api/admin/renter-agreements/<int:agreement_id>/verify',methods=['POST'])
    def renter_admin_verify(agreement_id):
        if not current_user('Admin'):return _error('Not authorized',403)
        data=request.get_json(silent=True) or {}
        action=data.get('action')
        if action not in ('approve','reject'):return _error('Select approve or reject.')
        conn=get_db_connection(autocommit=False)
        try:
            with conn.cursor() as cur:
                cur.execute('''SELECT a.*,r.account_user_id FROM nfh_rental_agreements a
                               JOIN nfh_renters r ON r.id=a.renter_id WHERE a.id=%s FOR UPDATE''',(agreement_id,))
                a=cur.fetchone()
                if not a or a['verification_status']!='Pending':return _error('Agreement is not pending.',409)
                if action=='approve':
                    if not a['account_user_id'] or not a['homeowner_acknowledged_at'] or not a['renter_acknowledged_at']:
                        return _error('Both parties must acknowledge the agreement and the renter must register.',409)
                    if not owned(cur,a['property_id'],a['homeowner_id'],True):return _error('Ownership must be verified.',409)
                    cur.execute('''SELECT id FROM nfh_rental_agreements WHERE property_id=%s
                                   AND id<>%s AND verification_status='Verified'
                                   AND starts_on<=%s AND ends_on>=%s FOR UPDATE''',
                                (a['property_id'],a['id'],a['ends_on'],a['starts_on']))
                    if cur.fetchall():return _error('Another verified agreement overlaps this occupancy.',409)
                status='Verified' if action=='approve' else 'Rejected'
                cur.execute('''UPDATE nfh_rental_agreements SET verification_status=%s,verified_by=%s,
                               verified_at=IF(%s='Verified',UTC_TIMESTAMP(),NULL) WHERE id=%s''',
                            (status,session['user_id'],status,agreement_id))
                if action=='approve':
                    cur.execute("UPDATE nfh_renters SET verification_status='Verified',verified_by=%s,verified_at=UTC_TIMESTAMP() WHERE id=%s",(session['user_id'],a['renter_id']))
            conn.commit();return jsonify(status='success',message='Agreement '+status.lower()+'.')
        except Exception:
            conn.rollback();app.logger.exception('Renter agreement review failed');return _error('Unable to review renter agreement.',503)
        finally:conn.close()

    @app.route('/api/renter/eligible-services',methods=['GET'])
    def renter_eligible_services():
        if not current_user('Homeowner','Renter'):return _error('Not authorized',403)
        conn=get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute('''SELECT id,service_name FROM service_types WHERE status='Active' ORDER BY service_name''')
                return jsonify(services=cur.fetchall())
        except Exception:
            app.logger.exception('Renter service catalog unavailable');return _error('Services unavailable.',503)
        finally:conn.close()

    @app.route('/api/renter/agreements/<int:agreement_id>/services', methods=['GET','POST'])
    def renter_services(agreement_id):
        uid=current_user('Homeowner','Renter','Admin')
        if not uid:return _error('Not authorized',403)
        conn=get_db_connection(autocommit=request.method!='POST')
        try:
            with conn.cursor() as cur:
                cur.execute('''SELECT a.*,r.account_user_id FROM nfh_rental_agreements a
                               JOIN nfh_renters r ON r.id=a.renter_id WHERE a.id=%s''' + (' FOR UPDATE' if request.method=='POST' else ''),(agreement_id,))
                a=cur.fetchone()
                if not a:return _error('Agreement not found.',404)
                owner=session['role']=='Homeowner' and int(a['homeowner_id'])==int(uid) and owned(cur,a['property_id'],uid)
                renter=session['role']=='Renter' and a['account_user_id'] and int(a['account_user_id'])==int(uid)
                if not (owner or renter or session['role']=='Admin'):return _error('Property access denied.',403)
                if request.method=='POST':
                    if not owner:return _error('Only the verified property owner can change standing authorizations.',403)
                    data=request.get_json(silent=True) or {}
                    try:service_id=int(data.get('service_id'))
                    except (ValueError,TypeError):return _error('Invalid service ID.')
                    enabled=data.get('enabled')
                    if not isinstance(enabled,bool):return _error('Specify enabled as true or false.')
                    cur.execute("SELECT id FROM service_types WHERE id=%s AND status='Active'",(service_id,))
                    if not cur.fetchone():return _error('Service is unavailable.',404)
                    if a['verification_status']!='Verified' or not (a['starts_on']<=date.today()<=a['ends_on']):
                        return _error('Standing authorization requires a verified active agreement.',409)
                    if enabled:
                        cur.execute('''INSERT INTO nfh_agreement_service_authorizations(agreement_id,service_id,revoked_at)
                                       VALUES(%s,%s,NULL) ON DUPLICATE KEY UPDATE revoked_at=NULL''',(agreement_id,service_id))
                    else:
                        cur.execute('''UPDATE nfh_agreement_service_authorizations SET revoked_at=UTC_TIMESTAMP()
                                       WHERE agreement_id=%s AND service_id=%s''',(agreement_id,service_id))
                    conn.commit()
                    return jsonify(status='success',message='Standing authorization updated.')
                agreement_active=(a['verification_status']=='Verified' and
                                  a['starts_on']<=date.today()<=a['ends_on'] and
                                  a['effective_from']<=date.today())
                if not agreement_active and renter:
                    return jsonify(services=[],agreement_status=a['verification_status'])
                cur.execute('''SELECT s.service_id,t.service_name FROM nfh_agreement_service_authorizations s
                               JOIN service_types t ON t.id=s.service_id AND t.status='Active'
                               WHERE s.agreement_id=%s AND s.revoked_at IS NULL''',(agreement_id,))
                return jsonify(services=cur.fetchall(),agreement_status=a['verification_status'])
        except Exception:
            if request.method=='POST':conn.rollback()
            app.logger.exception('Renter service authorization failed')
            return _error('Service authorization unavailable.',503)
        finally:conn.close()

    @app.route('/api/admin/renter-agreements/<int:agreement_id>/terminate',methods=['POST'])
    def renter_terminate_agreement(agreement_id):
        if not current_user('Admin'):return _error('Not authorized',403)
        conn=get_db_connection(autocommit=False)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id,verification_status FROM nfh_rental_agreements WHERE id=%s FOR UPDATE",(agreement_id,))
                a=cur.fetchone()
                if not a or a['verification_status']!='Verified':return _error('Only verified agreements can be terminated.',409)
                cur.execute('''UPDATE nfh_rental_agreements SET verification_status='Revoked',revoked_at=UTC_TIMESTAMP()
                               WHERE id=%s''',(agreement_id,))
                cur.execute('''UPDATE nfh_agreement_service_authorizations SET revoked_at=UTC_TIMESTAMP()
                               WHERE agreement_id=%s AND revoked_at IS NULL''',(agreement_id,))
            conn.commit()
            return jsonify(status='success',message='Occupancy access and standing authorizations revoked. Financial history remains unchanged.')
        except Exception:
            conn.rollback();app.logger.exception('Agreement termination failed');return _error('Unable to terminate agreement.',503)
        finally:conn.close()

    @app.route('/api/renter/agreements',methods=['GET'])
    def renter_my_agreements():
        uid=current_user('Renter')
        if not uid:return _error('Not authorized',403)
        conn=get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute('''SELECT a.id,a.property_id,a.payer_type,a.starts_on,a.ends_on,a.verification_status,
                               a.homeowner_acknowledged_at,a.renter_acknowledged_at,p.property_code
                               FROM nfh_rental_agreements a
                               JOIN nfh_renters r ON r.id=a.renter_id
                               JOIN nfh_properties p ON p.id=a.property_id
                               WHERE r.account_user_id=%s AND a.verification_status IN ('Pending','Verified')
                               ORDER BY a.id DESC LIMIT 100''',(uid,))
                return jsonify(agreements=cur.fetchall())
        except Exception:
            app.logger.exception('Renter agreements unavailable');return _error('Agreements unavailable.',503)
        finally:conn.close()

    @app.route('/renter')
    def renter_portal():
        if not current_user('Renter'):return redirect(url_for('index'))
        return render_template('renter.html')

    @app.route('/api/renter/dashboard',methods=['GET'])
    def renter_dashboard():
        uid=current_user('Renter')
        if not uid:return _error('Not authorized',403)
        conn=get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute('''SELECT a.id agreement_id,a.property_id,a.starts_on,a.ends_on,
                               a.payer_type,p.property_code,p.block,p.lot,r.id renter_id
                               FROM nfh_rental_agreements a JOIN nfh_renters r ON r.id=a.renter_id
                               JOIN nfh_properties p ON p.id=a.property_id
                               WHERE r.account_user_id=%s AND r.verification_status='Verified'
                               AND a.verification_status='Verified' AND a.effective_from<=CURDATE()
                               AND a.starts_on<=CURDATE() AND a.ends_on>=CURDATE()
                               ORDER BY a.id DESC LIMIT 5''',(uid,))
                agreements=cur.fetchall()
                for a in agreements:
                    cur.execute('''SELECT d.billing_period,d.amount_due,d.payer_type,
                                   COALESCE(SUM(CASE WHEN r.voided_at IS NULL THEN r.amount ELSE 0 END),0) amount_paid
                                   FROM nfh_property_monthly_dues d
                                   LEFT JOIN nfh_property_due_receipts r ON r.obligation_id=d.id
                                   WHERE d.property_id=%s AND d.payer_type='Renter' AND d.responsible_payer_id=%s
                                   AND d.rental_agreement_id=%s
                                   GROUP BY d.id,d.billing_period,d.amount_due,d.payer_type
                                   ORDER BY d.billing_period DESC LIMIT 60''',(a['property_id'],a['renter_id'],a['agreement_id']))
                    a['assigned_dues']=cur.fetchall()
                    for d in a['assigned_dues']:
                        d['outstanding_balance']=str(max(0,d['amount_due']-d['amount_paid']))
                        d['amount_due']=str(d['amount_due']);d['amount_paid']=str(d['amount_paid'])
                return jsonify(agreements=agreements)
        except Exception:
            app.logger.exception('Renter dashboard unavailable');return _error('Renter property information unavailable. Check migration status.',503)
        finally:conn.close()
