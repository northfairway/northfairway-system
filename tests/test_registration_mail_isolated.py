"""Standalone isolated tests of actual app.py OTP and configuration functions.
Run with: python tests/test_registration_mail_isolated.py
Does not require Flask, MySQL, or SMTP.
"""
import ast
import hashlib
import hmac
import os
import re
import secrets
import string
import time
from pathlib import Path
from types import SimpleNamespace
from email.utils import parseaddr

source = Path(__file__).resolve().parents[1] / 'app.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
wanted = ['generate_code','_issue_one_time_code','_verify_one_time_code','_registration_email_verified','_validate_mail_settings']
module = ast.Module(body=[functions[n] for n in wanted],type_ignores=[])
app = SimpleNamespace(secret_key='test-secret',config={
    'MAIL_SERVER':'smtp.gmail.com','MAIL_PORT':587,'MAIL_USE_TLS':True,
    'MAIL_USE_SSL':False,'MAIL_USERNAME':'sender@example.com',
    'MAIL_PASSWORD':'secret','MAIL_DEFAULT_SENDER':'sender@example.com'})
namespace = {'app':app,'OTP_TTL_SECONDS':600,'OTP_RESEND_COOLDOWN_SECONDS':60,
             'OTP_MAX_ATTEMPTS':5,'time':time,'secrets':secrets,'hashlib':hashlib,
             'hmac':hmac,'string':string,'re':re,'parseaddr':parseaddr,'VERIFICATION_CODES':{}}
exec(compile(module,str(source),'exec'),namespace)
issue=namespace['_issue_one_time_code']; verify=namespace['_verify_one_time_code']; store={}
code, wait=issue(store,'user@example.com')
assert len(code)==6 and code.isdigit() and wait==0
assert 'code' not in store['user@example.com'] and 'code_hash' in store['user@example.com']
assert issue(store,'user@example.com')[0] is None
assert verify(store,'user@example.com','000000')[0] is False or code=='000000'
assert verify(store,'user@example.com',code,mark_verified=True)[0] is True
assert namespace['_registration_email_verified']('user@example.com') is False  # separate store
assert store['user@example.com']['code_hash'] is None
assert verify(store,'user@example.com',code)[0] is False
expired={}; k='expired@example.com'; expired_code,_=issue(expired,k)
expired[k]['expires_at']=time.time()-1
assert verify(expired,k,expired_code)[0] is False
assert k not in expired
namespace['_validate_mail_settings']()
app.config['MAIL_USE_SSL']=True
try: namespace['_validate_mail_settings'](); raise AssertionError('accepted dual TLS+SSL')
except ValueError: pass
print('PASS: OTP hashed, cooldown, verification, one-use, expiry, invalid mail mode')
