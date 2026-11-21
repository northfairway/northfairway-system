"""Independent delinquency mail worker. Run with --once from cron every minute.

Run with --loop for checks every 60 seconds. Successful sends have a
configurable 3-calendar-month default cooldown. No browser session required.
"""
import argparse
import os
import time
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

MANILA = ZoneInfo("Asia/Manila")


def add_calendar_months(value, months):
    """Calendar-month addition with end-of-month clamping."""
    import calendar
    from datetime import datetime
    index = value.year * 12 + value.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def next_reminder_date(value, frequency, unit):
    from datetime import timedelta
    if unit == 'months':
        return add_calendar_months(value, frequency)
    return value + timedelta(days=frequency * (7 if unit == 'weeks' else 1))


def read_policy(cursor):
    cursor.execute("SELECT setting_key,setting_value FROM hoa_settings WHERE setting_key IN (%s,%s,%s,%s,%s)",
                   ('delinquency_email_enabled','delinquency_unpaid_months','delinquency_email_frequency_value',
                    'delinquency_email_frequency_unit','delinquency_email_config_updated_at'))
    settings = {r['setting_key']: r['setting_value'] for r in cursor.fetchall()}
    frequency = int(settings.get('delinquency_email_frequency_value') or 3)
    unit = settings.get('delinquency_email_frequency_unit') or 'months'
    if unit not in ('days','weeks','months') or not 1 <= frequency <= 365:
        raise ValueError('Invalid delinquency email frequency configuration')
    return (str(settings.get('delinquency_email_enabled','1')) == '1',
            max(1,int(settings.get('delinquency_unpaid_months') or 5)),frequency,unit)


def eligible_months(rows, today):
    """Return months with actual remaining balance, excluding future obligations."""
    unpaid = []
    for row in rows:
        month = row["due_month"]
        if month > today:
            continue
        if row["status"] == "Adjusted":
            continue
        # Older legacy Paid records may not have separate allocation rows.
        allocated = Decimal(str(row["allocated"] or 0))
        amount = Decimal(str(row["amount"]))
        balance = Decimal("0") if row["status"] == "Paid" else max(Decimal("0"), amount - allocated)
        if balance > 0:
            unpaid.append((month, balance))
    return unpaid


