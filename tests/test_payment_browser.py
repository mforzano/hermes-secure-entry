"""Real isolated Chrome + real native CapturedCDP. Synthetic route fixtures only."""

import json
import unittest
from playwright.sync_api import sync_playwright
from secure_entry import payment_browser
from tools.browser_supervisor import SUPERVISOR_REGISTRY


class PaymentBrowserTests(unittest.TestCase):
    def setUp(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(
            channel="chrome",
            headless=True,
            args=[
                "--enable-automation",
                "--remote-debugging-port=0",
                "--site-per-process",
            ],
        )
        self.addCleanup(self.cleanup)
        self.context = self.browser.new_context()
        self.context.route(
            "https://merchant.test/**",
            lambda r: r.fulfill(
                content_type="text/html",
                body='<main><section><iframe src="https://provider.test/pay"></iframe></section><aside>carousel</aside></main>',
            ),
        )
        self.context.route(
            "https://provider.test/**",
            lambda r: r.fulfill(
                content_type="text/html",
                body='<form><input autocomplete="cc-number"><input autocomplete="cc-exp-month"><input autocomplete="cc-exp-year"><input autocomplete="cc-csc"></form>',
            ),
        )
        self.page = self.context.new_page()
        self.page.goto("https://merchant.test/")
        # Playwright's browser websocket is a pipe. Obtain its CDP endpoint from
        # the isolated browser's command line profile, never a user profile.
        session = self.context.new_cdp_session(self.page)
        argv = self.browser.new_browser_cdp_session().send(
            "Browser.getBrowserCommandLine"
        )["arguments"]
        from pathlib import Path
        import urllib.request

        profile = next(
            a.split("=", 1)[1] for a in argv if a.startswith("--user-data-dir=")
        )
        port = (Path(profile) / "DevToolsActivePort").read_text().splitlines()[0]
        with urllib.request.urlopen("http://127.0.0.1:" + port + "/json/version") as r:
            endpoint = json.load(r)["webSocketDebuggerUrl"]
        SUPERVISOR_REGISTRY.get_or_start("synthetic-payment", endpoint)
        self.capture = SUPERVISOR_REGISTRY.capture("synthetic-payment")
        self.parent = session.send("Target.getTargetInfo")["targetInfo"]["targetId"]
        # OOPIF owner identity, not a frame URL/name chosen by the model.
        root = session.send("DOM.getDocument")["root"]["nodeId"]
        node = session.send(
            "DOM.querySelector", {"nodeId": root, "selector": "iframe"}
        )["nodeId"]
        self.frame = session.send("DOM.describeNode", {"nodeId": node})["node"][
            "frameId"
        ]

    def cleanup(self):
        SUPERVISOR_REGISTRY.stop("synthetic-payment")
        self.browser.close()
        self.pw.stop()

    def _run_facility(
        self, choice="once", before_answer=None, issued_card=None, expected_prompts=1
    ):
        from secure_entry.payment import LocalPayment
        from secure_entry.service import Service
        from gateway.session_context import set_session_vars, clear_session_vars
        from hermes_constants import get_hermes_home, profile_name_for_home
        from tools import approval, browser_tool
        from unittest.mock import patch

        tokens = set_session_vars(
            platform="photon",
            chat_type="dm",
            chat_id="synthetic-chat",
            user_id="synthetic-owner",
            session_key="synthetic-key",
            session_id="synthetic-session",
            profile=profile_name_for_home(get_hermes_home()) or "",
            cron_session="",
        )
        self.addCleanup(clear_session_vars, tokens)
        service = Service("https://example.invalid", str(get_hermes_home()), port=0)
        self.addCleanup(service.close)
        prompts = []

        def notify(data):
            prompts.append(data)
            if before_answer:
                before_answer()
            approval.resolve_gateway_approval(
                "synthetic-key", choice, request_id=data["request_id"]
            )

        approval.register_gateway_notify("synthetic-key", notify)
        self.addCleanup(approval.unregister_gateway_notify, "synthetic-key")
        import sys
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as root:
            script = Path(root) / "synthetic_link.py"
            payload = {
                "spend_request_id": "lsrq_synthetic",
                "merchant_url": "https://merchant.test/pay",
                "card": {
                    "number": "4242424242424242",
                    "cvc": "123",
                    "exp_month": 12,
                    "exp_year": 2030,
                },
            }
            if issued_card is not None:
                payload["card"] = issued_card
            script.write_text(
                "import json,sys,pathlib\na=sys.argv[1:]\npathlib.Path(a[6]).write_text("
                + repr(json.dumps(payload))
                + ')\nprint(json.dumps({"id":"lsrq_synthetic","status":"approved"}))\n'
            )
            facility = LocalPayment(service, [sys.executable, str(script)])
            service.payment = facility
            # Deliberately no legacy session metadata: BrowserUse dispatch does
            # not populate the native task-key cache for every route.
            with patch.dict(browser_tool._active_sessions, {}, clear=True):
                result = json.loads(
                    service.payment_fill(
                        {
                            "parent": self.parent,
                            "frame": self.frame,
                            "merchant_origin": "https://merchant.test",
                            "frame_origin": "https://provider.test",
                            "spend_request_id": "lsrq_synthetic",
                        },
                        task_id="synthetic-payment",
                    )
                )
        self.assertEqual(len(prompts), expected_prompts)
        return result, prompts

    def target_for_html(self, html):
        self.page.frames[1].evaluate("html => document.body.innerHTML=html", html)
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
        return target

    def test_writer_initial_mismatch_reaches_native_result_without_values(self):
        self.page.frames[1].evaluate('''document.body.innerHTML=
            '<form><input autocomplete="cc-number"><input autocomplete="cc-exp">' +
            '<input autocomplete="cc-name" value="Synthetic Guest"></form>' ''')
        result, _ = self._run_facility(issued_card={
            "number": "4242424242424242", "exp_month": 12, "exp_year": 2035,
            "billing_address": {"name": "Synthetic Cardholder"},
        })
        self.assertEqual(result, {
            "success": False, "status": "write_unknown", "stage": "write",
            "payment_diagnostic_version": "0.5.5",
            "refusal": "initial_mismatch", "field": "cc-name", "written_fields": 0,
        })

    def test_writer_invalidation_survives_postflight_check(self):
        self.page.frames[1].evaluate('''() => {
            document.body.innerHTML='<form><input autocomplete="cc-number"><input autocomplete="cc-exp"></form>';
            document.querySelector('input').oninput=()=>document.body.setAttribute('data-mutated','yes');
        }''')
        result, _ = self._run_facility()
        self.assertEqual(result.get("refusal"), "invalidated")
        self.assertEqual(result.get("written_fields"), 1)
        self.assertNotIn("field", result)

    def test_writer_reason_categories_execute_generated_javascript(self):
        base = '<form><input autocomplete="cc-number"><input autocomplete="cc-exp">{}</form>'
        values = {"cc-number": "4242424242424242", "cc-exp": "12/35"}
        cases = [
            ("source_missing", "cc-name", '<input autocomplete="cc-name">', "", values, 0),
            ("initial_mismatch", "billing postal-code", '<input autocomplete="billing postal-code" value="10001">', "", {**values, "billing postal-code": "10002"}, 0),
            ("field_changed", "cc-exp", "", 'document.querySelectorAll("input")[1].value="other"', values, 0),
            ("invalidated", None, "", 'document.body.setAttribute("data-changed","yes")', values, 0),
            ("select_mismatch", "billing country", '<select autocomplete="billing country"><option value="">Choose</option><option value="US">Country</option></select>', "", {**values, "billing country": "CA"}, 0),
            ("unchanged", "cc-number", "", 'document.querySelector("input").oninput=e=>e.target.value=""', values, 1),
            ("expiry_format", "cc-exp", "", 'document.querySelectorAll("input")[1].oninput=e=>e.target.value="12/2035"', values, 2),
            ("write_mismatch", "cc-number", "", 'document.querySelector("input").oninput=e=>e.target.value="different"', values, 1),
        ]
        for reason, field, extra, mutate, supplied, count in cases:
            with self.subTest(reason=reason):
                target = self.target_for_html(base.format(extra))
                if mutate:
                    self.page.frames[1].evaluate("() => {" + mutate + ";}")
                result = target.invoke(target.csid, target.cg, "function(v){return this.write(v);}", (supplied,))
                expected = {"written": count, "valid": False, "reason": reason}
                if field:
                    expected["field"] = field
                self.assertEqual(result, expected)
                refusal = payment_browser.WriteRefused(result)
                self.assertEqual(refusal.category, reason)
                self.assertEqual(refusal.field, field)
                self.assertEqual(refusal.written, count)
                target.close()
        target = self.target_for_html(base.format(""))
        self.assertTrue(target.invoke(target.csid, target.cg, "function(v){return this.write(v);}", (values,))["valid"])
        self.assertEqual(target.invoke(target.csid, target.cg, "function(v){return this.write(v);}", (values,)),
                         {"written": 0, "valid": False, "reason": "already_used"})

    def test_framework_value_attribute_reflects_only_current_self_write(self):
        for event in ('input', 'change'):
            for formatted in (False, True):
                with self.subTest(event=event, formatted=formatted):
                    target = self.target_for_html(
                        '<div><input autocomplete="cc-number"><input autocomplete="cc-exp"></div>'
                    )
                    self.page.frames[1].evaluate('''([event, formatted]) => {
                        document.querySelectorAll('input').forEach(e => {
                            e.addEventListener(event, () => {
                                if(formatted && e.autocomplete==='cc-number')
                                    e.value=e.value.match(/.{1,4}/g).join(' ');
                                if(formatted && e.autocomplete==='cc-exp')
                                    e.value=e.value.replace('/', ' / ');
                                e.setAttribute('value', e.value);
                            });
                        });
                    }''', [event, formatted])
                    result = target.fill(dict(number='4242424242424242', exp_month=12, exp_year=2035))
                    self.assertEqual(result['filled_fields'], 2)
                    target.close()

    def test_value_reflection_does_not_authorize_foreign_or_mismatched_mutations(self):
        cases = [
            "n.setAttribute('value','4242424242424241')",
            "n.setAttribute('value','4242424242424241'); n.setAttribute('value',n.value)",
            "n.setAttribute('value',n.value); n.removeAttribute('value')",
            "n.value='4242424242424241'; n.setAttribute('value',n.value)",
            "x.value='12/35'",
            "x.setAttribute('value','12/35')",
            "x.setAttribute('value',''); x.removeAttribute('value')",
            "n.parentNode.setAttribute('value',n.value)",
            "n.setAttribute('data-untrusted','yes')",
            "n.setAttribute('type','tel'); n.removeAttribute('type')",
            "n.setAttribute('name','other'); n.removeAttribute('name')",
            "n.autocomplete='cc-name'; n.autocomplete='cc-number'",
            "n.replaceWith(n.cloneNode(true))",
            "n.parentNode.setAttribute('inert',''); n.parentNode.removeAttribute('inert')",
        ]
        values = {'cc-number': '4242424242424242', 'cc-exp': '12/35'}
        for change in cases:
            with self.subTest(change=change):
                target = self.target_for_html('<div><input autocomplete="cc-number"><input autocomplete="cc-exp"></div>')
                self.page.frames[1].evaluate('''change => {
                    const [n,x]=document.querySelectorAll('input');
                    n.oninput=()=>{n.setAttribute('value',n.value); eval(change)};
                }''', change)
                result = target.invoke(target.csid, target.cg, 'function(v){return this.write(v);}', (values,))
                self.assertFalse(result['valid'])
                self.assertEqual(result['written'], 1)
                target.close()

    def test_value_attribute_mutations_before_or_after_write_stay_sticky(self):
        for change in ("n.setAttribute('value','')", "n.setAttribute('value','bad'); n.removeAttribute('value')"):
            with self.subTest(change=change):
                target = self.target_for_html('<div><input autocomplete="cc-number"><input autocomplete="cc-exp"></div>')
                self.page.frames[1].evaluate('() => {const n=document.querySelector("input"); '+change+'}')
                result = target.invoke(target.csid, target.cg, 'function(v){return this.write(v);}',
                                       ({'cc-number': '4242424242424242', 'cc-exp': '12/35'},))
                self.assertEqual(result, {'written': 0, 'valid': False, 'reason': 'invalidated'})
                target.close()
        target = self.target_for_html('<div><input autocomplete="cc-number"><input autocomplete="cc-exp"></div>')
        target.fill(dict(number='4242424242424242', exp_month=12, exp_year=2035))
        self.page.frames[1].evaluate('''() => {const n=document.querySelector('input'); n.setAttribute('value',n.value)}''')
        with self.assertRaises(ValueError):
            target.check()

    def test_reflected_expiry_still_requires_exact_month_and_year(self):
        for value in ('11/35', '12/36', '12/2035', '12/35x'):
            with self.subTest(value=value):
                target = self.target_for_html('<div><input autocomplete="cc-number"><input autocomplete="cc-exp"><input autocomplete="cc-csc"></div>')
                self.page.frames[1].evaluate('''value => {
                    const e=document.querySelector('[autocomplete=cc-exp]');
                    e.oninput=()=>{e.value=value; e.setAttribute('value',e.value)};
                }''', value)
                with self.assertRaises(ValueError):
                    target.fill(dict(number='4242424242424242', exp_month=12, exp_year=2035, cvc='987'))
                self.assertEqual(self.page.frames[1].locator('[autocomplete=cc-csc]').input_value(), '')
                target.close()

    def test_writer_diagnostics_discard_untrusted_values(self):
        failure = payment_browser.WriteRefused({
            "reason": "SYNTHETIC_PRIVATE", "field": "SYNTHETIC_PRIVATE",
            "written": True, "value": "SYNTHETIC_PRIVATE",
        })
        self.assertEqual(failure.category, "write_failed")
        self.assertIsNone(failure.field)
        self.assertIsNone(failure.written)
        self.assertEqual(str(failure), "write_unknown")

    def test_binding_refusal_categories_are_safe(self):
        parent, frame = self.parent, self.frame
        for category in ("selected_parent", "frame_lineage", "form_layout"):
            self.parent, self.frame = parent, frame
            if category == "selected_parent":
                self.parent = "missing-private-target"
            elif category == "frame_lineage":
                self.frame = "missing-private-frame"
            else:
                self.page.frames[1].evaluate(
                    'document.body.innerHTML="<div>unsupported</div>"'
                )
            result, _ = self._run_facility(expected_prompts=0)
            self.assertEqual(
                result,
                dict(
                    success=False,
                    status="refused",
                    stage="target_binding",
                    refusal=category,
                    payment_diagnostic_version="0.5.5",
                ),
            )

    def test_parent_unrelated_mutations_preserve_retained_iframe(self):
        target = self.target_for_html(
            '<form><input autocomplete="cc-number"><input autocomplete="cc-exp"></form>'
        )
        self.page.evaluate("""() => {
            document.title='new title'; document.body.setAttribute('aria-busy','false');
            document.querySelector('iframe').title='accessible payment';
            document.querySelector('section').setAttribute('aria-label','Payment');
            document.querySelector('aside').innerHTML='<article>next promotion</article>';
            document.querySelector('main').appendChild(document.createElement('footer'));
        }""")
        other = self.context.new_page()
        other.goto("https://merchant.test/other")
        other.evaluate("document.body.appendChild(document.createElement('div'))")
        target.check()
        self.assertEqual(
            target.fill(dict(number="4242424242424242", exp_month=12, exp_year=2030))[
                "filled_fields"
            ],
            2,
        )

    def test_parent_lineage_security_mutations_are_sticky(self):
        for change in (
            "f.remove()",
            "document.querySelector('aside').appendChild(f)",
            "const p=f.parentNode; p.remove(); document.body.appendChild(p)",
            "f.setAttribute('src', 'https://provider.test/changed'); f.setAttribute('src', 'https://provider.test/pay')",
            "f.setAttribute('sandbox','allow-scripts'); f.removeAttribute('sandbox')",
            "f.parentNode.setAttribute('inert',''); f.parentNode.removeAttribute('inert')",
        ):
            with self.subTest(change=change):
                self.page.goto("https://merchant.test/")
                self.page.frames[1].wait_for_load_state()
                session = self.context.new_cdp_session(self.page)
                root = session.send("DOM.getDocument")["root"]["nodeId"]
                node = session.send(
                    "DOM.querySelector", {"nodeId": root, "selector": "iframe"}
                )["nodeId"]
                self.frame = session.send("DOM.describeNode", {"nodeId": node})["node"][
                    "frameId"
                ]
                self.page.frames[1].wait_for_load_state()
                target = self.target_for_html(
                    '<form><input autocomplete="cc-number"><input autocomplete="cc-exp"></form>'
                )
                self.page.evaluate(
                    '() => {const f=document.querySelector("iframe"); ' + change + "}"
                )
                with self.assertRaises(ValueError):
                    target.check()
                target.close()

    def test_formless_cohesive_payment_widget(self):
        target = self.target_for_html(
            '<div><section><input autocomplete="cc-number"></section>'
            '<section><input autocomplete="cc-exp"></section></div>'
        )
        self.assertEqual(
            target.fill(dict(number="4242424242424242", exp_month=12, exp_year=2030))[
                "filled_fields"
            ],
            2,
        )

    def test_formless_unrelated_groups_refused(self):
        for html in [
            '<div><input autocomplete="cc-number"></div><div><input autocomplete="cc-exp"></div>',
            '<div><input autocomplete="cc-number"><input autocomplete="cc-exp"></div><div><input autocomplete="billing postal-code"></div>',
            '<div><input autocomplete="cc-number"><input autocomplete="cc-exp"></div>'
            * 2,
        ]:
            with self.subTest(html=html), self.assertRaises(ValueError):
                self.target_for_html(html)

    def test_formless_retained_container_replacement_refused(self):
        target = self.target_for_html(
            '<div><input autocomplete="cc-number"><input autocomplete="cc-exp"></div>'
        )
        self.page.frames[1].evaluate(
            'document.querySelector("div").outerHTML=document.querySelector("div").outerHTML'
        )
        with self.assertRaises(ValueError):
            target.check()

    def test_unsectioned_postal_code_with_combined_expiry_mask(self):
        target = self.target_for_html(
            '<div><input type="text" autocomplete="cc-number">'
            '<input type="text" autocomplete="cc-exp">'
            '<input type="text" autocomplete="cc-csc">'
            '<input type="text" autocomplete="postal-code"></div>'
        )
        frame = self.page.frames[1]
        before = frame.locator('input').evaluate_all(
            'fields => fields.map(e => e.getAttribute("autocomplete"))'
        )
        frame.evaluate('''() => {
          const e=document.querySelector('[autocomplete=cc-exp]');
          e.addEventListener('input',()=>{e.value=e.value.replace('/', ' / ')});
        }''')
        result = target.fill(dict(number="4242424242424242", exp_month=12,
            exp_year=2035, cvc="987", billing_address={"postal_code":"10001"}))
        self.assertEqual(result['filled_fields'], 4)
        self.assertEqual(frame.locator('[autocomplete=cc-exp]').input_value(), '12 / 35')
        self.assertEqual(frame.locator('[autocomplete=cc-csc]').input_value(), '987')
        self.assertEqual(frame.locator('[autocomplete=postal-code]').input_value(), '10001')
        self.assertEqual(frame.locator('input').evaluate_all(
            'fields => fields.map(e => e.getAttribute("autocomplete"))'), before)

    def test_unsectioned_postal_code_keeps_strict_control_admission(self):
        for extra in (
            '<input autocomplete="postal-code"><input autocomplete="billing postal-code">',
            '<input autocomplete="postal-code"><input autocomplete="postal-code">',
            '<input autocomplete="shipping postal-code">',
            '<input autocomplete="section-other postal-code">',
            '<input autocomplete="country">',
            '<input autocomplete="address-line1">',
            '<input autocomplete="postal-code" type="hidden">',
            '<select autocomplete="postal-code"><option>10001</option></select>',
            '<textarea autocomplete="postal-code"></textarea>',
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.target_for_html('<div><input autocomplete="cc-number">'
                    '<input autocomplete="cc-exp"><input autocomplete="cc-csc">'+extra+'</div>')

    def test_unsectioned_postal_code_retains_original_attribute_authority(self):
        target = self.target_for_html('<div><input autocomplete="cc-number">'
            '<input autocomplete="cc-exp"><input autocomplete="postal-code"></div>')
        self.page.frames[1].evaluate('''() => {
          const e=document.querySelector('[autocomplete=postal-code]');
          e.autocomplete='billing postal-code';
          e.autocomplete='postal-code';
        }''')
        with self.assertRaises(ValueError):
            target.check()
        self.assertEqual(self.page.frames[1].locator('[autocomplete=cc-number]').input_value(), '')

    def test_unsectioned_postal_code_conflict_uses_canonical_diagnostic(self):
        target = self.target_for_html('<div><input autocomplete="cc-number">'
            '<input autocomplete="cc-exp"><input autocomplete="postal-code" value="99999"></div>')
        with self.assertRaises(payment_browser.WriteRefused) as caught:
            target.fill(dict(number="4242424242424242", exp_month=12,
                exp_year=2035, billing_address={"postal_code":"10001"}))
        self.assertEqual(caught.exception.category, 'initial_mismatch')
        self.assertEqual(caught.exception.field, 'billing postal-code')
        self.assertEqual(caught.exception.written, 0)

    def test_combined_expiry_input_mask_preserves_exact_month_and_year(self):
        target = self.target_for_html(
            '<div><input autocomplete="cc-number" required><input autocomplete="cc-exp" required></div>'
        )
        self.page.frames[1].evaluate('''() => {
          window.expiryEvents=[];
          const e=document.querySelector('[autocomplete=cc-exp]');
          e.addEventListener('input',()=>{window.expiryEvents.push('input'); e.value=e.value.replace('/', ' / ')});
          e.addEventListener('change',()=>window.expiryEvents.push('change'));
        }''')
        result = target.fill(dict(number="4242424242424242", exp_month=12, exp_year=2035))
        self.assertEqual(result['filled_fields'], 2)
        self.assertEqual(self.page.frames[1].locator('[autocomplete=cc-exp]').input_value(), '12 / 35')
        self.assertEqual(self.page.frames[1].evaluate('window.expiryEvents'), ['input', 'change'])

    def test_unsupplied_billing_preservation_does_not_bypass_required_or_identity(self):
        for preserve, extra, billing in (
            (True, '<input autocomplete="billing address-line1" required>', {}),
            (True, '<input autocomplete="billing postal-code" value="99999">', {'postal_code':'10001'}),
            (True, '<input autocomplete="cc-name" value="Other Person">', {'name':'Synthetic Person'}),
            (False, '<input autocomplete="billing address-line1" value="1 Test St">', {}),
        ):
            with self.subTest(preserve=preserve, extra=extra):
                target = self.target_for_html('<div><input autocomplete="cc-number"><input autocomplete="cc-exp">'+extra+'</div>')
                with self.assertRaises(ValueError):
                    target.fill(dict(number='4242424242424242', exp_month=12, exp_year=2035,
                        billing_address=billing, preserve_unsupplied_billing=preserve))
                self.assertEqual(self.page.frames[1].locator('[autocomplete=cc-number]').input_value(), '')
                target.close()

    def test_invalid_combined_expiry_mask_is_refused(self):
        for value in ('11 / 35', '12 / 36', '12 / 35x', '1235', '12/2035'):
            with self.subTest(value=value):
                target = self.target_for_html('<div><input autocomplete="cc-number"><input autocomplete="cc-exp"><input autocomplete="cc-csc"></div>')
                self.page.frames[1].evaluate('''value => document.querySelector('[autocomplete=cc-exp]').addEventListener('input',e=>e.target.value=value)''', value)
                with self.assertRaises(ValueError):
                    target.fill(dict(number='4242424242424242', exp_month=12, exp_year=2035, cvc='987'))
                self.assertEqual(self.page.frames[1].locator('[autocomplete=cc-csc]').input_value(), '')
                target.close()

    def test_combined_expiry_without_merchant_cvc(self):
        target = self.target_for_html(
            '<form><input autocomplete="cc-number"><input autocomplete="cc-exp"></form>'
        )
        result = target.fill(
            dict(number="4242424242424242", exp_month=12, exp_year=2030, cvc="123")
        )
        self.assertEqual(result, dict(success=True, status="filled", filled_fields=2))
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-exp]").input_value(), "12/30"
        )

    def test_formless_billing_selects_react_tracker(self):
        self.test_billing_selects_prefilled_and_react_property_tracker(formless=True)

    def test_billing_selects_prefilled_and_react_property_tracker(self, formless=False):
        html = """<form><input autocomplete="cc-number"><input autocomplete="cc-exp">
        <input autocomplete="cc-name"><select autocomplete="billing country"><option value="US" selected>United States</option></select>
        <input autocomplete="billing address-line1"><input autocomplete="billing address-line2">
        <input autocomplete="billing address-level2"><select autocomplete="billing address-level1"><option value="NY" selected>New York</option></select>
        <input autocomplete="billing postal-code"><input autocomplete="billing tel" value="2125550100"></form>"""
        if formless:
            html = html.replace("<form>", "<div>").replace("</form>", "</div>")
        self.page.frames[1].evaluate("html => document.body.innerHTML=html", html)
        self.page.frames[
            1
        ].evaluate("""() => {window.updates=0; for(const e of document.querySelectorAll('input')) {
          let tracked=e.value; Object.defineProperty(e,'value',{get(){return Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').get.call(this)},set(v){tracked=v;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(this,v)}});
          e.addEventListener('input',()=>{if(e.value!==tracked){window.updates++;tracked=e.value}});
        }}""")
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.addCleanup(target.close)
        result = target.fill(
            dict(
                number="4242424242424242",
                exp_month=12,
                exp_year=2030,
                billing_address=dict(
                    name="Synthetic Person",
                    country="US",
                    line1="1 Test St",
                    line2="",
                    city="Test City",
                    state="NY",
                    postal_code="10001",
                ),
            )
        )
        self.assertEqual(result, dict(success=True, status="filled", filled_fields=6))
        self.assertEqual(self.page.frames[1].evaluate("window.updates"), 6)
        self.assertNotIn("Synthetic", json.dumps(result))

    def test_pan_brand_and_sibling_validation_updates_preserve_authority(self):
        target = self.target_for_html(
            '<form><section><input autocomplete="cc-number"><span id="brand">Card</span>'
            '<span id="validation" class="pending">Pending</span></section>'
            '<section><input autocomplete="cc-exp"></section></form>'
        )
        self.assertNotEqual(target.csid, target.psid)  # actual Chrome OOPIF
        self.page.frames[1].evaluate('''() => {
          document.querySelector('input').addEventListener('input', e => {
            document.querySelector('#brand').innerHTML='<svg class="visa"><title>Visa</title></svg>';
            const validation=document.querySelector('#validation');
            validation.className='valid';
            validation.firstChild.data='Valid card';
            e.target.closest('section').classList.add('validated');
          });
        }''')
        self.assertEqual(target.fill(dict(number="4242424242424242", exp_month=12,
                                         exp_year=2035))['filled_fields'], 2)
        self.assertEqual(self.page.frames[1].locator('#validation').inner_text(), 'Valid card')

    def test_child_authority_mutations_remain_sticky_after_pan(self):
        changes = [
            'const p=e.parentNode; e.remove(); p.appendChild(e)',
            'const p=e.parentNode; document.body.appendChild(e); p.appendChild(e)',
            'const p=e.parentNode, g=p.parentNode; p.remove(); g.appendChild(p)',
            'const f=e.form, p=f.parentNode; f.remove(); p.appendChild(f)',
            "e.outerHTML=e.outerHTML",
            "const n=document.createElement('input'); e.after(n); n.remove()",
            "const n=document.createElement('form'); document.body.appendChild(n); n.remove()",
            "e.parentNode.className='hidden'; e.parentNode.style.display='none'",
        ]
        for selector, attribute, value in (
            ('input', 'autocomplete', 'cc-csc'), ('input', 'type', 'hidden'),
            ('input', 'name', 'different'), ('input', 'id', 'different'),
            ('input', 'form', 'different'), ('input', 'disabled', ''),
            ('input', 'readonly', ''), ('input', 'required', ''),
            ('input', 'pattern', '.*'), ('input', 'maxlength', '1'),
            ('section', 'inert', ''), ('section', 'hidden', ''),
            ('section', 'style', 'display:none'), ('form', 'action', '/changed'),
            ('form', 'method', 'post'), ('form', 'id', 'changed'),
        ):
            changes.append(f'''const n=document.querySelector({json.dumps(selector)});
                const old=n.getAttribute({json.dumps(attribute)});
                n.setAttribute({json.dumps(attribute)},{json.dumps(value)});
                if(old===null)n.removeAttribute({json.dumps(attribute)});
                else n.setAttribute({json.dumps(attribute)},old);''')
        for change in changes:
            with self.subTest(change=change):
                target = self.target_for_html(
                    '<form><section><input autocomplete="cc-number"></section>'
                    '<section><input autocomplete="cc-exp"></section></form>'
                )
                self.page.frames[1].evaluate('''change => {
                  document.querySelector('input').addEventListener('input', event => {
                    const e=event.target; new Function('e',change)(e);
                  });
                }''', change)
                with self.assertRaises(payment_browser.WriteRefused) as caught:
                    target.fill(dict(number="4242424242424242", exp_month=12, exp_year=2035))
                self.assertEqual(caught.exception.category, 'invalidated')
                self.assertEqual(caught.exception.written, 1)
                self.assertEqual(self.page.frames[1].locator('[autocomplete=cc-exp]').input_value(), '')
                target.close()

    def test_benign_validation_attributes_and_pan_grouping(self):
        self.page.frames[
            1
        ].evaluate("""() => document.querySelector('input').addEventListener('input',e=>{
          e.target.setAttribute('aria-invalid','false');
          e.target.value=e.target.value.replace(/(.{4})(?=.)/g,'$1 ');
        })""")
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.addCleanup(target.close)
        self.assertEqual(
            target.fill(
                dict(number="4242424242424242", exp_month=12, exp_year=2030, cvc="123")
            )["filled_fields"],
            4,
        )

    def test_ambiguous_and_unrelated_controls_refused(self):
        base = '<input autocomplete="cc-number"><input autocomplete="cc-exp">'
        for extra in [
            '<input autocomplete="cc-number">',
            '<input autocomplete="cc-exp-month">',
            '<input autocomplete="email">',
            '<select autocomplete="shipping country"></select>',
            '<input autocomplete="billing postal-code"><input autocomplete="billing postal-code">',
        ]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.target_for_html("<form>" + base + extra + "</form>")

    def test_mismatching_prefilled_billing_refuses_before_any_write(self):
        target = self.target_for_html(
            '<form><input autocomplete="cc-number"><input autocomplete="cc-exp"><input autocomplete="billing postal-code" value="99999"></form>'
        )
        with self.assertRaises(ValueError):
            target.fill(
                dict(
                    number="4242424242424242",
                    exp_month=12,
                    exp_year=2030,
                    billing_address=dict(postal_code="10001"),
                )
            )
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-number]").input_value(), ""
        )

    def test_value_only_event_tampering_of_later_target_refused(self):
        self.page.frames[1].evaluate(
            """() => document.querySelector('input').addEventListener('input',()=>document.querySelector('[autocomplete=cc-exp-year]').value='attacker')"""
        )
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.addCleanup(target.close)
        with self.assertRaises(ValueError):
            target.fill(
                dict(number="4242424242424242", exp_month=12, exp_year=2030, cvc="123")
            )
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-exp-month]").input_value(), ""
        )

    def test_parent_mutation_at_dispatch_is_unknown_not_atomic_no_write(self):
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.addCleanup(target.close)
        real = target.invoke

        def invoke(sid, obj, function, args=()):
            if "this.write" in function:
                self.page.evaluate("document.querySelector('iframe').name='changed'")
            return real(sid, obj, function, args)

        target.invoke = invoke
        with self.assertRaises(ValueError):
            target.fill(
                dict(number="4242424242424242", exp_month=12, exp_year=2030, cvc="123")
            )
        self.assertTrue(target.started)
        # CDP cannot atomically check parent JS and write another OOPIF process.
        # This explicitly records the limitation, not a no-disclosure guarantee.
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-number]").input_value(),
            "4242424242424242",
        )

    def test_last_event_tampering_of_prior_target_refused(self):
        self.page.frames[1].evaluate(
            """() => document.querySelector('[autocomplete=cc-csc]').addEventListener('change',()=>document.querySelector('[autocomplete=cc-number]').value='9999')"""
        )
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.addCleanup(target.close)
        with self.assertRaises(ValueError):
            target.fill(
                dict(number="4242424242424242", exp_month=12, exp_year=2030, cvc="123")
            )

    def test_native_issued_billing_redacted_individually_before_fill(self):
        from agent.redact import redact_registered_vault_values

        self.page.frames[1].evaluate(
            """() => document.body.innerHTML='<form><input autocomplete="cc-number"><input autocomplete="cc-exp"><input autocomplete="cc-name"><input autocomplete="billing address-line1"></form>' """
        )
        card = dict(
            number="4242424242424242",
            exp_month=12,
            exp_year=2030,
            billing_address=dict(
                name="Unique Synthetic Cardholder",
                line1="1 Private Synthetic Street",
                country="US",
            ),
        )
        result, _ = self._run_facility(issued_card=card)
        self.assertEqual(
            result,
            dict(
                success=True,
                status="filled",
                filled_fields=4,
                payment_diagnostic_version="0.5.5",
            ),
        )
        self.assertNotIn(
            "Unique Synthetic Cardholder",
            redact_registered_vault_values("Unique Synthetic Cardholder"),
        )
        self.assertNotIn(
            "1 Private Synthetic Street",
            redact_registered_vault_values("1 Private Synthetic Street"),
        )
        self.assertNotIn("12/30", redact_registered_vault_values("12/30"))

    def test_matching_prefilled_cardholder_is_preserved(self):
        target = self.target_for_html(
            '<form><input autocomplete="cc-number"><input autocomplete="cc-exp"><input autocomplete="cc-name" value="Synthetic Person"></form>'
        )
        self.assertEqual(
            target.fill(
                dict(
                    number="4242424242424242",
                    exp_month=12,
                    exp_year=2030,
                    billing_address=dict(name="Synthetic Person"),
                )
            )["filled_fields"],
            2,
        )

    def test_empty_billing_selects_use_native_change_events(self):
        target = self.target_for_html(
            '<form><input autocomplete="cc-number"><input autocomplete="cc-exp"><select autocomplete="billing country"><option value=""></option><option value="US">United States</option></select><select autocomplete="billing address-level1"><option value=""></option><option value="NY">New York</option></select></form>'
        )
        self.page.frames[1].evaluate(
            "window.changes=0;document.querySelectorAll('select').forEach(e=>e.addEventListener('change',()=>window.changes++))"
        )
        result = target.fill(
            dict(
                number="4242424242424242",
                exp_month=12,
                exp_year=2030,
                billing_address=dict(country="US", state="NY"),
            )
        )
        self.assertEqual(result["filled_fields"], 4)
        self.assertEqual(self.page.frames[1].evaluate("window.changes"), 2)

    def test_invalid_pan_mask_content_refused(self):
        self.page.frames[1].evaluate(
            "document.querySelector('input').addEventListener('input',e=>e.target.value+='x')"
        )
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.addCleanup(target.close)
        with self.assertRaises(ValueError):
            target.fill(
                dict(number="4242424242424242", exp_month=12, exp_year=2030, cvc="123")
            )
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-exp-month]").input_value(), ""
        )

    def _dispatched_browseruse_fill(self, session="", hybrid=False, nonprimary=False):
        """Real harness process + native attach/capture; only browser provisioning
        is replaced with this test's already-launched disposable Chrome endpoint.
        No generated receipt, plugin authority, live browser or live IPC runtime.
        """
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from tools import browser_use_cli as bu

        endpoint = self.capture.cdp_url
        SUPERVISOR_REGISTRY.stop("synthetic-payment")
        self.assertFalse(self.capture.is_valid())
        with tempfile.TemporaryDirectory() as directory:
            base = bu._base_subprocess_env()
            for key in list(base):
                if key.startswith(("BU_", "BH_", "BROWSER_")):
                    del base[key]
            base.update(
                BH_HOME=str(Path(directory) / "home"),
                BH_RUNTIME_DIR=str(Path(directory) / "runtime"),
                BH_RUNTIME_DIR_SHARED="1",
                BU_AUTOSPAWN="0",
            )

            def provision(env, task_id, session_name="", sidecar=False):
                self.assertEqual(sidecar, hybrid)
                bu._set_cdp_env(env, endpoint)
                env[bu._PRIVATE_BROWSER_SENTINEL] = "1"
                env[bu._BOT_DESKTOP_BROWSER_SENTINEL] = "1"
                return None

            with (
                patch.object(bu, "_base_subprocess_env", return_value=base.copy()),
                patch.object(bu, "_real_profile_consented", return_value=False),
                patch.object(bu, "_resolve_local_engine_cdp", side_effect=provision),
                patch("tools.browser_tool_cdp._get_cdp_override", return_value=""),
                patch("tools.browser_tool_cdp._get_cdp_override_raw", return_value=""),
                patch(
                    "tools.browser_tool_cloud._get_cloud_provider",
                    return_value=object() if hybrid else None,
                ),
                patch(
                    "tools.browser_tool_cloud._auto_local_for_private_urls",
                    return_value=True,
                ),
                patch.object(bu, "_read_browser_cfg", return_value={}),
            ):
                try:
                    # A private URL literal selects the genuine hybrid predicate;
                    # the code reads fixture metadata only, never field values.
                    code = '# http://127.0.0.1/fixture\nprint("fixture-dispatched", cdp("Browser.getVersion")["product"])'
                    result = bu.browser_exec(
                        code, session=session, task_id="synthetic-payment", timeout_s=45
                    )
                    if isinstance(result, str):
                        result = json.loads(result)
                    self.assertTrue(result.get("success"), result)
                    self.assertIn("fixture-dispatched", result["output"])
                    self.assertEqual(
                        bu._exec_route_is_sidecar[
                            bu._backend_cache_key("synthetic-payment", session)
                        ],
                        hybrid,
                    )
                    capture = SUPERVISOR_REGISTRY.capture("synthetic-payment")
                    self.assertTrue(capture.is_valid())
                    self.assertEqual(capture.cdp_url, endpoint)
                    self.capture = capture
                    if nonprimary:
                        original = self.page
                        self.page = self.context.new_page()
                        self.page.goto("https://merchant.test/second")
                        page_session = self.context.new_cdp_session(self.page)
                        self.parent = page_session.send("Target.getTargetInfo")[
                            "targetInfo"
                        ]["targetId"]
                        root = page_session.send("DOM.getDocument")["root"]["nodeId"]
                        node = page_session.send(
                            "DOM.querySelector", {"nodeId": root, "selector": "iframe"}
                        )["nodeId"]
                        self.frame = page_session.send(
                            "DOM.describeNode", {"nodeId": node}
                        )["node"]["frameId"]
                        selected = bu.browser_exec(
                            "switch_tab("
                            + repr(self.parent)
                            + ')\nprint("selected-exact-parent", current_tab()["targetId"] == '
                            + repr(self.parent) + ')',
                            session=session,
                            task_id="synthetic-payment",
                            timeout_s=45,
                        )
                        if isinstance(selected, str):
                            selected = json.loads(selected)
                        self.assertTrue(selected.get("success"), selected)
                        # Random target IDs can contain registered synthetic CVC
                        # substrings. Compare inside the harness, before redaction.
                        self.assertIn('selected-exact-parent True', selected["output"])
                        default = capture.call(
                            "Target.getTargetInfo", session_id=capture.page_session_id
                        )["result"]["targetInfo"]["targetId"]
                        self.assertNotEqual(default, self.parent)
                    filled, _ = self._run_facility()
                    self.assertTrue(filled["success"], filled)
                    if nonprimary:
                        self.assertEqual(
                            original.frames[1]
                            .locator("[autocomplete=cc-number]")
                            .input_value(),
                            "",
                        )
                        self.assertEqual(
                            self.page.frames[1]
                            .locator("[autocomplete=cc-number]")
                            .input_value(),
                            "4242424242424242",
                        )
                finally:
                    import time

                    # Native best-effort cleanup can return before Windows closes
                    # the daemon log handle. Exercise reload directly and wait
                    # for the exact disposable runtime to release its files.
                    name = (
                        bu._sidecar_daemon_name(session)
                        if hybrid
                        else (session or "default")
                    )
                    import psutil

                    # Keep an identity-checked handle to this test's daemon.
                    # Harness reload has a Windows port-file deletion race;
                    # cleanup must not leave a disposable process/log handle.
                    pidfile = Path(directory) / "runtime" / f"bu-{name}.pid"
                    daemon = None
                    if pidfile.exists():
                        record = json.loads(pidfile.read_text())
                        daemon = psutil.Process(
                            int(record["pid"] if isinstance(record, dict) else record)
                        )
                        self.assertEqual(
                            daemon.cmdline()[1:3], ["-m", "browser_harness.daemon"]
                        )
                    bu._run_cli_killing_process_group(
                        [*bu._find_cli(), "--reload"], "", {**base, "BU_NAME": name}, 20
                    )
                    if daemon is not None:
                        try:
                            daemon.wait(timeout=3)
                        except psutil.TimeoutExpired:
                            daemon.terminate()
                            daemon.wait(timeout=10)
                    for _ in range(100):
                        try:
                            for logfile in (Path(directory) / "home" / "tmp").glob(
                                "*.log"
                            ):
                                logfile.unlink()
                            break
                        except PermissionError:
                            time.sleep(0.1)
                    bu._driven_daemons.discard(name)

    def test_nonprimary_attachment_cleanup_and_wrong_frame_lineage(self):
        other = self.context.new_page()
        other.goto("https://merchant.test/other")
        session = self.context.new_cdp_session(other)
        parent = session.send("Target.getTargetInfo")["targetInfo"]["targetId"]
        with self.assertRaises(payment_browser.BindingRefused) as caught:
            payment_browser.Target(
                self.capture,
                parent,
                self.frame,
                "https://merchant.test",
                "https://provider.test",
                lambda: None,
            )
        self.assertEqual(caught.exception.category, "frame_lineage")
        root = session.send("DOM.getDocument")["root"]["nodeId"]
        node = session.send(
            "DOM.querySelector", {"nodeId": root, "selector": "iframe"}
        )["nodeId"]
        frame = session.send("DOM.describeNode", {"nodeId": node})["node"]["frameId"]
        target = payment_browser.Target(
            self.capture,
            parent,
            frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.assertTrue(target.parent_attached)
        sessions = (target.psid, target.csid)
        target.close()
        for sid in sessions:
            with self.assertRaises(RuntimeError):
                self.capture.call("Target.getTargetInfo", session_id=sid)
        self.assertEqual(
            self.capture.call(
                "Target.getTargetInfo", session_id=self.capture.page_session_id
            )["result"]["targetInfo"]["targetId"],
            self.parent,
        )

    def test_nonprimary_browseruse_selected_exact_parent(self):
        self._dispatched_browseruse_fill(session="synthetic-multitab", nonprimary=True)

    def test_default_browseruse_dispatch_to_existing_public_capture_fill(self):
        self._dispatched_browseruse_fill()

    def test_named_browseruse_dispatch_to_existing_public_capture_fill(self):
        self._dispatched_browseruse_fill(session="synthetic-checkout")

    def test_hybrid_browseruse_dispatch_to_existing_public_capture_fill(self):
        self._dispatched_browseruse_fill(session="synthetic-hybrid", hybrid=True)

    def test_registered_facility_native_consent_private_file_to_real_iframe(self):
        from agent.redact import redact_registered_vault_values

        result, prompts = self._run_facility()
        self.assertEqual(
            result,
            {
                "success": True,
                "status": "filled",
                "filled_fields": 4,
                "payment_diagnostic_version": "0.5.5",
            },
        )
        self.assertIn("https://merchant.test", prompts[0]["command"])
        self.assertIn("https://provider.test", prompts[0]["command"])
        self.assertNotIn(
            "4242424242424242", redact_registered_vault_values("4242424242424242")
        )
        self.assertNotIn("123", redact_registered_vault_values("123"))
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-number]").input_value(),
            "4242424242424242",
        )

    def test_takeover_after_write_reports_unknown_not_nothing_written(self):
        from unittest.mock import patch
        from tools.bot_desktop import lease

        original = payment_browser.Target.fill

        def takeover(target, card):
            result = original(target, card)
            lease.acquire("synthetic-viewer")
            return result

        self.addCleanup(lease.release, "synthetic-viewer")
        with patch.object(payment_browser.Target, "fill", takeover):
            result, _ = self._run_facility()
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "write_unknown")

    def test_supervisor_replacement_during_consent_refuses_before_retrieval(self):
        endpoint = self.capture.cdp_url

        def replace():
            SUPERVISOR_REGISTRY.stop("synthetic-payment")
            SUPERVISOR_REGISTRY.get_or_start("synthetic-payment", endpoint)

        result, _ = self._run_facility(before_answer=replace)
        self.assertFalse(result["success"])
        self.assertEqual(result["stage"], "postconsent_current")
        self.assertEqual(result["refusal"], "browser_capture_invalid")
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-number]").input_value(), ""
        )

    def test_native_takeover_during_consent_refuses_before_retrieval(self):
        from tools.bot_desktop import lease

        self.addCleanup(lease.release, "synthetic-viewer")
        result, _ = self._run_facility(
            before_answer=lambda: lease.acquire("synthetic-viewer")
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["stage"], "postconsent_current")
        self.assertEqual(result["refusal"], "takeover_refused")
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-number]").input_value(), ""
        )

    def test_supervisor_replacement_after_write_reports_unknown(self):
        from unittest.mock import patch

        original = payment_browser.Target.fill
        endpoint = self.capture.cdp_url

        def replace(target, card):
            result = original(target, card)
            SUPERVISOR_REGISTRY.stop("synthetic-payment")
            SUPERVISOR_REGISTRY.get_or_start("synthetic-payment", endpoint)
            return result

        with patch.object(payment_browser.Target, "fill", replace):
            result, _ = self._run_facility()
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "write_unknown")
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-number]").input_value(),
            "4242424242424242",
        )

    def test_native_decline_keeps_card_fields_empty(self):
        result, _ = self._run_facility("deny")
        self.assertEqual(
            result,
            {
                "success": False,
                "status": "payment_declined",
                "payment_diagnostic_version": "0.5.5",
            },
        )
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-number]").input_value(), ""
        )

    def test_navigation_while_native_consent_waits_refuses_before_retrieval(self):
        result, _ = self._run_facility(
            before_answer=lambda: self.page.frames[1].goto(
                "https://provider.test/reload"
            )
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["stage"], "postconsent_target")
        self.assertEqual(result["refusal"], "target_check_failed")
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-number]").input_value(), ""
        )

    def test_same_origin_reload_never_retargets_new_document(self):
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.addCleanup(target.close)
        self.page.frames[1].goto("https://provider.test/reloaded")
        with self.assertRaises(Exception):
            target.fill(
                {
                    "number": "4242424242424242",
                    "cvc": "123",
                    "exp_month": 12,
                    "exp_year": 2030,
                }
            )
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-number]").input_value(), ""
        )

    def test_reverted_parent_mutation_is_sticky_refusal(self):
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.addCleanup(target.close)
        self.page.evaluate(
            "document.querySelector('iframe').setAttribute('name','changed');document.querySelector('iframe').removeAttribute('name')"
        )
        with self.assertRaises(ValueError):
            target.check()
        self.assertFalse(target.started)

    def test_child_input_event_replacement_stops_remaining_writes(self):
        self.page.frames[1].evaluate(
            "document.querySelector('input').addEventListener('input',()=>document.querySelector('[autocomplete=cc-csc]').replaceWith(document.createElement('input')))"
        )
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.addCleanup(target.close)
        with self.assertRaises(ValueError):
            target.fill(
                {
                    "number": "4242424242424242",
                    "cvc": "123",
                    "exp_month": 12,
                    "exp_year": 2030,
                }
            )
        self.assertTrue(target.started)
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-exp-month]").input_value(), ""
        )

    def test_parent_navigation_after_last_preflight_before_secret_send(self):
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.addCleanup(target.close)
        real = target.invoke

        def invoke(sid, obj, function, args=()):
            if "this.write" in function:
                self.page.goto("https://merchant.test/reloaded")
            return real(sid, obj, function, args)

        target.invoke = invoke
        with self.assertRaises(Exception):
            target.fill(
                {
                    "number": "4242424242424242",
                    "cvc": "123",
                    "exp_month": 12,
                    "exp_year": 2030,
                }
            )
        self.assertEqual(
            self.page.frames[1].locator("[autocomplete=cc-number]").input_value(), ""
        )

    def test_reconnect_invalidates_original_transport(self):
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        self.addCleanup(target.close)
        endpoint = self.capture.cdp_url
        SUPERVISOR_REGISTRY.stop("synthetic-payment")
        SUPERVISOR_REGISTRY.get_or_start("synthetic-payment", endpoint)
        with self.assertRaises(ValueError):
            target.check()
        self.assertFalse(target.started)

    def test_wrong_parent_or_provider_refused(self):
        for parent, provider in (
            ("unrelated-target", "https://provider.test"),
            (self.parent, "https://wrong.test"),
        ):
            with self.subTest(parent=parent), self.assertRaises(ValueError):
                payment_browser.Target(
                    self.capture,
                    parent,
                    self.frame,
                    "https://merchant.test",
                    provider,
                    lambda: None,
                )

    def test_cleanup_releases_untracked_remote_objects_after_lost_reply(self):
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        sid, obj = target.psid, target.pg
        target.objects.clear()  # simulate successful creation with a lost reply
        target.close()
        with self.assertRaises(RuntimeError):
            self.capture.call(
                "Runtime.callFunctionOn",
                {
                    "objectId": obj,
                    "functionDeclaration": "function(){return true;}",
                    "returnByValue": True,
                },
                session_id=sid,
            )

    def test_actual_cross_origin_fill_and_metadata_only(self):
        target = payment_browser.Target(
            self.capture,
            self.parent,
            self.frame,
            "https://merchant.test",
            "https://provider.test",
            lambda: None,
        )
        try:
            self.assertTrue(
                target.attached,
                "fixture must exercise real cross-process iframe attachment",
            )
            result = target.fill(
                {
                    "number": "4242424242424242",
                    "cvc": "123",
                    "exp_month": 12,
                    "exp_year": 2030,
                }
            )
            self.assertEqual(
                result, {"success": True, "status": "filled", "filled_fields": 4}
            )
            self.assertEqual(
                self.page.frames[1].locator("[autocomplete=cc-number]").input_value(),
                "4242424242424242",
            )
            self.assertNotIn("424242", json.dumps(result))
        finally:
            target.close()


if __name__ == "__main__":
    unittest.main()
