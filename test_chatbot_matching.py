import unittest
from chatbot_matching import match
ROWS=[{'id':1,'question':'How do I request a Statement of Account?','answer':'SOA instructions','keywords':'SOA fee,request SOA,statement of account'}, {'id':2,'question':'How can I request a vehicle sticker?','answer':'Vehicle instructions','keywords':'vehicle sticker,car sticker'}]
class ChatbotMatchingTests(unittest.TestCase):
 def test_exact(self):self.assertEqual(match('HOW DO I REQUEST A STATEMENT OF ACCOUNT?',ROWS)['row']['id'],1)
 def test_alternative(self):self.assertEqual(match('SOA fee',ROWS)['row']['id'],1)
 def test_typo(self):self.assertEqual(match('How do I requst a Statement of Account?',ROWS)['row']['id'],1)
 def test_unrelated(self):self.assertEqual(match('Who is the mayor of London?',ROWS)['type'],'fallback')
 def test_empty(self):self.assertEqual(match('   ',ROWS)['type'],'empty')
 def test_inactive_filter_contract(self):self.assertEqual(match('vehicle sticker',[ROWS[0]])['type'],'fallback')
if __name__=='__main__':unittest.main()
