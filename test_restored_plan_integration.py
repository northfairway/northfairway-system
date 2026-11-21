import unittest
from pathlib import Path
from datetime import date
from whole_peso import whole, installments
from inline_missing_dues_plan import schedule

ROOT=Path(__file__).resolve().parent

class PaymentPlanRegression(unittest.TestCase):
    def test_remainder_distribution(self):
        self.assertEqual([a for _,_,a in schedule(1000,3,date(2026,11,12))],[334,333,333])
    def test_month_end(self):
        self.assertEqual([str(d) for _,d,_ in schedule(300,3,date(2027,1,31))],['2027-01-31','2027-02-28','2027-03-31'])
    def test_fractional_cash_rejected(self):
        for value in ('1.50','-1','0','nan'):
            with self.assertRaises(ValueError):whole(value,positive=True)
    def test_tabs_and_existing_form_retained(self):
        html=(ROOT/'templates/officer.html').read_text()
        for text in ('Monthly Dues Advance Payment','Monthly Dues Adjustment','nfhPaymentPlanPanel','nfhCashModal','adjHomeownerSearch'):
            self.assertIn(text,html)
    def test_routes_and_transaction(self):
        app=(ROOT/'app.py').read_text()
        for needle in ("'/api/treasurer/payment-overview/<int:user_id>'", "'/api/treasurer/settle-dues'", 'record_payment(conn,homeowner_id,amount', 'conn.commit()'):
            self.assertIn(needle,app)
    def test_cash_modal_no_browser_prompt(self):
        js=(ROOT/'static/officer.js').read_text()
        start=js.index('async function settleMonthlyDues(');end=js.index('window.filterAdjustmentHomeowners=',start)
        section=js[start:end]
        self.assertNotIn('prompt(',section)
        self.assertIn('nfhCashModal',section)
        self.assertIn('request_key:nfhCashState.key',section)
    def test_original_email_not_replaced_by_otp(self):
        app=(ROOT/'app.py').read_text()
        self.assertIn("'Missing Monthly Dues Notice'",app)
        self.assertIn('Payment Plan Arrangement:',app)
        self.assertNotIn('Newly applied billing periods:',app)

if __name__=='__main__':unittest.main()
