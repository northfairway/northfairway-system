import unittest
from unittest.mock import patch
from flask import Flask
import nfh_extensions as ext

class Cursor:
    def __init__(self, state):self.s=state;self.lastrowid=7;self._row=None
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql,args=()):
        self.s['sql'].append((sql,args))
        if 'SELECT status,version,user_id' in sql:self._row={'status':'Submitted','version':0,'user_id':11}
        elif 'SELECT user_id FROM general_concerns' in sql:self._row={'user_id':11}
    def fetchone(self):return self._row
    def fetchall(self):return []
class Conn:
    def __init__(self,s):self.s=s
    def cursor(self):return Cursor(self.s)
    def commit(self):self.s['commits']+=1
    def rollback(self):self.s['rollbacks']+=1
    def close(self):pass
class Tests(unittest.TestCase):
    def setUp(self):
        self.state={'sql':[],'commits':0,'rollbacks':0}
        app=Flask(__name__);app.secret_key='testing';app.register_blueprint(ext.init_extensions(lambda **kwargs:Conn(self.state)));app.testing=True
        self.client=app.test_client()
    def login(self,role,uid=4):
        with self.client.session_transaction() as sess:sess.update(user_id=uid,role=role,username='test')
    def test_homeowner_submission_audited(self):
        self.login('Homeowner',11)
        r=self.client.post('/api/nfh/concerns',json={'category':'General','subject':'Road','description':'Pothole'})
        self.assertEqual(r.status_code,201)
        self.assertEqual(self.state['commits'],1)
        self.assertTrue(any('INSERT INTO audit_logs' in q for q,_ in self.state['sql']))
    def test_officer_update_audit_alert_history(self):
        for role in ('Secretary','Treasurer','President','Vice President','Board Director'):
            self.setUp();self.login(role)
            r=self.client.post('/api/nfh/concerns/7/respond',json={'status':'Acknowledged','response':'We will inspect','version':0})
            self.assertEqual(r.status_code,200,(role,r.get_json()))
            for table in ('general_concern_history','audit_logs','alerts','notification_log'):
                self.assertTrue(any('INSERT INTO '+table in q for q,_ in self.state['sql']),table)
            self.assertEqual(self.state['commits'],1)
    def test_conflict_rolls_back(self):
        self.login('Treasurer')
        r=self.client.post('/api/nfh/concerns/7/respond',json={'status':'Resolved','response':'Done','version':1})
        self.assertEqual(r.status_code,409)
        self.assertEqual(self.state['commits'],0)
        self.assertEqual(self.state['rollbacks'],1)
    def test_homeowner_cannot_respond(self):
        self.login('Homeowner',11)
        self.assertEqual(self.client.post('/api/nfh/concerns/7/respond',json={'status':'Resolved','response':'No','version':0}).status_code,403)
    def test_homeowner_cannot_view_other_history(self):
        self.login('Homeowner',12)
        self.assertEqual(self.client.get('/api/nfh/concerns/7/history').status_code,403)
if __name__=='__main__':unittest.main()
