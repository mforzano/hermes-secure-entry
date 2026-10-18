"""Disposable real-Chrome topology/semantic regressions; no real payment traffic."""

import unittest
import test_payment_browser as fixtures
from secure_entry import payment_browser


class StandalonePaymentTests(unittest.TestCase):
    setUp = fixtures.PaymentBrowserTests.setUp
    cleanup = fixtures.PaymentBrowserTests.cleanup
    _run_facility = fixtures.PaymentBrowserTests._run_facility

    def standalone(self, html):
        self.page.evaluate("html=>document.body.innerHTML=html", html)
        session = self.context.new_cdp_session(self.page)
        self.frame = session.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        return payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://merchant.test",
            lambda: None,
        )

    def semantic_html(self):
        return """<form method="post"><input type="hidden" name="opaqueState" value="synthetic-state">
            <input autocomplete="postal-code"><input autocomplete="cc-name"><input autocomplete="cc-number">
            <table><tr><td><label for="month">* Month</label></td><td><select id="month"><option value=""></option>
            <option value="12">December</option></select></td></tr>
            <tr><td><label for="year">* Year</label></td><td><select id="year"><option value=""></option>
            <option value="2035">2035</option></select></td></tr></table>
            <label>Card Verification Value(CVV2)<input id="security"></label>
            <input type="button" value="Back"><input type="submit" value="Next"><button type="button">Exit</button></form>"""

    def test_semantic_split_selects_cvc_postback_and_billing(self):
        target = self.standalone(self.semantic_html())
        self.addCleanup(target.close)
        before = self.page.locator("input,select").evaluate_all(
            'es=>es.map(e=>e.getAttribute("autocomplete"))'
        )
        result = target.fill(
            dict(
                number="4242424242424242",
                exp_month=12,
                exp_year=2035,
                cvc="123",
                billing_address={
                    "name": "Synthetic Cardholder",
                    "postal_code": "10001",
                },
            )
        )
        self.assertEqual(result["filled_fields"], 6)
        self.assertTrue(
            self.page.evaluate("""()=>document.querySelector('#month').value==='12' &&
            document.querySelector('#year').value==='2035' && document.querySelector('#security').value==='123' &&
            document.querySelector('[type=hidden]').value==='synthetic-state' """)
        )
        self.assertEqual(
            self.page.locator("input,select").evaluate_all(
                'es=>es.map(e=>e.getAttribute("autocomplete"))'
            ),
            before,
        )

    def test_native_root_semantic_form_consent_and_private_producer(self):
        target = self.standalone(self.semantic_html())
        target.close()
        self.page.evaluate("""()=>{window.submits=0;window.clicks=0;
            document.querySelector('form').onsubmit=e=>{window.submits++;e.preventDefault();};
            document.querySelectorAll('button,[type=submit],[type=button]').forEach(e=>e.onclick=()=>window.clicks++);}""")
        result, prompts = self._run_facility(
            frame_origin="https://merchant.test",
            registered=True,
            issued_card=dict(
                number="4242424242424242",
                exp_month=12,
                exp_year=2035,
                cvc="123",
                billing_address={
                    "name": "Synthetic Cardholder",
                    "postal_code": "10001",
                },
            ),
        )
        self.assertTrue(
            self.page.evaluate("()=>window.submits===0 && window.clicks===0")
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(result["filled_fields"], 6)
        self.assertEqual(len(prompts), 1)

    def test_default_expiry_selects_can_be_replaced_after_retention(self):
        html = self.semantic_html().replace('<option value=""></option>', "")
        html = html.replace(
            '<option value="12">',
            '<option value="01">January</option><option value="12">',
        )
        html = html.replace(
            '<option value="2035">',
            '<option value="2030">2030</option><option value="2035">',
        )
        target = self.standalone(html)
        self.addCleanup(target.close)
        self.assertEqual(
            target.fill(
                dict(
                    number="4242424242424242",
                    exp_month=12,
                    exp_year=2035,
                    cvc="123",
                    billing_address={
                        "name": "Synthetic Cardholder",
                        "postal_code": "10001",
                    },
                )
            )["filled_fields"],
            6,
        )

    def test_semantic_label_change_and_restore_is_sticky(self):
        for mutation in (
            "const l=document.querySelector('label[for=month]');l.firstChild.data='Other';l.firstChild.data='* Month'",
            "const l=document.querySelector('label[for=month]');l.htmlFor='year';l.htmlFor='month'",
        ):
            with self.subTest(mutation=mutation):
                target = self.standalone(self.semantic_html())
                self.page.evaluate("()=>{" + mutation + "}")
                with self.assertRaises(ValueError):
                    target.check()
                target.close()

    def test_structural_single_control_table_labels_and_numeric_options(self):
        html = self.semantic_html().replace(
            '<label for="month">* Month</label>', "* Month"
        )
        html = html.replace('<label for="year">* Year</label>', "* Year")
        html = html.replace(
            '<option value="12">December</option>',
            '<option value="1">January</option><option value="12">December</option>',
        )
        target = self.standalone(html)
        self.addCleanup(target.close)
        self.assertEqual(
            target.fill(
                dict(
                    number="4242424242424242",
                    exp_month=12,
                    exp_year=2035,
                    cvc="123",
                    billing_address={
                        "name": "Synthetic Cardholder",
                        "postal_code": "10001",
                    },
                )
            )["filled_fields"],
            6,
        )

    def test_root_semantic_combined_expiry_and_aria_cvc_in_oopif(self):
        frame = self.page.frames[1]
        frame.evaluate("""()=>document.body.innerHTML='<form><input autocomplete="cc-number">'+
            '<label>Expiration date<input id="expiry"></label><span id="cvc-label">Security code</span>'+
            '<input aria-labelledby="cvc-label" id="cvc"><button type="submit">Next</button></form>' """)
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.addCleanup(target.close)
        self.assertTrue(target.attached)
        self.assertEqual(
            target.fill(
                dict(number="4242424242424242", exp_month=12, exp_year=2035, cvc="123")
            )["filled_fields"],
            3,
        )
        self.assertTrue(
            frame.evaluate(
                '()=>document.querySelector("#expiry").value==="12/35" && document.querySelector("#cvc").value==="123"'
            )
        )

    def test_default_expiry_without_cvc_verifies_even_when_only_pan_changes(self):
        html = '<form><input autocomplete="cc-number"><label>Month<select><option value="12">12</option></select></label>'
        html += '<label>Year<select><option value="2035">2035</option></select></label></form>'
        target = self.standalone(html)
        self.addCleanup(target.close)
        self.assertEqual(
            target.fill(dict(number="4242424242424242", exp_month=12, exp_year=2035))[
                "filled_fields"
            ],
            1,
        )

    def test_semantic_ambiguity_and_unrelated_fields_refuse_without_writes(self):
        for extra in (
            "<label>Month<input></label>",
            "<label>CVV<input></label>",
            "<label>Date of birth<input></label>",
            '<input autocomplete="email">',
            '<input autocomplete="cc-number">',
            '<textarea aria-label="Security code"></textarea>',
            '<input type="hidden" autocomplete="cc-csc">',
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(payment_browser.BindingRefused):
                    self.standalone(
                        self.semantic_html().replace("</form>", extra + "</form>")
                    )
                self.assertTrue(
                    self.page.locator("[autocomplete=cc-number]").evaluate_all(
                        'es=>es.every(e=>e.value==="")'
                    )
                )

    def test_root_navigation_control_and_form_authority_mutations_refuse(self):
        for mutation in (
            "document.querySelector('form').action='https://foreign.test/';document.querySelector('form').removeAttribute('action')",
            "const e=document.querySelector('#security');e.name='other';e.removeAttribute('name')",
            "const e=document.querySelector('#security');e.replaceWith(e.cloneNode())",
            "const e=document.querySelector('#month');e.setAttribute('form','other');e.removeAttribute('form')",
            "const e=document.querySelector('[type=hidden]');e.autocomplete='cc-csc';e.removeAttribute('autocomplete')",
            "const e=document.querySelector('[type=hidden]');e.type='text';e.type='hidden'",
            "const e=document.querySelector('[type=submit]');e.type='text';e.type='submit'",
            "const e=document.querySelector('#month option');e.value='other';e.value=''",
            "location.hash='changed'",
        ):
            with self.subTest(mutation=mutation):
                target = self.standalone(self.semantic_html())
                self.page.evaluate("()=>{" + mutation + "}")
                with self.assertRaises(ValueError):
                    target.check()
                target.close()
        target = self.standalone(self.semantic_html())
        self.addCleanup(target.close)
        self.page.reload()
        with self.assertRaises((ValueError, RuntimeError)):
            target.check()

    def test_semantic_label_insertion_then_removal_is_sticky(self):
        target = self.standalone(self.semantic_html())
        self.addCleanup(target.close)
        self.page.evaluate("""()=>{const n=document.createElement('label');n.htmlFor='month';n.textContent='Other';
            document.body.append(n);n.remove();}""")
        with self.assertRaises(ValueError):
            target.check()

    def test_expiry_select_numeric_aliases_map_uniquely(self):
        html = (
            self.semantic_html()
            .replace('value="12">December', 'value="1">January')
            .replace('value="2035">2035', 'value="35">2035')
        )
        target = self.standalone(html)
        self.addCleanup(target.close)
        self.assertEqual(
            target.fill(
                dict(
                    number="4242424242424242",
                    exp_month=1,
                    exp_year=2035,
                    cvc="123",
                    billing_address={
                        "name": "Synthetic Cardholder",
                        "postal_code": "10001",
                    },
                )
            )["filled_fields"],
            6,
        )
        self.assertTrue(
            self.page.evaluate(
                '()=>document.querySelector("#month").value==="1" && document.querySelector("#year").value==="35"'
            )
        )
        target.close()
        html = html.replace(
            '<option value="1">January',
            '<option value="01">January</option><option value="1">January',
        )
        target = self.standalone(html)
        self.addCleanup(target.close)
        with self.assertRaises(payment_browser.WriteRefused) as caught:
            target.fill(
                dict(
                    number="4242424242424242",
                    exp_month=1,
                    exp_year=2035,
                    cvc="123",
                    billing_address={
                        "name": "Synthetic Cardholder",
                        "postal_code": "10001",
                    },
                )
            )
        self.assertEqual(caught.exception.category, "select_mismatch")
        self.assertEqual(caught.exception.written, 0)

    def test_aria_only_semantics_keep_label_insertion_sticky(self):
        target = self.standalone(
            '<form><input autocomplete="cc-number"><input id="expiry" aria-label="Expiry">'
            '<input aria-label="CVV"></form>'
        )
        self.addCleanup(target.close)
        self.page.evaluate("""()=>{const n=document.createElement('label');n.htmlFor='expiry';n.textContent='Other';
            document.body.append(n);n.remove();}""")
        with self.assertRaises(ValueError):
            target.check()

    def test_offsite_root_registered_native_consent_and_exact_provider(self):
        # The selected page is the processor, not a retained merchant ancestor.
        self.page.goto("https://provider.test/pay")
        session = self.context.new_cdp_session(self.page)
        self.frame = session.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        # A merchant mismatch never excuses a wrong destination origin.
        result, _ = self._run_facility(
            frame_origin="https://wrong-provider.test", registered=True, expected_prompts=0
        )
        self.assertFalse(result["success"], result)
        self.assertEqual(result["stage"], "target_binding")
        self.assertTrue(self.page.evaluate(
            '()=>[...document.querySelectorAll("input")].every(e=>e.value==="")'
        ))
        # Real synthetic producer still issues for merchant.test, not provider.test.
        result, prompts = self._run_facility(registered=True)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["filled_fields"], 4)
        disclosure = str(prompts[0])
        self.assertIn("https://merchant.test", disclosure)
        self.assertIn("https://provider.test", disclosure)
        self.assertIn("No live merchant parent is retained", disclosure)
        self.assertTrue(self.page.evaluate(
            '()=>[...document.querySelectorAll("input")].every(e=>e.value.length>0)'
        ))

    def test_root_origin_or_frame_mismatch_never_falls_back(self):
        target = self.standalone(self.semantic_html())
        target.close()
        result, _ = self._run_facility(
            frame_origin="https://provider.test", expected_prompts=0
        )
        self.assertFalse(result["success"], result)
        with self.assertRaises(payment_browser.BindingRefused):
            payment_browser.Target(
                self.capture,
                self.parent,
                "missing-frame",
                "https://merchant.test",
                "https://merchant.test",
                lambda: None,
            )

    def test_root_navigation_during_native_consent_refuses_before_producer(self):
        target = self.standalone(self.semantic_html())
        target.close()
        result, _ = self._run_facility(
            frame_origin="https://merchant.test",
            registered=True,
            before_answer=self.page.reload,
        )
        self.assertFalse(result["success"], result)
        self.assertEqual(result["stage"], "postconsent_target")
        self.assertEqual(result["refusal"], "target_check_failed")

    def test_explicit_root_document_standard_form(self):
        target = self.standalone(
            '<form><input autocomplete="cc-number"><input autocomplete="cc-exp">'
            '<button type="submit">Next</button></form>'
        )
        self.addCleanup(target.close)
        self.assertFalse(target.attached)
        self.assertEqual(
            target.fill(dict(number="4242424242424242", exp_month=12, exp_year=2035))[
                "filled_fields"
            ],
            2,
        )
        self.assertTrue(
            self.page.evaluate(
                '()=>[...document.querySelectorAll("input")].every(e=>e.value.length>0)'
            )
        )


if __name__ == "__main__":
    unittest.main()
