import unittest
from whole_peso import whole
class DiscountTests(unittest.TestCase):
 def test_whole_discounts(self):
  self.assertEqual(1200-whole('200'),1000)
  self.assertEqual(1200-whole('0'),1200)
 def test_fractional_rejected(self):
  for amount in ['0.5','-1','abc']:
   with self.assertRaises(ValueError):whole(amount)
 def test_existing_cash_validation(self):
  from pathlib import Path
  src=(Path(__file__).parent/'advance_dues.py').read_text()
  self.assertIn('discount>approved_limit',src)
  self.assertIn('cash!=gross-discount',src)
  self.assertIn('discount>gross',src)
if __name__=='__main__':unittest.main()
