import unittest
from decimal import Decimal
from datetime import date
from treasurer_financial import money, period, validate

class Cursor:
    def execute(self, sql, args):
        self.sql=sql;self.args=args
    def fetchone(self):
        if 'FROM users' in self.sql:
            return dict(id=1,homeowner_public_id='NFH-001',first_name='Maria',last_name='Cruz',block='1',lot='2')
        return None

class FinancialValidationTests(unittest.TestCase):
    def test_whole_peso(self):
        self.assertEqual(money('100'),Decimal('100'))
        with self.assertRaises(ValueError): money('10.5')
        with self.assertRaises(ValueError): money('-5')
    def test_canonical_period(self): self.assertEqual(period(2026,9),date(2026,9,1))
    def test_duplicate_in_same_file(self):
        row=dict(zip(['Homeowner ID','Homeowner Name','Block','Lot','Billing Month','Billing Year','Monthly Dues Amount','Amount Paid','Remaining Due','Payment Status','Remarks'],['NFH-001','Maria Cruz','1','2',9,2026,100,0,100,'Unpaid','']))
        out=validate('dues',[row,row],1,Cursor())
        self.assertEqual([r['status'] for r in out],['Valid','Duplicate'])
    def test_historical_payment_requires_review(self):
        row=dict(zip(['Homeowner ID','Homeowner Name','Block','Lot','Billing Month','Billing Year','Monthly Dues Amount','Amount Paid','Remaining Due','Payment Status','Remarks'],['NFH-001','Maria Cruz','1','2',9,2026,100,50,50,'Partial','']))
        self.assertEqual(validate('dues',[row],1,Cursor())[0]['status'],'Requires Review')
if __name__=='__main__':unittest.main()
