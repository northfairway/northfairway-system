"""Static plus rendered-message regression tests without live SMTP credentials."""
import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
FUNCTION = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'treasurer_submit_adjustment')
CALL = next(n for n in ast.walk(FUNCTION) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == 'send_alert_and_email')


def render_test_body():
    context = {
        'inserted_months': list(range(15)), 'monthly_due': 100.0,
        'total': 1500.0, 'reason': 'Ledger correction',
        'treasurer': {'name': 'HOA Treasurer', 'phone': '0123456789', 'email': 'test@example.invalid'},
        'periods': 'October 2026, September 2026, August 2026',
    }
    expression = ast.Expression(body=CALL.args[2])
    return eval(compile(ast.fix_missing_locations(expression), '<notification-body>', 'eval'), {'len': len}, context)


class MissingDuesEmailTests(unittest.TestCase):
    def test_notification_body_excludes_new_month_list(self):
        body = render_test_body()
        self.assertNotIn('Newly applied billing periods:', body)
        self.assertNotIn('Recorded period(s):', body)
        self.assertNotIn('October 2026, September 2026', body)

    def test_financial_summary_and_contact_preserved(self):
        body = render_test_body()
        self.assertIn('15 unpaid monthly due(s)', body)
        self.assertIn('₱100.00 each', body)
        self.assertIn('totaling ₱1500.00', body)
        self.assertIn('Reason on file: Ledger correction', body)
        self.assertIn('HOA Treasurer', body)

    def test_audit_periods_and_dedupe_preserved(self):
        function_source = ast.get_source_segment(SOURCE, FUNCTION)
        self.assertIn('periods =', function_source)
        self.assertIn('f"{periods} | New outstanding:', function_source)
        self.assertIn("dedupe_key=f'missing-dues-{adj_id}'", function_source)
        self.assertIn("'recorded_periods':", function_source)


if __name__ == '__main__':
    unittest.main()
