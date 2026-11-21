"""Isolated parsing/template checks; does NOT prove live Flask or MySQL integration."""
import io, sys, types
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from openpyxl import load_workbook

# Import application module without starting Flask in this isolated environment.
fake=types.ModuleType('flask')
class BP:
    def __init__(self,*args,**kwargs):pass
    def get(self,*args,**kwargs):return lambda f:f
    def post(self,*args,**kwargs):return lambda f:f
fake.Blueprint=BP
fake.request=types.SimpleNamespace(args={},form={})
fake.jsonify=lambda **kw:kw
fake.session={'user_id':2,'role':'Treasurer'}
fake.send_file=lambda file,**kw:file.getvalue()
sys.modules.setdefault('flask',fake)
import treasurer_financial as m

USER={'id':5,'homeowner_public_id':'NFH-005','first_name':'Jane','last_name':'Doe','mobile':'09123456789','email':'j@example.test','address_line':'B 10 L 2','block':'10','lot':'2'}
class Cursor:
    def __init__(self):self.last=''
    def execute(self,sql,args=None):self.last=sql
    def fetchone(self):return USER if 'FROM users ' in self.last else None
    def __enter__(self):return self
    def __exit__(self,*args):pass
class Conn:
    def cursor(self):return Cursor()
    def close(self):pass
class File:
    filename='historical.xlsx'
    def __init__(self,data):self.data=data
    def read(self,*args):return self.data
with patch.object(m,'connection',lambda:Conn()), patch.object(m.request,'args',{'homeowner_id':'5'}), patch.object(m,'send_file',lambda buf,**kwargs:buf.getvalue()):
    # Flask request.args.get(type=int) semantics are needed by the template.
    class Query(dict):
        def get(self,key,default=None,type=None):
            v=super().get(key,default);return type(v) if v is not None and type else v
    m.request.args=Query(homeowner_id='5')
    data=m.template('soa')
w=load_workbook(io.BytesIO(data));ws=w['Historical SOA']
assert [ws.cell(12,j).value for j in range(1,8)]==m.COLS['soa']
assert ws['B5'].value=='NFH-005'
assert 'Examples - DO NOT IMPORT' in w.sheetnames
assert ws['A13'].protection.locked and not ws['G13'].protection.locked
assert len(ws.data_validations.dataValidation)==2
ws['B13']='Request';ws['C13']='Proof of Residency';ws['D13']=date(2026,10,15);ws['E13']=50;ws['F13']='Paid';ws['G13']='000123'
ws['B14']='Others';ws['C14']='Historical fee';ws['D14']=date(2026,10,16);ws['E14']=60;ws['F14']='Unpaid'
out=io.BytesIO();w.save(out)
rows=m.read_rows(File(out.getvalue()),'soa')
assert len(rows)==2 and rows[0]['OR Number']=='000123' and rows[0]['Type']=='Request'
assert rows[1]['Type']=='Others' and rows[1]['OR Number'] is None
assert m.money('50')==Decimal(50)
print('PASS: seven-column template, protected fields, dropdowns, parser, leading-zero OR, and Others row')
