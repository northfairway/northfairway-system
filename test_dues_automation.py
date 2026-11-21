import unittest
from datetime import date
from decimal import Decimal
from dues_automation import payment_state, money
class DuesRules(unittest.TestCase):
    def test_deadline(self):
        self.assertEqual(payment_state(date(2026,10,1),100,0,date(2026,10,5)),'Unpaid')
        self.assertEqual(payment_state(date(2026,10,1),100,0,date(2026,10,6)),'Overdue')
    def test_advance(self):
        self.assertEqual(payment_state(date(2026,11,1),100,100,date(2026,10,22)),'Paid in Advance')
    def test_partial(self):
        self.assertEqual(payment_state(date(2026,10,1),100,50,date(2026,10,22)),'Partially Paid')
    def test_money(self):
        self.assertEqual(money('100.005'),Decimal('100.01'))
if __name__=='__main__': unittest.main()
