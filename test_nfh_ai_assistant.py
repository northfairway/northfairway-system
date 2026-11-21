import unittest
from unittest.mock import patch
import json
from nfh_ai_assistant import validate_settings, retrieve, generate, settings_from_rows, UNKNOWN

ROWS=[{'id':1,'question':'How much are monthly dues?','answer':'Monthly dues are ₱100.','keywords':'association payment','category':'Payments'}, {'id':2,'question':'How to request a certificate?','answer':'Use Request portal.','keywords':'certificate','category':'Documents'}]
CFG={'enabled':True,'provider':'gemini','model':'gemini-2.5-flash-lite','fallback':True,'language':'auto','length':'standard'}
class TestAI(unittest.TestCase):
 def test_defaults_off(self): self.assertFalse(settings_from_rows([])['enabled'])
 def test_wrong_model_rejected(self):
  with self.assertRaises(ValueError): validate_settings(dict(CFG, model='unverified-model'))
 def test_retrieval_only_source_rows(self): self.assertEqual({r['id'] for r in retrieve('monthly dues', ROWS)}, {1,2})
 @patch('nfh_ai_assistant._gemini',return_value=json.dumps({'answer':'Monthly dues are ₱100.','source_ids':[1]}))
 def test_grounded_answer(self,api): self.assertEqual(generate('How much are monthly dues?',ROWS,CFG)['source_ids'],[1])
 @patch('nfh_ai_assistant._gemini',return_value=json.dumps({'answer':'made up','source_ids':[999]}))
 def test_reject_unapproved_ids(self,api): self.assertIsNone(generate('How much?',ROWS,CFG))
 @patch('nfh_ai_assistant._gemini',return_value=json.dumps({'answer':UNKNOWN,'source_ids':[]}))
 def test_unknown_abstains(self,api): self.assertIsNone(generate('unknown?',ROWS,CFG))
if __name__=='__main__': unittest.main()
