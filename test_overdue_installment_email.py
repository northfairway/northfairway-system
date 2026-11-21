import unittest
from datetime import date
from decimal import Decimal
from overdue_installment_email_job import eligible, compose, amount

class EmailTests(unittest.TestCase):
 def test_grace_window(self):
  due=date(2026,12,5)
  self.assertFalse(eligible(due,0,175,date(2026,12,9)))
  self.assertTrue(eligible(due,0,175,date(2026,12,10)))
 def test_paid(self):
  self.assertFalse(eligible(date(2026,12,5),175,175,date(2026,12,20)))
 def test_partial_and_no_double_count(self):
  user={'id':7,'first_name':'Juan','last_name':'Dela Cruz','block':'1','lot':'2'}
  inst={'installment_number':2,'due_date':date(2026,12,5),'amount':175,'paid_amount':75}
  plan={'id':4,'installment_count':4}
  summary={'monthly_rate':Decimal('100'),'regular':Decimal('100'),'plan':Decimal('525'),'total':Decimal('625')}
  plain,html=compose(user,inst,plan,summary,date(2026,12,10))
  for key in ['₱100','₱525','₱625','Verified installment paid','Remaining installment balance']:
   self.assertIn(key,plain)
  self.assertIn('text-align:right',html)
  self.assertIn('₱625',html)
  self.assertNotIn('₱725',html)
 def test_reject_fractional_legacy(self):
  with self.assertRaises(ValueError): amount(Decimal('10.50'))
 def test_manila_threshold(self):
  self.assertTrue(eligible(date(2027,1,31),0,100,date(2027,2,5)))
if __name__=='__main__':unittest.main()
