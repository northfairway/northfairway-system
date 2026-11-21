"""Standalone focused claim tests; no Flask server or MariaDB required."""
import ast
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / 'first_time_enrollment.py'

def load_helpers():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'normalize_claim','save_claim'}]
    env = {'re': __import__('re'), 'LOCATION': __import__('re').compile(r'^[\w\- /]{1,50}$', __import__('re').UNICODE)}
    exec(compile(ast.Module(body=funcs,type_ignores=[]),str(SOURCE),'exec'),env)
    return env

class DummyCursor:
    def __init__(self, conflict=False):
        self.statements = []
        self.conflict = conflict
    def execute(self,statement,parameters=None):
        self.statements.append((statement, parameters))
    def fetchall(self):
        return [{'id':2}] if self.conflict else []

class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.fn = load_helpers()
    def test_location_normalized(self):
        self.assertEqual(self.fn['normalize_claim']({'block':' 2a ','lot':' 05 ','evidence_note':'doc'})[:2],('2A','05'))
    def test_missing_location_rejected(self):
        with self.assertRaises(ValueError):self.fn['normalize_claim']({'block':'', 'lot':'1'})
    def test_long_evidence_rejected(self):
        with self.assertRaises(ValueError):self.fn['normalize_claim']({'block':'1','lot':'1','evidence_note':'x'*501})
    def test_claim_intake_does_not_bill_or_activate(self):
        cur=DummyCursor(); self.fn['save_claim'](cur,17,'Occupancy','1','2','paper letter')
        queries=' '.join(s for s,_ in cur.statements).lower()
        self.assertIn('nfh_property_claims',queries)
        self.assertNotIn('monthly_dues',queries)
        self.assertNotIn('nfh_rental_agreements',queries)
    def test_conflicting_owners_are_held(self):
        cur=DummyCursor(conflict=True)
        self.fn['save_claim'](cur,17,'Ownership','1','2','deed')
        self.assertTrue(any("status='Disputed'" in sql for sql,_ in cur.statements))
    def test_no_conflict_keeps_pending(self):
        cur=DummyCursor(conflict=False)
        self.fn['save_claim'](cur,17,'Ownership','1','2','deed')
        self.assertFalse(any("status='Disputed'" in sql for sql,_ in cur.statements))

if __name__=='__main__':unittest.main()
