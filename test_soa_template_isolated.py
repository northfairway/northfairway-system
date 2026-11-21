"""Isolated template/parser checks; does not verify Flask or MySQL integration."""
import importlib.util,sys,types,io
from pathlib import Path
from openpyxl import Workbook


if 'flask' not in sys.modules:
    fake=types.ModuleType('flask')
    fake.Blueprint=lambda *a,**kw: types.SimpleNamespace(get=lambda *_:lambda f:f,post=lambda *_:lambda f:f)
    for k in ('request','session'):setattr(fake,k,{})
    fake.jsonify=lambda **kw:kw
    fake.send_file=lambda x,**kw:x
    sys.modules['flask']=fake
spec=importlib.util.spec_from_file_location('treasurer_financial',Path(__file__).with_name('treasurer_financial.py'))
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
w=Workbook();sh=w.active;sh.title='Historical SOA'
for row,(name,value) in enumerate({'Name':'Test Homeowner','Homeowner ID':'HOA-001','Contact':'09123456789','Email':'test@example.com','Address':'Block 1 Lot 2'}.items(),4):
    sh.cell(row,1,name);sh.cell(row,2,value)
for i,h in enumerate(mod.COLS['soa'],1):sh.cell(12,i,h)
for r,vals in ((13,['AUTO','Proof of Residency','2026-10-15',50,'Unpaid']),(14,['AUTO','Monthly Dues','2026-09-01',100,'Unpaid'])):
    for i,val in enumerate(vals,1):sh.cell(r,i,val)
out=io.BytesIO();w.save(out)
file=types.SimpleNamespace(read=io.BytesIO(out.getvalue()).read,filename='sample.xlsx')
rows=mod.read_rows(file,'soa')
assert len(rows)==2 and rows[0]['_meta']['Homeowner ID']=='HOA-001' and rows[1]['Description']=='Monthly Dues'
assert mod.money('50')==50
assert mod.period(2026,9).isoformat()=='2026-09-01'
print('PASS: 5-column workbook parsing, homeowner metadata, money and period calculation')
class Cursor:
    def __init__(self):self.last='';self.params=();self.queries=[]
    def execute(self,sql,params):self.last=sql;self.params=params;self.queries.append(sql)
    def fetchone(self):
        if 'FROM users' in self.last:
            return {'id':1,'homeowner_public_id':'HOA-001','first_name':'Test','last_name':'Homeowner','block':'1','lot':'2','mobile':'09123456789','email':'test@example.com','address_line':'Block 1 Lot 2'}
        if 'FROM service_types' in self.last:return {'service_name':'Proof of Residency'}
        return None
cur=Cursor();results=mod.validate('soa',rows,1,cur)
assert [r['status'] for r in results]==['Valid','Valid'],results
assert [r['payload']['category'] for r in results]==['soa','dues'],results
bad=dict(rows[0]);bad['_meta']={**rows[0]['_meta'],'Homeowner ID':'ANOTHER-HOMEOWNER'}
assert mod.validate('soa',[bad],1,Cursor())[0]['status']=='Invalid'
paid=dict(rows[0]);paid['Status']='Paid'
assert mod.validate('soa',[paid],1,Cursor())[0]['status']=='Requires Review'
print('PASS: categorization, homeowner mismatch rejection, Paid-status verification hold')
