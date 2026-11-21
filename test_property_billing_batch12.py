"""Batch 12 safe isolated unit tests; no production database needed."""
import unittest
from datetime import date
from property_billing import choose_payer, period_start

class PayerTests(unittest.TestCase):
    def agreement(self, payer='Renter', verified='Verified'):
        return dict(id=8, homeowner_id=11, renter_id=27, starts_on=date(2027,1,1),
                    effective_from=date(2027,2,1), ends_on=date(2027,12,31),
                    verification_status=verified, payer_type=payer)
    def test_owner_default(self):
        self.assertEqual(choose_payer(11, [], date(2027,2,21)), ('Homeowner',11,None))
    def test_unverified_agreement_ignored(self):
        self.assertEqual(choose_payer(11,[self.agreement(verified='Pending')],date(2027,3,1)),('Homeowner',11,None))
    def test_owner_pays(self):
        self.assertEqual(choose_payer(11,[self.agreement('Homeowner')],date(2027,3,1)),('Homeowner',11,8))
    def test_renter_pays(self):
        self.assertEqual(choose_payer(11,[self.agreement()],date(2027,3,1)),('Renter',27,8))
    def test_future_effective_date(self):
        self.assertEqual(choose_payer(11,[self.agreement()],date(2027,1,1)),('Homeowner',11,None))
    def test_conflict_rejected(self):
        with self.assertRaises(ValueError): choose_payer(11,[self.agreement(),self.agreement()],date(2027,3,1))
    def test_wrong_owner_rejected(self):
        with self.assertRaises(ValueError): choose_payer(10,[self.agreement()],date(2027,3,1))
    def test_period_normalized(self):
        self.assertEqual(period_start(date(2027,4,29)),date(2027,4,1))
if __name__ == '__main__': unittest.main()
