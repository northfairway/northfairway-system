"""B12-11: first-time claim intake and controlled HOA review.

Important: claims are not ownership or occupancy authority. An occupancy claim
never grants financial/request access. The legacy billing engine is unchanged.
"""
import re
from flask import request, session, jsonify, render_template, redirect, url_for
from werkzeug.security import generate_password_hash
from pymysql import IntegrityError

EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
LOCATION = re.compile(r'^[\w\- /]{1,50}$', re.UNICODE)


def normalize_claim(item):
    if not isinstance(item, dict):
        raise ValueError('Enter a property block and lot.')
    block = str(item.get('block') or '').strip().upper()
    lot = str(item.get('lot') or '').strip().upper()
    evidence = str(item.get('evidence_note') or '').strip()
    if not LOCATION.fullmatch(block) or not LOCATION.fullmatch(lot) or len(evidence) > 500:
        raise ValueError('Enter valid Block/Lot and supporting evidence details (500 characters maximum).')
    return block, lot, evidence


def save_claim(cur, user_id, claim_type, block, lot, evidence):
    # Claimant never receives property data from this public lookup. Admin resolves identities.
    cur.execute('''INSERT INTO nfh_property_claims
      (claimant_user_id,claim_type,block,lot,evidence_note,status)
      VALUES (%s,%s,%s,%s,%s,'Pending')
      ON DUPLICATE KEY UPDATE evidence_note=VALUES(evidence_note),
        status=IF(status='Rejected','Pending',status)''',
      (user_id,claim_type,block,lot,evidence or None))
    if claim_type == 'Ownership':
        # Conflicts are held for administrator review; no verified title changes.
        cur.execute("""SELECT id FROM nfh_property_claims WHERE claim_type='Ownership'
            AND subdivision='North Fairway Homes' AND block=%s AND lot=%s
            AND claimant_user_id<>%s AND status IN ('Pending','Verified','Disputed') FOR UPDATE""",
            (block,lot,user_id))
        if cur.fetchall():
            cur.execute("""UPDATE nfh_property_claims SET status='Disputed'
                WHERE claim_type='Ownership' AND subdivision='North Fairway Homes'
                AND block=%s AND lot=%s AND status='Pending'""",(block,lot))


