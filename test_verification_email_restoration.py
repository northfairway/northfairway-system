import unittest
from pathlib import Path
from jinja2 import Environment,FileSystemLoader,select_autoescape
class TestVerificationEmail(unittest.TestCase):
 def setUp(self):
  self.root=Path(__file__).resolve().parent
  self.jinja=Environment(loader=FileSystemLoader(str(self.root/'templates')),autoescape=select_autoescape(['html']))
 def test_registration(self):
  h=self.jinja.get_template('emails/verification.html').render(code='123456',title='Verify Your Account',description='Enter the verification code below to complete your registration.',expiry_minutes=10,security_message='Disregard if unexpected')
  for part in ('123456','Verify Your Account','10 minutes','North Fairway Homes','#1B4332','#F4F9F4'):self.assertIn(part,h)
 def test_reset(self):
  h=self.jinja.get_template('emails/verification.html').render(code='654321',title='Password Reset Verification',description='Enter the verification code below to reset your password.',expiry_minutes=5,security_message='Disregard if unexpected')
  for part in ('654321','Password Reset Verification','5 minutes'):self.assertIn(part,h)
 def test_escaping(self):
  h=self.jinja.get_template('emails/verification.html').render(code='123456',title='<script>alert(1)</script>',description='d',expiry_minutes=1,security_message='s')
  self.assertNotIn('<script>',h);self.assertIn('&lt;script&gt;',h)
 def test_sender_paths(self):
  s=(self.root/'app.py').read_text();self.assertEqual(s.count("'emails/verification.html'"),2);self.assertEqual(s.count('msg.html = render_template('),2)
if __name__=='__main__':unittest.main()
