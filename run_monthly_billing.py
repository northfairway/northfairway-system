"""Run daily at 08:00 Asia/Manila. The 1st bills the new month; subsequent runs safely catch up.

Schedule this once per day (not only on the first) so missed schedules recover.
The unique (user_id, due_month) index plus INSERT IGNORE makes repeats safe.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from app import get_db_connection
from dues_automation import generate_bills

if __name__ == '__main__':
    connection = get_db_connection(autocommit=False)
    try:
        inserted = generate_bills(connection)
        print(f'{datetime.now(ZoneInfo("Asia/Manila")).isoformat()} | Newly created monthly dues: {inserted}')
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