def register_enrollment_routes(app, connect, email_verified):
    def error(msg, status=400): return jsonify(status='error',message=msg),status

    @app.route('/register/renter')
    def renter_self_enroll_page():
        return render_template('renter_self_register.html')

    @app.route('/api/enrollment/renter',methods=['POST'])
    def renter_self_enroll():
        """Independent renter account creation, without property privileges."""
        if session.get('user_id'): return error('Sign out to create a new account.',409)
        data=request.get_json(silent=True) or {}
        email=str(data.get('email') or '').strip().lower()
        first=str(data.get('first_name') or '').strip()
        last=str(data.get('last_name') or '').strip()
        username=str(data.get('username') or '').strip()
        phone=str(data.get('phone') or '').strip()
        password=data.get('password') or ''
        if (not EMAIL.fullmatch(email) or len(email)>150 or len(first)<1 or len(first)>100
            or len(last)<1 or len(last)>100 or not re.fullmatch(r'[\w.-]{3,80}',username)
            or not re.fullmatch(r'09\d{9}',phone) or len(password)<8
            or password!=data.get('password_confirm')):
            return error('Check your account information, matching passwords, and mobile number.')
        try: block,lot,evidence=normalize_claim(data)
        except ValueError as exc:return error(str(exc))
        if not email_verified(email):return error('Verify your email before registering.',403)
        conn=connect(autocommit=False)
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT id FROM users WHERE LOWER(email)=%s OR LOWER(username)=%s LIMIT 1', (email,username.lower()))
                if cur.fetchone():return error('An account already uses these credentials.',409)
                cur.execute('''INSERT INTO users(first_name,last_name,email,username,mobile,password_hash,role,status,verification_status)
                     VALUES (%s,%s,%s,%s,%s,%s,'Renter','Active','Verified')''',
                     (first,last,email,username,phone,generate_password_hash(password,method='pbkdf2:sha256')))
                uid=cur.lastrowid
                # Reuse pending invite identity, so invitation acceptance links to this account.
                cur.execute("SELECT id FROM nfh_renters WHERE LOWER(email)=%s AND account_user_id IS NULL ORDER BY id LIMIT 1 FOR UPDATE",(email,))
                pending=cur.fetchone()
                if pending:
                    cur.execute("UPDATE nfh_renters SET account_user_id=%s,mobile=%s WHERE id=%s",(uid,phone,pending['id']))
                else:
                    cur.execute("INSERT INTO nfh_renters(full_name,email,mobile,verification_status,account_user_id) VALUES (%s,%s,%s,'Pending',%s)",
                                (first+' '+last,email,phone,uid))
                save_claim(cur,uid,'Occupancy',block,lot,evidence)
            conn.commit()
            return jsonify(status='success',message='Email-verified account created. Your occupancy claim is pending HOA verification; no property access has been granted.'),201
        except IntegrityError:
            conn.rollback();return error('Account or property claim conflict. Contact HOA verification.',409)
        except Exception:
            conn.rollback();app.logger.exception('Renter self-enrollment failed')
            return error('Unable to complete enrollment. Verify the B12-11 database migration.',503)
        finally:conn.close()

    @app.route('/api/enrollment/my-claims',methods=['GET','POST'])
    def user_claims():
        uid=session.get('user_id')
        if not uid or session.get('role') not in ('Homeowner','Renter'):return error('Sign in with a resident account.',403)
        conn=connect(autocommit=request.method=='GET')
        try:
            with conn.cursor() as cur:
                if request.method=='POST':
                    d=request.get_json(silent=True) or {}
                    try:block,lot,evidence=normalize_claim(d)
                    except ValueError as exc:return error(str(exc))
                    typ='Ownership' if session['role']=='Homeowner' else 'Occupancy'
                    save_claim(cur,uid,typ,block,lot,evidence)
                    conn.commit()
                    return jsonify(status='success',message='Claim submitted for HOA review. No property access or monthly dues were generated.'),201
                cur.execute('''SELECT id,claim_type,block,lot,status,created_at,review_note FROM nfh_property_claims
                               WHERE claimant_user_id=%s ORDER BY id DESC LIMIT 100''',(uid,))
                return jsonify(claims=cur.fetchall())
        except Exception:
            if request.method=='POST':conn.rollback()
            app.logger.exception('Resident property claims unavailable')
            return error('Property claims unavailable.',503)
        finally:conn.close()

    @app.route('/admin/property-claims')
    def property_claims_page():
        if session.get('role')!='Admin':return redirect(url_for('index'))
        return render_template('property_claims_admin.html')

    @app.route('/api/admin/property-claims')
    def admin_claims():
        if session.get('role')!='Admin':return error('Not authorized',403)
        conn=connect()
        try:
            with conn.cursor() as cur:
                cur.execute('''SELECT c.id,c.claim_type,c.block,c.lot,c.status,c.evidence_note,c.created_at,
                                  u.first_name,u.last_name,u.email,u.role,
                                  (SELECT COUNT(*) FROM nfh_property_claims z
                                   WHERE z.block=c.block AND z.lot=c.lot AND z.subdivision=c.subdivision
                                   AND z.claim_type='Ownership' AND z.claimant_user_id<>c.claimant_user_id
                                   AND z.status IN ('Pending','Verified','Disputed')) AS conflicting_owners
                               FROM nfh_property_claims c JOIN users u ON u.id=c.claimant_user_id
                               ORDER BY FIELD(c.status,'Disputed','Pending','Verified','Rejected'),c.id DESC LIMIT 500''')
                return jsonify(claims=cur.fetchall())
        except Exception:
            app.logger.exception('Property claims review listing unavailable')
            return error('Unable to load claims.',503)
        finally:conn.close()

    @app.route('/api/admin/property-registry',methods=['POST'])
    def admin_create_verified_registry_property():
        if session.get('role')!='Admin':return error('Not authorized',403)
        data=request.get_json(silent=True) or {}
        try:block,lot,_=normalize_claim(data)
        except ValueError as exc:return error(str(exc))
        from datetime import date
        try:start=date.fromisoformat(str(data.get('billing_start') or ''))
        except ValueError:return error('Set an HOA-verified billing start date.')
        note=str(data.get('verification_note') or '').strip()
        if len(note)<12 or len(note)>500:return error('Record the HOA verification reference (12–500 characters).')
        conn=connect(autocommit=False)
        import hashlib,secrets
        lockname='nfh-registry-'+hashlib.sha256((block+':'+lot).encode()).hexdigest()[:32]
        locked=False
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT GET_LOCK(%s,5) AS acquired',(lockname,))
                locked=bool(cur.fetchone()['acquired'])
                if not locked:return error('Another registry update is in progress.',409)
                cur.execute("""SELECT id FROM nfh_properties WHERE subdivision='North Fairway Homes'
                               AND UPPER(TRIM(block))=%s AND UPPER(TRIM(lot))=%s""",(block,lot))
                if cur.fetchall():return error('Property already registered or requires duplicate reconciliation.',409)
                code='NFH-'+secrets.token_hex(12).upper()
                cur.execute("""INSERT INTO nfh_properties(property_code,block,lot,billing_start,status)
                               VALUES (%s,%s,%s,%s,'Inactive')""",(code,block,lot,start))
                property_id=cur.lastrowid
                cur.execute("""INSERT INTO audit_logs(username,role,action,item,prev_val,new_val)
                               VALUES (%s,'Admin','Create Inactive Property Registry',%s,'Not Registered',%s)""",
                            (session.get('username') or str(session['user_id']),code,
                             'Block '+block+' Lot '+lot+'; Verified source: '+note))
            conn.commit()
            return jsonify(status='success',property_id=property_id,message='Inactive registry property created. No owner assigned and no dues generated.'),201
        except Exception:
            conn.rollback();app.logger.exception('Registry property creation failed')
            return error('Unable to create registry property.',503)
        finally:
            if locked:
                try:
                    with conn.cursor() as cur:cur.execute('SELECT RELEASE_LOCK(%s)',(lockname,))
                except Exception:pass
            conn.close()

    @app.route('/api/admin/property-claims/<int:claim_id>/review',methods=['POST'])
    def admin_review_claim(claim_id):
        if session.get('role')!='Admin':return error('Not authorized',403)
        data=request.get_json(silent=True) or {}
        decision=data.get('decision')
        note=str(data.get('note') or '').strip()
        if decision not in ('verify','reject','dispute') or len(note)<8 or len(note)>500:
            return error('Provide a decision and verification note (8–500 characters).')
        conn=connect(autocommit=False)
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM nfh_property_claims WHERE id=%s FOR UPDATE',(claim_id,))
                claim=cur.fetchone()
                if not claim or claim['status'] not in ('Pending','Disputed'):
                    return error('Claim is not available for review.',409)
                status={'verify':'Verified','reject':'Rejected','dispute':'Disputed'}[decision]
                prop_id=None
                if decision=='verify':
                    cur.execute('''SELECT id FROM nfh_properties WHERE subdivision=%s AND UPPER(TRIM(block))=%s
                                   AND UPPER(TRIM(lot))=%s FOR UPDATE''',
                                (claim['subdivision'],claim['block'],claim['lot']))
                    props=cur.fetchall()
                    if len(props)!=1:return error('Property registry must have exactly one HOA-validated match. Resolve duplicates or create the verified registry entry first.',409)
                    prop_id=props[0]['id']
                    if claim['claim_type']=='Ownership':
                        cur.execute('''SELECT id,homeowner_id FROM nfh_property_owners WHERE property_id=%s
                                       AND verified_at IS NOT NULL AND (effective_to IS NULL OR effective_to>=CURDATE()) FOR UPDATE''',(prop_id,))
                        owners=cur.fetchall()
                        if any(int(r['homeowner_id'])!=int(claim['claimant_user_id']) for r in owners):
                            return error('Conflicting verified ownership. Requires manual ownership-resolution procedure.',409)
                        cur.execute('''SELECT id FROM nfh_property_claims WHERE claim_type='Ownership' AND id<>%s
                                       AND subdivision=%s AND block=%s AND lot=%s AND status IN ('Pending','Disputed','Verified') FOR UPDATE''',
                                    (claim_id,claim['subdivision'],claim['block'],claim['lot']))
                        if cur.fetchall():return error('Conflicting ownership claims must be resolved before approval.',409)
                        cur.execute('''SELECT id FROM nfh_property_owners WHERE property_id=%s AND homeowner_id=%s LIMIT 1 FOR UPDATE''',
                                    (prop_id,claim['claimant_user_id']))
                        if not cur.fetchone():
                            cur.execute('''INSERT INTO nfh_property_owners(property_id,homeowner_id,effective_from,verified_at,verified_by)
                                           VALUES (%s,%s,CURDATE(),UTC_TIMESTAMP(),%s)''',
                                        (prop_id,claim['claimant_user_id'],session['user_id']))
                    else:
                        # This decision verifies evidence only; it DOES NOT activate occupancy.
                        # A separate homeowner-renter agreement with both acknowledgments must be approved.
                        cur.execute('''SELECT id FROM nfh_property_owners WHERE property_id=%s AND verified_at IS NOT NULL
                                       AND (effective_to IS NULL OR effective_to>=CURDATE()) FOR UPDATE''',(prop_id,))
                        if len(cur.fetchall())!=1:return error('Verify unique property ownership before reviewing occupancy.',409)
                cur.execute('''UPDATE nfh_property_claims SET status=%s,property_id=%s,review_note=%s,
                               reviewed_by=%s,reviewed_at=UTC_TIMESTAMP() WHERE id=%s''',
                            (status,prop_id,note,session['user_id'],claim_id))
                cur.execute('''INSERT INTO nfh_property_claim_reviews(claim_id,reviewer_id,previous_status,new_status,decision_note)
                               VALUES (%s,%s,%s,%s,%s)''',
                            (claim_id,session['user_id'],claim['status'],status,note))
            conn.commit()
            return jsonify(status='success',message='Claim reviewed. Occupancy access still requires an approved agreement; no billing was created.')
        except Exception:
            conn.rollback();app.logger.exception('Property claim verification failed')
            return error('Unable to review claim.',503)
        finally:conn.close()
