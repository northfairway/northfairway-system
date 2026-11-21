from pathlib import Path
import ast,unittest
ROOT=Path(__file__).resolve().parents[1]
class IntegrationStructureTests(unittest.TestCase):
 def test_python_syntax(self):
  for p in ('app.py','nfh_extensions.py','delinquency_job.py'): ast.parse((ROOT/p).read_text())
 def test_registered_blueprint(self): self.assertIn('app.register_blueprint(init_extensions(get_db_connection))',(ROOT/'app.py').read_text())
 def test_homeowner_services(self):
  html=(ROOT/'templates/homeowner.html').read_text()
  for x in ('nfhSoa','nfhConcern','nfhFeedback','nfhResolutions','nfhQuestion'):self.assertIn(x,html)
 def test_migration_is_non_destructive(self):
  sql=(ROOT/'migration_20261022.sql').read_text().upper()
  self.assertNotIn('DROP TABLE',sql);self.assertNotIn('TRUNCATE',sql)
 def test_soa_not_gated(self):self.assertIn("require('Homeowner') # deliberately no monthly-dues gate",(ROOT/'nfh_extensions.py').read_text())
if __name__=='__main__':unittest.main()
