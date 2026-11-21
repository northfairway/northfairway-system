"""Shared HTML and plain-text templates for final account/request decisions."""
from html import escape

HOA = 'North Fairway Homes Homeowners Association Inc.'
TITLES = {'account_verified': 'Account Verification Successful', 'account_rejected': 'Registration Not Approved', 'request_approved': 'Your Document Request Has Been Approved', 'request_rejected': 'Document Request Not Approved'}
MESSAGES = {'account_verified': 'Your homeowner registration has been successfully verified. You may now sign in to the homeowner portal.', 'account_rejected': 'Your homeowner registration could not be approved at this time.', 'request_approved': 'Your document request was approved. Approval does not necessarily mean the document is paid, ready for release, or issued.', 'request_rejected': 'Your document request was not approved. Please review the recorded decision.'}
def render_status_email(kind, name, details=None, next_step=''):
    title=TITLES[kind]; message=MESSAGES[kind]; details=details or {}
    if kind == 'account_rejected':
        homeowner_id = str(details.get('Homeowner ID') or '—')
        remarks = str(details.get('remarks') or details.get('Reason for Rejection') or '').strip()
        # Retain line breaks but escape all administrator-entered HTML.
        html_remarks = '<br>'.join(escape(line) for line in remarks.split('\n'))
        footer = 'This is an automated notification. Contact the HOA office if you need assistance.'
        html = ('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
                '</head><body style="background:#F4F9F4;margin:0;padding:16px 8px;font:15px Arial,sans-serif;color:#2D312E">'
                '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;margin:auto;background:#fff;border-collapse:collapse">'
                '<tr><td style="background:#1B4332;color:#fff;padding:24px;font-weight:bold">' + escape(HOA) + '</td></tr>'
                '<tr><td style="padding:24px"><h1 style="font-size:21px;line-height:1.3;color:#1B4332;margin:0 0 20px">Registration Not Approved</h1>'
                '<p style="line-height:1.6">Dear ' + escape(str(name or 'Homeowner')) + ',</p>'
                '<p style="line-height:1.6">Your homeowner registration could not be approved at this time.</p>'
                '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin:14px 0">'
                '<tr><th scope="row" align="left" style="width:40%;background:#F4F9F4;padding:12px;border-bottom:1px solid #E2EBE2">Homeowner ID</th>'
                '<td style="padding:12px;border-bottom:1px solid #E2EBE2;overflow-wrap:anywhere">' + escape(homeowner_id) + '</td></tr></table>'
                '<p style="line-height:1.6;margin:18px 0 8px">The Administrator provided the following explanation:</p>'
                '<p style="line-height:1.6;overflow-wrap:anywhere;white-space:normal;margin:0 0 20px">' + html_remarks + '</p>'
                '<p style="line-height:1.6">Please review your property information and submit a corrected registration.</p>'
                '</td></tr><tr><td style="background:#E2EBE2;padding:18px;font-size:12px;line-height:1.6">'
                + escape(HOA) + '<p style="margin:8px 0 0">' + escape(footer) + '</p></td></tr></table></body></html>')
        plain = ('North Fairway Homes Homeowners Association Inc.\n\nRegistration Not Approved\n\n'
                 'Dear ' + str(name or 'Homeowner') + ',\n\n'
                 'Your homeowner registration could not be approved at this time.\n\n'
                 'Homeowner ID: ' + homeowner_id + '\n\n'
                 'The Administrator provided the following explanation:\n\n' + remarks + '\n\n'
                 'Please review your property information and submit a corrected registration.\n\n'
                 + HOA + '\n' + footer)
        return html, plain
    rows=''.join('<tr><th align="left" style="padding:10px;border-bottom:1px solid #E2EBE2;text-align:left;width:40%">'+escape(str(k))+'</th><td style="padding:10px;border-bottom:1px solid #E2EBE2;overflow-wrap:anywhere">'+escape(str(v or '—'))+'</td></tr>' for k,v in details.items())
    html='<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="background:#F4F9F4;margin:0;padding:16px 8px;font:15px Arial,sans-serif;color:#2D312E"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;margin:auto;background:white;border-collapse:collapse"><tr><td style="background:#1B4332;color:white;padding:24px;font-weight:bold">'+escape(HOA)+'</td></tr><tr><td style="padding:24px"><h1 style="font-size:21px;color:#1B4332">'+escape(title)+'</h1><p>Dear '+escape(name or 'Homeowner')+',</p><p style="line-height:1.6">'+escape(message)+'</p><table width="100%" cellspacing="0" cellpadding="0">'+rows+'</table><p style="line-height:1.6">'+escape(next_step)+'</p></td></tr><tr><td style="background:#E2EBE2;padding:18px;font-size:12px">'+escape(HOA)+'<p>This is an automated notification. Contact the HOA office if you need assistance.</p></td></tr></table></body></html>'
    plain='\n'.join([title,'Dear '+str(name or 'Homeowner')+',',message]+[str(k)+': '+str(v or '—') for k,v in details.items()]+[next_step,HOA,'This is an automated notification.'])
    return html,plain
