"""B12-12..19: source-backed officer work queue (staging integration).

Tasks are projections of existing authoritative records. This module never posts a
payment, approves property claims or bypasses request routing. Delegations not
already authorized in the legacy app remain disabled.
"""
from flask import request, session, jsonify
from datetime import datetime

OFFICER_ROLES = ('Admin','Secretary','Treasurer','President','Vice President','Board Director')
DONE_REQUESTS = ('Issued / Completed', 'Rejected', 'Cancelled')


def task_visibility(role, task):
    """Fail closed: only assigned role can view; Admin audits all tasks."""
    return role == 'Admin' or role == task.get('assigned_role')


def derive_task_state(source_type, source_status):
    if source_type == 'Property Claim':
        return 'Completed' if source_status in ('Verified','Rejected') else 'Escalated' if source_status == 'Disputed' else 'Pending'
    if source_type == 'Request Concern':
        return 'Completed' if source_status in ('Responded','Resolved') else 'Pending'
    if source_type == 'Document Request':
        return 'Completed' if source_status in DONE_REQUESTS else 'Pending'
    return 'Pending'


def register_officer_task_routes(app, connect):
    def fail(message, code):
        return jsonify(error=message), code

    def authenticate():
        return session.get('user_id') and session.get('role') in OFFICER_ROLES

    def sync_tasks(cur):
        # Idempotent projections; only the currently authorized workflow owner
        # is assigned. Property claim review is Admin-only until HOA delegation.
        cur.execute("""INSERT IGNORE INTO nfh_officer_tasks
          (source_type,source_id,task_type,assigned_role,priority,created_at,due_at,source_link)
          SELECT 'Property Claim',CAST(id AS CHAR),'Property Verification','Admin',
          IF(status='Disputed','High','Normal'),created_at,
          DATE_ADD(created_at,INTERVAL 5 DAY),'/admin/property-claims'
          FROM nfh_property_claims""")
        cur.execute("""INSERT IGNORE INTO nfh_officer_tasks
          (source_type,source_id,task_type,assigned_role,priority,created_at,due_at,source_link)
          SELECT 'Request Concern',CAST(id AS CHAR),'Concern Review',assigned_role,
          'Normal',created_at,DATE_ADD(created_at,INTERVAL 5 DAY),'/officer#concerns'
          FROM request_concerns WHERE assigned_role IN ('Secretary','Treasurer')""")
        # Respect the request's existing assigned reviewer. No new approver is inferred.
        cur.execute("""INSERT IGNORE INTO nfh_officer_tasks
          (source_type,source_id,task_type,assigned_role,priority,created_at,due_at,source_link)
          SELECT 'Document Request',id,'Document Request Review',assigned_officer,
          'Normal',date_submitted,DATE_ADD(date_submitted,INTERVAL 5 DAY),
          CASE WHEN assigned_officer='Treasurer' THEN '/officer#treasurer-checking'
               ELSE '/officer#assigned' END
          FROM requests WHERE assigned_officer IN ('Secretary','Treasurer')""")
        # Never complete a task independently of its authoritative source status.
        cur.execute("""UPDATE nfh_officer_tasks t
            JOIN nfh_property_claims c ON t.source_type='Property Claim' AND t.source_id=CAST(c.id AS CHAR)
            SET t.status=CASE WHEN c.status IN ('Verified','Rejected') THEN 'Completed'
                               WHEN c.status='Disputed' THEN 'Escalated'
                               ELSE 'Pending' END,
                t.completed_at=IF(c.status IN ('Verified','Rejected'),COALESCE(t.completed_at,NOW()),NULL),
                t.priority=IF(c.status='Disputed','High',t.priority)
            WHERE t.status <> CASE WHEN c.status IN ('Verified','Rejected') THEN 'Completed'
                              WHEN c.status='Disputed' THEN 'Escalated' ELSE 'Pending' END""")
        cur.execute("""UPDATE nfh_officer_tasks t
            JOIN request_concerns c ON t.source_type='Request Concern' AND t.source_id=CAST(c.id AS CHAR)
            SET t.status=IF(c.status IN ('Responded','Resolved'),'Completed','Pending'),
                t.completed_at=IF(c.status IN ('Responded','Resolved'),COALESCE(t.completed_at,NOW()),NULL)
            WHERE t.status<>IF(c.status IN ('Responded','Resolved'),'Completed','Pending')""")
        cur.execute("""UPDATE nfh_officer_tasks t
            JOIN requests r ON t.source_type='Document Request' AND t.source_id=r.id
            SET t.status=IF(r.status IN ('Issued / Completed','Rejected','Cancelled'),'Completed','Pending'),
                t.completed_at=IF(r.status IN ('Issued / Completed','Rejected','Cancelled'),COALESCE(t.completed_at,NOW()),NULL)
            WHERE t.status<>IF(r.status IN ('Issued / Completed','Rejected','Cancelled'),'Completed','Pending')""")

    @app.route('/api/officer/my-tasks', methods=['GET'])
    def officer_my_tasks():
        if not authenticate(): return fail('Unauthorized officer session.',403)
        role=session['role']; uid=int(session['user_id'])
        q=(request.args.get('q') or '').strip()[:100]
        status=(request.args.get('status') or '').strip()
        typ=(request.args.get('type') or '').strip()
        priority=(request.args.get('priority') or '').strip()
        if status and status not in ('Pending','In Progress','Completed','Escalated','Awaiting Information','Canceled'):return fail('Invalid status.',400)
        if priority and priority not in ('Normal','High','Urgent'):return fail('Invalid priority.',400)
        try: page=max(1,min(int(request.args.get('page',1)),100000)); size=int(request.args.get('size',10))
        except (TypeError,ValueError): return fail('Invalid pagination.',400)
        if size not in (10,25,50):return fail('Invalid page size.',400)
        conn=None
        try:
            conn=connect(autocommit=False)
            with conn.cursor() as cur:
                sync_tasks(cur)
                where=['1=1']; params=[]
                # Role scoped even if caller alters query-string arguments.
                if role!='Admin':
                    where.append('t.assigned_role=%s AND (t.assigned_user_id IS NULL OR t.assigned_user_id=%s)')
                    params.extend((role,uid))
                if q:where.append('(t.source_id LIKE %s OR t.task_type LIKE %s OR t.source_type LIKE %s)');params.extend(('%'+q+'%',)*3)
                if status:where.append('t.status=%s');params.append(status)
                if typ:where.append('t.source_type=%s');params.append(typ)
                if priority:where.append('t.priority=%s');params.append(priority)
                clause=' AND '.join(where)
                cur.execute('SELECT COUNT(*) AS total FROM nfh_officer_tasks t WHERE '+clause,params)
                total=cur.fetchone()['total']
                page=min(page,max(1,(total+size-1)//size))
                cur.execute('''SELECT t.id,t.source_type,t.source_id,t.task_type,t.assigned_role,t.priority,
                    t.status,t.created_at,t.due_at,t.completed_at,t.source_link,
                    t.assigned_user_id,t.escalation_reason
                    FROM nfh_officer_tasks t WHERE '''+clause+'''
                    ORDER BY (t.status='Completed') ASC,
                      (t.due_at IS NULL) ASC,t.due_at ASC,t.id DESC LIMIT %s OFFSET %s''',
                    params+[size,(page-1)*size])
                rows=cur.fetchall()
                # Counters scoped to this user's permitted queue; not just current search.
                base='1=1'; baseparams=[]
                if role!='Admin':base='assigned_role=%s AND (assigned_user_id IS NULL OR assigned_user_id=%s)';baseparams=[role,uid]
                cur.execute('''SELECT
                    SUM(status='Pending') pending,SUM(status='In Progress') in_progress,
                    SUM(priority IN ('High','Urgent') AND status<>'Completed') high_priority,
                    SUM(due_at<NOW() AND status NOT IN ('Completed','Canceled')) overdue,
                    SUM(status='Completed') completed
                    FROM nfh_officer_tasks WHERE '''+base,baseparams)
                counters={k:int(v or 0) for k,v in cur.fetchone().items()}
            conn.commit()
            for row in rows:
                for k in ('created_at','due_at','completed_at'):
                    if row.get(k):row[k]=row[k].isoformat(sep=' ',timespec='minutes')
            return jsonify(tasks=rows,total=total,page=page,size=size,counters=counters)
        except Exception:
            if conn:conn.rollback()
            app.logger.exception('Officer task queue unavailable')
            return fail('Task queue unavailable. Apply the B12 task migration in staging.',503)
        finally:
            if conn:conn.close()

    @app.route('/api/officer/workload',methods=['GET'])
    def officer_workload():
        if not authenticate() or session.get('role') not in ('Vice President','Admin'):
            return fail('Workload dashboard restricted.',403)
        conn=None
        try:
            conn=connect(autocommit=False)
            with conn.cursor() as cur:
                sync_tasks(cur)
                cur.execute('''SELECT assigned_role,
                    COUNT(*) total,SUM(status='Pending') pending,
                    SUM(status='In Progress') in_progress,
                    SUM(status='Completed') completed,
                    SUM(status NOT IN ('Completed','Canceled') AND due_at<NOW()) overdue,
                    SUM(status='Escalated') escalated
                    FROM nfh_officer_tasks GROUP BY assigned_role ORDER BY assigned_role''')
                results=cur.fetchall()
            conn.commit()
            return jsonify(workload=results,delegation_enabled=False)
        except Exception:
            if conn:conn.rollback()
            app.logger.exception('Officer workload unavailable')
            return fail('Workload records unavailable.',503)
        finally:
            if conn:conn.close()
