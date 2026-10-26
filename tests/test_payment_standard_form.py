"""Real Chrome regressions for standard, PAN-anchored checkout semantics."""
import unittest
import test_payment_browser as fixtures
from secure_entry import payment_browser


class StandardFormTests(unittest.TestCase):
    setUp = fixtures.PaymentBrowserTests.setUp
    cleanup = fixtures.PaymentBrowserTests.cleanup
    def target_for_html(self, html):
        frame=self.page.frames[1]
        frame.evaluate('html=>document.body.innerHTML=html',html)
        session=self.context.new_cdp_session(frame)
        root=session.send('DOM.getDocument')['root']['nodeId']
        mapping={}
        for token,autocomplete in [('cc-number','cc-number'),('cc-exp-month','cc-exp-month'),
                                   ('cc-exp-year','cc-exp-year'),('cc-csc','cc-cvc'),('cc-name','name')]:
            node=session.send('DOM.querySelector',{'nodeId':root,'selector':'[autocomplete="'+autocomplete+'"]'})['nodeId']
            mapping[token]=session.send('DOM.describeNode',{'nodeId':node})['node']['backendNodeId']
        session.detach()
        target=payment_browser.Target(self.capture,self.parent,self.frame,'https://merchant.test',
                                      'https://provider.test',lambda:None,field_mapping=mapping)
        self.addCleanup(target.close)
        return target

    @staticmethod
    def standard_html():
        return '''<form><input type="tel" autocomplete="cc-number">
          <input type="tel" autocomplete="cc-exp-month"><input type="tel" autocomplete="cc-exp-year">
          <input type="tel" autocomplete="cc-cvc"><input autocomplete="name">
          <input autocomplete="address-line1" value="1 Test St" required>
          <input autocomplete="address-line2"><input autocomplete="address-level2" value="Test City" required>
          <input type="tel" autocomplete="postal-code" value="10001" required>
          <select autocomplete="country-name" required><option value="US">United States</option></select>
          <select autocomplete="address-level1" required><option value="NY">New York</option></select></form>'''

    def test_standard_billing_aliases_use_retained_original_attributes(self):
        target = self.target_for_html(self.standard_html())
        frame = self.page.frames[1]
        before = frame.locator('input,select').evaluate_all('es=>es.map(e=>e.getAttribute("autocomplete"))')
        result = target.fill(dict(number='4242424242424242', exp_month=12, exp_year=2035,
            cvc='987', billing_address={'name':'Synthetic Cardholder','postal_code':'10001'},
            preserve_unsupplied_billing=True))
        self.assertEqual(result['filled_fields'], 5)
        self.assertEqual(frame.locator('input,select').evaluate_all('es=>es.map(e=>e.getAttribute("autocomplete"))'), before)
        self.assertTrue(frame.evaluate('''()=>document.querySelector('[autocomplete="cc-cvc"]').value==='987' &&
            document.querySelector('[autocomplete="name"]').value==='Synthetic Cardholder' '''))


    def test_unrelated_controls_forms_and_mutations_do_not_block_card_fill(self):
        html = self.standard_html().replace('</form>', '''
          <input name="coupon"><input type="password" name="account_password">
          <textarea name="note"></textarea><input type="checkbox" name="consent">
          <select><option value="+1">United States +1</option></select></form>
          <input type="checkbox" id="tos"><input type="checkbox" id="email_opt_out">
          <form id="search"><input name="query"><button>Search</button></form>''')
        target = self.target_for_html(html)
        self.page.frames[1].evaluate('''()=>{
          document.querySelector('[name="coupon"]').setAttribute('placeholder','Coupon');
          document.querySelector('#search').append(document.createElement('input'));
          document.querySelector('#tos').checked=true;
        }''')
        result = target.fill(dict(number='4242424242424242', exp_month=12, exp_year=2035,
            cvc='987', billing_address={'name':'Synthetic Cardholder','postal_code':'10001'},
            preserve_unsupplied_billing=True))
        self.assertEqual(result['filled_fields'], 5)
        self.assertTrue(self.page.frames[1].evaluate('''()=>
            document.querySelector('[name="coupon"]').value==='' &&
            document.querySelector('[name="account_password"]').value==='' &&
            document.querySelector('#tos').checked && !document.querySelector('#email_opt_out').checked'''))


if __name__ == '__main__':
    unittest.main()
