"""Pure ledger smoke test. Does NOT claim real MySQL compatibility."""
from decimal import Decimal
from financial_ledger import snapshot

class Cursor:
    def __init__(self): self.result=None
    def execute(self, sql, params):
        if 'FROM users' in sql: self.result={'id':1,'homeowner_public_id':'HOA-001','name':'Test Person','block':'1','lot':'2'}
        elif 'FROM monthly_dues md' in sql: self.result=[]
        elif 'FROM requests r' in sql: self.result=[]
        elif 'FROM nfh_historical_request_fees h' in sql: self.result=[{'id':2,'type':'Proof of Residency','occurred':'2026-10-15','assessed':Decimal('50'),'paid':Decimal('20'),'external_ref':'HIST-2'}]
        elif 'FROM monthly_dues_payments' in sql: self.result=[]
        elif 'FROM payment_transactions' in sql: self.result=[]
        elif 'FROM nfh_historical_fee_receipts' in sql: self.result=[{'id':7,'occurred':'2026-10-20','amount':Decimal('20')}]
        else: raise AssertionError('Unexpected SQL: '+sql)
    def fetchone(self):return self.result
    def fetchall(self):return self.result

if __name__=='__main__':
    result=snapshot(Cursor(),1)
    assert result['charges']=='50',result
    assert result['payments_during_period']=='20',result
    assert result['closing_balance']=='30',result
    assert result['request_fees'][0]['remaining']=='30',result
    assert result['request_fees'][0]['status']=='Partial',result
    print('PASS: isolated historical fee ₱50 less verified receipt ₱20 = ₱30 remaining')
