import unittest
from datetime import date
from unittest.mock import patch
from dues_automation import generate_bills, payment_state

class FakeCursor:
    def __init__(self, db): self.db=db;self.rowcount=0;self.result=None
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execute(self,sql,params=None):
        self.rowcount=0
        if 'FROM fees' in sql:self.result=[{'amount':'100.00'}]
        elif 'FROM users' in sql:self.result=self.db.users
        elif 'INSERT IGNORE INTO monthly_dues' in sql:
            key=params[:2]
            if key not in self.db.bills:self.db.bills[key]=params[2];self.rowcount=1
    def fetchone(self):return self.result[0] if self.result else None
    def fetchall(self):return self.result
class FakeDB:
    def __init__(self):self.users=[{'id':7,'created_at':date(2026,1,16)}];self.bills={};self.commits=0
    def cursor(self):return FakeCursor(self)
    def commit(self):self.commits+=1

class BillingScheduleTests(unittest.TestCase):
    def test_first_of_month_and_idempotency(self):
        db=FakeDB()
        self.assertEqual(generate_bills(db,through=date(2026,3,1)),3)
        self.assertEqual(generate_bills(db,through=date(2026,3,1)),0)
        self.assertIn((7,date(2026,3,1)),db.bills)
    def test_catchup(self):
        db=FakeDB();generate_bills(db,through=date(2026,2,1))
        self.assertEqual(generate_bills(db,through=date(2026,4,1)),2)
        self.assertEqual(len(db.bills),4)
    def test_preserves_existing_amounts_and_advance(self):
        db=FakeDB();db.bills[(7,date(2026,2,1))]='55.00'
        generate_bills(db,through=date(2026,3,1))
        self.assertEqual(db.bills[(7,date(2026,2,1))],'55.00')
    def test_deadline_kept_separate(self):
        self.assertEqual(payment_state(date(2026,10,1),100,0,date(2026,10,1)),'Unpaid')
        self.assertEqual(payment_state(date(2026,10,1),100,0,date(2026,10,5)),'Unpaid')
        self.assertEqual(payment_state(date(2026,10,1),100,0,date(2026,10,6)),'Overdue')
    def test_future_protection(self):
        with self.assertRaises(ValueError):generate_bills(FakeDB(),through=date(2099,1,1))
if __name__=='__main__':unittest.main()
