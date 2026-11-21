"""Pure unit checks for the annual raffle cut-off and covered-month policy."""
import unittest
from datetime import date, datetime
from decimal import Decimal
from advance_promo import raffle_tickets, award_annual_promo, CERTIFICATES, promo_status, redeem_code
from advance_dues import periods

class Cursor:
    def __init__(self,rows):self.rows=rows;self.queries=[]
    def execute(self,sql,args):self.queries.append((sql,args))
    def fetchall(self):
        sql=self.queries[-1][0]
        if 'SELECT ap.due_month' in sql:return self.rows
        return []
    def fetchone(self):
        sql=self.queries[-1][0]
        if 'SELECT id,raffle_tickets' in sql:return {'id':42,'raffle_tickets':12,'certificate_credits':4}
        return {'raffle_tickets':12,'certificate_credits':4}

def rows(when,missing=(),voided=()):
    return [{'due_month':date(2026,m,1),'received_at':datetime.combine(when,datetime.min.time()),
             'gross_amount':Decimal('100'),'cash_amount':Decimal('100'),
             'discount_amount':Decimal('0'),'voided_at':datetime.now() if m in voided else None}
             for m in range(1,13) if m not in missing]

class PromoTests(unittest.TestCase):
    def test_cutoff(self):
        for d,expected in [(date(2025,12,15),12),(date(2026,1,1),12),(date(2026,1,31),12),
                           (date(2026,2,1),0),(date(2026,3,15),0)]:
            with self.subTest(d=d):self.assertEqual(raffle_tickets(2026,d),expected)
    def test_no_incomplete_award(self):
        for excluded in [dict(missing=(4,)),dict(voided=(4,))]:
            with self.subTest(excluded=excluded):
                c=Cursor(rows(date(2026,1,31),**excluded))
                self.assertIsNone(award_annual_promo(c,1,2026,'Treasurer'))
                self.assertEqual(len(c.queries),1)
    def test_full_year_awarded_once(self):
        c=Cursor(rows(date(2026,1,31)))
        self.assertIsNotNone(award_annual_promo(c,1,2026,'Treasurer'))
        self.assertIn('ON DUPLICATE KEY UPDATE id=id',c.queries[1][0])
        self.assertEqual(c.queries[1][1][3],12)
    def test_late_payment_four_credits(self):
        c=Cursor(rows(date(2026,2,1)))
        award_annual_promo(c,1,2026,'Treasurer')
        self.assertEqual(c.queries[1][1][3],0)
        self.assertIn('4',c.queries[1][0])
    def test_current_year_annual_allowed(self):
        self.assertEqual(len(periods('2026-01',12,date(2026,2,1))),12)
        with self.assertRaises(ValueError):periods('2026-01',11,date(2026,2,1))
    def test_expiration_boundaries_manila(self):
        base={'revoked_at':None,'valid_months':12,'redeemed_request_id':None,
              'request_status':None,'expires_at':datetime(2028,1,1)}
        self.assertEqual(promo_status(base,datetime(2027,12,31,23,59,59)),'Active')
        self.assertEqual(promo_status(base,datetime(2028,1,1,0,0,0)),'Expired')
        self.assertEqual(promo_status(dict(base,valid_months=11),datetime(2027,1,1)),'Inactive')
        self.assertEqual(promo_status(dict(base,redeemed_request_id='REQ-10',request_status='Submitted'),datetime(2029,1,1)),'Used')
        self.assertEqual(promo_status(dict(base,redeemed_request_id='REQ-10',request_status='Cancelled'),datetime(2027,1,1)),'Active')
    def test_full_year_generates_four_code_inserts(self):
        for year in (2027,2028,2029):
            ledger=[dict(row,due_month=date(year,i,1)) for i,row in enumerate(rows(date(2026,1,1)),1)]
            c=Cursor(ledger)
            award_annual_promo(c,9,year,'Treasurer')
            inserts=[(q,a) for q,a in c.queries if 'INSERT INTO nfh_promo_codes' in q]
            self.assertEqual(len(inserts),4)
            self.assertEqual({a[-1] for _,a in inserts},{datetime(year+1,1,1)})
            self.assertEqual(len({a[3] for _,a in inserts}),4)
    def test_partial_year_generates_no_codes(self):
        c=Cursor(rows(date(2026,1,1),missing=(12,)))
        self.assertIsNone(award_annual_promo(c,1,2026,'Treasurer'))
        self.assertFalse(any('INSERT INTO nfh_promo_codes' in sql for sql,args in c.queries))
    def test_ownership_and_expiration_rejected_before_redemption(self):
        from unittest.mock import patch
        class Fake:
            def __init__(self, record):self.record=record;self.queries=[]
            def execute(self,sql,args):self.queries.append((sql,args))
            def fetchone(self):return self.record
        inactive={'id':9,'award_id':1,'user_id':3,'expires_at':datetime(2025,1,1),
                  'revoked_at':None,'redeemed_request_id':None,'request_status':None}
        c=Fake(inactive)
        with self.assertRaises(ValueError):
            redeem_code(c,3,'REQ-11','Proof of Residency','UNAVAILABLE',50)
        self.assertTrue(all('UPDATE nfh_promo_codes' not in q for q,a in c.queries))
        with self.assertRaises(ValueError):
            redeem_code(c,3,'REQ-11','Gate Pass','UNAVAILABLE',50)
        with self.assertRaises(ValueError):
            redeem_code(c,3,'REQ-11','Proof of Residency','UNAVAILABLE',0)

    def test_only_certificate_types(self):
        self.assertEqual(CERTIFICATES, {'Proof of Residency','Certificate of Improvement','Certificate of Membership'})

if __name__=='__main__':unittest.main()
