"""Isolated validation regression; run `python test_membership_name_characters.py`."""
import ast, re, unicodedata
from pathlib import Path
src = ast.parse(Path(__file__).with_name('homeowner_reconciliation.py').read_text(encoding='utf-8'))
wanted = {'normalize_id','identity','fullname','address','status_of','normalize_imported_name','valid_homeowner_name','validate'}
constants={'NAME_MISMATCH_MESSAGE','INVALID_NAME_MESSAGE'}
nodes=[n for n in src.body if (isinstance(n, ast.FunctionDef) and n.name in wanted) or (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets))]
ns={'re':re,'unicodedata':unicodedata}
exec(compile(ast.Module(body=nodes,type_ignores=[]),'validation','exec'),ns)
valid=ns['valid_homeowner_name']; validate=ns['validate']; normalize=ns['normalize_imported_name']
valid_names=['Juan Dela Cruz','María Dela Cruz','Jose Niño Santos','Mary-Anne Reyes',"D'Angelo Cruz",'John A. Santos','Ma. Cristina Reyes','Juán Ñ. Santos', 'Jose Ni\u006e\u0303o', 'O’Connor']
invalid_names=['Juan123 Cruz','Maria@Santos','Pedro_Cruz','Juan#Reyes','Test123','', '  ', 'John\x00 Doe','Juan\nCruz', 'Juan\tCruz', '<b>Juan</b>','John😀 Cruz','Juan$ Cruz','Juan+ Cruz','Juan= Cruz','Juan% Cruz','Juan& Cruz','John\u200d Cruz','123','...', '\u0303Juan']
for name in valid_names: assert valid(name), ('should accept',repr(name))
for name in invalid_names: 
    assert not valid(name), ('should reject',repr(name))
assert normalize('  Maria   Ñ. Santos ') == 'Maria Ñ. Santos'
users=[{'id':1,'homeowner_public_id':'NFH-001','first_name':'Juan','middle_name':'','last_name':'Dela Cruz','suffix':'','address_line':'Block 1 Lot 2','membership_status':'Active'}]
def r(hid,name):return (2,{'Homeowner_ID':hid,'Name':name,'Address':'Block 1 Lot 2','Status':'Inactive'})
assert validate([r('NFH-001','Juan Dela Cruz')],users)[0]['state']=='Ready to Update'
for bad in invalid_names:
    result=validate([r('NFH-001',bad)],users)[0]
    assert result['state']=='Invalid' and ns['INVALID_NAME_MESSAGE'] in result['message'],(bad,result)
assert validate([r('NFH-002','María Dela Cruz')],users)[0]['state']=='Valid — Pending Account Match'
assert validate([r('NFH-001','Maria Santos')],users)[0]['validation_result']=='Requires Review — Name Mismatch'
assert validate([r('NFH-001','Juan Dela Cruz'),r('NFH-001','Juan Dela Cruz')],users)[1]['state']=='Duplicate'
print(f'PASS: {len(valid_names)} accepted examples, {len(invalid_names)} rejected examples, and reconciliation flow checks')