def run_once(*, now=None, mail_sender=None, connection_factory=None):
    """Return counts; a database unique claim prevents duplicate sends per interval.

    A failed SMTP send is logged as Failed. A crashed worker leaves a Pending
    claim, which intentionally suppresses duplicates until the next interval.
    """
    from app import app, get_db_connection, mail, Message
    current = now or __import__("datetime").datetime.now(MANILA)
    today = current.astimezone(MANILA).date()
    bucket = int(current.timestamp()) // 60  # Atomic per-minute claim; cooldown is calendar-based.
    factory = connection_factory or get_db_connection
    counts = {"evaluated": 0, "delinquent": 0, "sent": 0, "failed": 0, "skipped": 0}
    with app.app_context():
        db = factory(autocommit=False)
        try:
            with db.cursor() as c:
                enabled, threshold, frequency, unit = read_policy(c)
                c.execute("""SELECT id, first_name, last_name, email FROM users
                             WHERE role='Homeowner' AND status='Active' ORDER BY id""")
                users = c.fetchall()
            db.commit()
            if not enabled:
                return counts
            for user in users:
                counts["evaluated"] += 1
                with db.cursor() as c:
                    c.execute("""SELECT d.due_month,d.amount,d.status,
                                      COALESCE(SUM(CASE WHEN p.voided_at IS NULL THEN a.amount ELSE 0 END),0) AS allocated
                               FROM monthly_dues d
                               LEFT JOIN monthly_dues_allocations a ON a.monthly_due_id=d.id
                               LEFT JOIN monthly_dues_payments p ON p.id=a.payment_id
                               WHERE d.user_id=%s AND d.due_month<=%s
                               GROUP BY d.id,d.due_month,d.amount,d.status
                               ORDER BY d.due_month""", (user["id"], today))
                    unpaid = eligible_months(c.fetchall(), today)
                months = len(unpaid)
                balance = sum((v for _, v in unpaid), Decimal("0"))
                if months < threshold or balance <= 0 or not (user.get("email") or "").strip():
                    counts["skipped"] += 1
                    continue
                counts["delinquent"] += 1
                subject = "North Fairway Homes HOA — Monthly Dues Reminder"
                name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip()
                body = (f"Dear {name},\n\nOur records show {months} unpaid monthly dues periods "
                        f"with an outstanding balance of PHP {balance:,.2f}.\n"
                        "Please contact the HOA Treasurer to review your account and settle dues "
                        "face-to-face at the HOA office. If you have recently paid, please "
                        "contact the Treasurer for verification.\n\nNorth Fairway Homes HOA")
                # Use the last successful submission timestamp, never the most
                # recent failed attempt or an interval bucket.
                with db.cursor() as c:
                    c.execute("""SELECT completed_at FROM delinquency_email_reminders
                                 WHERE user_id=%s AND status='Sent' AND completed_at IS NOT NULL
                                 ORDER BY completed_at DESC LIMIT 1""", (user['id'],))
                    last = c.fetchone()
                if last and last.get('completed_at'):
                    last_at = last['completed_at']
                    # Database DATETIME values are in the configured DB/server timezone.
                    # Deployment must set MySQL session timezone to Asia/Manila.
                    if next_reminder_date(last_at, frequency, unit) > current.replace(tzinfo=None):
                        counts['skipped'] += 1
                        continue
                interval = 60
                # Insert an atomic unique claim BEFORE SMTP. A concurrent worker
                # sees duplicate-key and cannot send the same interval's email.
                try:
                    with db.cursor() as c:
                        c.execute("""INSERT INTO delinquency_email_reminders
                                     (user_id,interval_bucket,interval_seconds,status)
                                     VALUES (%s,%s,%s,'Pending')""", (user["id"], bucket, interval))
                        reminder_id = c.lastrowid
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    if getattr(exc, "args", [None])[0] == 1062:
                        counts["skipped"] += 1
                        continue
                    raise
                error = None
                try:
                    if not app.config.get("MAIL_SERVER") and mail_sender is None:
                        raise RuntimeError("SMTP sender is not configured")
                    if mail_sender:
                        mail_sender(user["email"], subject, body)
                    else:
                        msg = Message(subject, recipients=[user["email"]])
                        msg.body = body
                        mail.send(msg)
                    counts["sent"] += 1
                    status = "Sent"
                except Exception as exc:
                    error = f"{type(exc).__name__}: {str(exc)[:350]}"
                    status = "Failed"
                    counts["failed"] += 1
                    app.logger.warning("Delinquency reminder delivery failed for user id %s", user["id"])
                with db.cursor() as c:
                    c.execute("""UPDATE delinquency_email_reminders SET status=%s,last_error=%s,
                                 completed_at=NOW() WHERE id=%s""", (status,error,reminder_id))
                    c.execute("""INSERT INTO notification_log
                                 (user_id,channel,subject,body,recipient,related_type,related_id,dedupe_key,status)
                                 VALUES (%s,'Email',%s,%s,%s,'Delinquency',%s,%s,%s)""",
                              (user["id"],subject,body,user["email"],str(reminder_id),
                               f"delinq:{user['id']}:{bucket}",status))
                    c.execute("""INSERT INTO audit_logs(username,role,action,item,new_val)
                                 VALUES (%s,'System','Delinquency Email Reminder',%s,%s)""",
                              ("scheduler",str(user["id"]),status))
                db.commit()
            return counts
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run one scheduled cycle")
    parser.add_argument("--loop", action="store_true", help="Run continuously (single worker only)")
    args = parser.parse_args()
    if not (args.once or args.loop):
        parser.error("Specify --once or --loop")
    while True:
        try:
            print(run_once(), flush=True)
        except Exception as exc:
            print(f"Delinquency job failed: {type(exc).__name__}: {exc}", flush=True)
            if args.once:
                raise
        if not args.loop:
            break
        time.sleep(60)
