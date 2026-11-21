import unittest
from datetime import date
from whole_peso import whole,installments,authorized_discount
from inline_missing_dues_plan import schedule
class TestWholePlan(unittest.TestCase):
 def test_split(self): self.assertEqual(installments(1000,3),[334,333,333])
 def test_whole(self):
  for amount in ['100.20','0','-5','invalid']:
   with self.assertRaises(ValueError):whole(amount,positive=True)
  self.assertEqual(whole('100.00',positive=True),100)
 def test_month_end(self):
  self.assertEqual([str(x[1]) for x in schedule(1000,3,date(2027,1,31))],['2027-01-31','2027-02-28','2027-03-31'])
 def test_discount(self):self.assertEqual(authorized_discount(1200,'Percentage',10),120)
 def test_total(self):self.assertEqual(sum(x[2] for x in schedule(1000,3,date(2026,11,1))),1000)
if __name__=='__main__':unittest.main()
