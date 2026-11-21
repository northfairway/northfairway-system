"""Run: python test_membership_name_cross_validation.py (no live DB required)."""
# Execute the standalone validation functions without importing Flask or connecting to MySQL.
import ast, re, unicodedata
from pathlib import Path
source=ast.parse(Path(__file__).with_name('homeowner_reconciliation.py').read_text())
nodes=[n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in
       ('normalize_id','identity','fullname','address','status_of','normalize_imported_name','valid_homeowner_name','validate')]
constants=[n for n in source.body if isinstance(n, ast.Assign) and any(
    isinstance(t,ast.Name) and t.id in ('NAME_MISMATCH_MESSAGE','INVALID_NAME_MESSAGE') for t in n.targets)]
ns={'re':re,'unicodedata':unicodedata}
exec(compile(ast.Module(body=constants+nodes,type_ignores=[]),'<isolated validation>','exec'),ns)
validate,normalize_id,identity=(ns[x] for x in ('validate','normalize_id','identity'))

registered=[dict(id=8,homeowner_public_id='NFH-001',first_name='Juan',middle_name='S.',last_name='Dela Cruz',suffix='',address_line='Block 1 Lot 2',membership_status='Active')]

def entry(hid='NFH-001',name='Juan S. Dela Cruz',address='Block 1 Lot 2',status='Inactive'):
    return (2,dict(Homeowner_ID=hid,Name=name,Address=address,Status=status))

def check(rows,pending=None):return validate(rows,registered,pending)

ok=check([entry(name='  jUaN   S.  DELA  CRUZ ')])[0]
assert ok['state']=='Ready to Update' and ok['validation_result']=='Valid — Existing Homeowner'
assert ok['registered_name']=='Juan S. Dela Cruz'
wrong=check([entry(name='Maria Santos')])[0]
assert wrong['state']=='Requires Review' and wrong['validation_result']=='Requires Review — Name Mismatch'
assert 'Homeowner Name Mismatch' in wrong['message']
unknown=check([entry('NFH-009','Pedro Reyes')])[0]
assert unknown['validation_result']=='Pending Account Match' and unknown['user_id'] is None
repeated=check([entry(),entry(name='Juan S. Dela Cruz')])[-1]
assert repeated['state']=='Duplicate'
pending={'nfh-009':dict(id=10,imported_name='Pedro Reyes',imported_address='Block 1 Lot 2',imported_status='Inactive')}
assert check([entry('NFH-009','Pedro Reyes')],pending)[0]['validation_result']=='Existing Pending Record — No duplicate'
assert check([entry('NFH-009','Another Person')],pending)[0]['validation_result']=='Requires Review — Pending Name Conflict'
assert check([entry('NFH-001','Juan S. Dela Cruz',address='Different Address')])[0]['state']=='Requires Review'
assert normalize_id(' 00-012 ')=='00-012' and identity('  JuAn   Cruz  ')=='juan cruz'
print('PASS: 8 cross-validation cases')
