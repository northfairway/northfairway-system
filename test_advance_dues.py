import unittest
from datetime import date
from decimal import Decimal
from advance_dues import periods, calculate_discount

class TestAdvanceDues(unittest.TestCase):
    def test_cross_year_periods(self):
        self.assertEqual([str(x) for x in periods('2026-11',4,date(2026,10,27))],['2026-11-01','2026-12-01','2027-01-01','2027-02-01'])
    def test_future_only(self):
        with self.assertRaises(ValueError): periods('2026-10',1,date(2026,10,27))
    def test_month_limits(self):
        with self.assertRaises(ValueError): periods('2027-01',61,date(2026,10,27))
    def test_without_discount(self):
        self.assertEqual(calculate_discount(None,None,12,Decimal('1200'),date(2026,10,27))[0],Decimal('0.00'))
    def test_no_unapproved_policy(self):
        class Cursor:
            def execute(self,*args):pass
            def fetchone(self):return None
        with self.assertRaises(ValueError): calculate_discount(Cursor(),3,12,Decimal('1200'),date(2026,10,27))
    def test_percentage_and_fixed(self):
        class Cursor:
            value=None
            def execute(self,*args):pass
            def fetchone(self):return self.value
        c=Cursor()
        base={'id':1,'resolution_reference':'HOA-RES-001','authorized_by':'Board','discount_value':Decimal('10')}
        c.value=dict(base,discount_type='Percentage')
        self.assertEqual(calculate_discount(c,1,12,Decimal('1200'),date(2026,10,27))[0],Decimal('120.00'))
        c.value=dict(base,discount_type='Fixed')
        self.assertEqual(calculate_discount(c,1,12,Decimal('1200'),date(2026,10,27))[0],Decimal('10.00'))
if __name__=='__main__':unittest.main()
