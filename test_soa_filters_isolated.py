"""Run with python test_soa_filters_isolated.py; no database required."""
import unittest
from datetime import date
from financial_ledger import snapshot

class StubCursor:
    def execute(self, sql, params):
        self.sql=sql
    def fetchone(self):
        return {'id':7,'homeowner_public_id':'HO-7','name':'Example Homeowner','block':'1','lot':'2'}
    def fetchall(self):
        q=self.sql
        if 'FROM monthly_dues md' in q:
            return [{'id':10,'covered_month':date(2026,10,1),'occurred':date(2026,10,2),'assessed':100,'paid':0}]
        if 'FROM requests r' in q:
            return [{'id':'R1','type':'Proof of Residency','occurred':date(2026,10,12),'assessed':50,'paid':50}]
        if 'FROM nfh_historical_request_fees h' in q:return []
        if 'FROM nfh_historical_import_entries WHERE' in q:
            return [{'id':33,'kind':'Others','description':'Other Fee','occurred':date(2026,10,13),'assessed':75}]
        if 'FROM nfh_historical_cash_allocations a' in q:return []
        if 'FROM monthly_dues_payments' in q:return []
        if 'FROM payment_transactions' in q:return []
        if 'FROM nfh_historical_fee_receipts hr' in q:return []
        if 'FROM nfh_historical_cash_receipts WHERE' in q:return []
        if 'FROM nfh_historical_cash_receipts h' in q:return []
        return []

class FilterTest(unittest.TestCase):
    def test_all_and_types(self):
        expectations={'all':(1,1,1,225),'monthly_dues':(1,0,0,100),'request_fee':(0,1,0,50),'others':(0,0,1,75)}
        for kind,(dues,fees,others,total) in expectations.items():
            with self.subTest(kind=kind):
                x=snapshot(StubCursor(),7,transaction_type=kind)
                self.assertEqual((len(x['monthly_dues']),len(x['request_fees']),len(x['other_charges'])),(dues,fees,others))
                self.assertEqual(float(x['filtered_assessed']),total)
    def test_status_and_date(self):
        x=snapshot(StubCursor(),7,payment_status='paid')
        self.assertEqual(len(x['request_fees']),1)
        self.assertEqual(len(x['monthly_dues']),0)
        x=snapshot(StubCursor(),7,start='2026-10-13',end='2026-10-13')
        self.assertEqual(len(x['other_charges']),1)
        self.assertEqual(len(x['request_fees']),0)
    def test_invalid_type(self):
        with self.assertRaises(ValueError):snapshot(StubCursor(),7,transaction_type='bad')
    def test_import_dates(self):
        x=snapshot(StubCursor(),7,transaction_type='monthly_dues')
        self.assertEqual(x['monthly_dues'][0]['date'],'2026-10-02')
if __name__=='__main__':unittest.main()
