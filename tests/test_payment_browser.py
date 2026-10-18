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
        self, choice="once", before_answer=None, issued_card=None, expected_prompts=1,
        frame_origin="https://provider.test", registered=False,
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
            handler=service.payment_fill
            if registered:
                from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager
                ctx=PluginContext(PluginManifest(name='synthetic-root-payment'),get_plugin_manager())
                registration=ctx.register_tool(name='secure_entry_payment_fill',toolset='secure_entry',
                    schema={'name':'secure_entry_payment_fill','parameters':{'type':'object'}},handler=handler)
                self.assertIsNotNone(registration)
                self.addCleanup(registration.dispose)
                handler=lambda args, **kw:ctx.dispatch_tool('secure_entry_payment_fill',args,**kw)
            # Deliberately no legacy session metadata: BrowserUse dispatch does
            # not populate the native task-key cache for every route.
            with patch.dict(browser_tool._active_sessions, {}, clear=True):
                result = json.loads(
                    handler(
                        {
                            "parent": self.parent,
                            "frame": self.frame,
                            "merchant_origin": "https://merchant.test",
                            "frame_origin": frame_origin,
                            "spend_request_id": "lsrq_synthetic",
                        },
                        task_id="synthetic-payment",
                    )
                )
        self.assertEqual(len(prompts), expected_prompts)
        return result, prompts

    def target_for_html(self, html):
        self.page.frames[1].evaluate("html => document.body.innerHTML=html", html)
        return self.target_for_current_widget()

    def target_for_current_widget(self):
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

    @staticmethod
    def alternative_billing_fixture(extra=''):
        # Complete observed shape, synthetic names/options only; no merchant IDs.
        return '''<form><input type="hidden" name="state"><input type="hidden" name="events">
          <input type="submit" hidden><button type="submit" style="display:none">Submit</button>
          <label>ZIP<input autocomplete="postal-code" required></label>
          <div style="display:none"><input id="alternative" autocomplete="postal-code"></div>
          <input autocomplete="cc-name"><input autocomplete="cc-number">
          <label>* Month<select><option value="">Choose</option><option value="12">December</option></select></label>
          <label>* Year<select><option value="">Choose</option><option value="2035">2035</option></select></label>
          <label>Card Verification Value(CVV2)<input></label>
          <button>Back</button><button>Next</button><button>Exit</button>''' + extra + '</form>'

    def test_hidden_alternative_complete_form_registered_native_fill(self):
        self.page.frames[1].evaluate('html=>document.body.innerHTML=html', self.alternative_billing_fixture())
        result, _ = self._run_facility(registered=True, issued_card={
            'number':'4242424242424242', 'exp_month':12, 'exp_year':2035, 'cvc':'123',
            'billing_address':{'name':'Synthetic Cardholder', 'postal_code':'10001'},
        })
        self.assertTrue(result.get('success'), result)
        self.assertEqual(result['filled_fields'], 6)
        self.assertTrue(self.page.frames[1].evaluate('document.querySelector("#alternative").value===""'))

    def test_hidden_alternative_mutations_remain_sticky(self):
        for mutation in (
            "e.type='password';e.type='text'",
            "e.autocomplete='billing tel';e.autocomplete='postal-code'",
            "e.parentElement.style.display='block';e.parentElement.style.display='none'",
            "e.remove();document.forms[0].append(e)",
        ):
            with self.subTest(mutation=mutation):
                target=self.target_for_html(self.alternative_billing_fixture())
                self.page.frames[1].evaluate("()=>{const e=document.querySelector('#alternative');"+mutation+"}")
                with self.assertRaises(ValueError):
                    target.check()
                target.close()

    def test_standard_form_non_data_buttons_are_not_fill_targets(self):
        for control in (
            '<button type="submit" hidden>Pay</button>',
            '<button type="button">Help</button>',
            '<button type="reset">Reset</button>',
            '<input type="submit" hidden>',
            '<input type="button" value="Help">',
            '<input type="reset">',
            '<input type="image" alt="Pay">',
            '<output hidden>Calculated total</output>',
            '<fieldset><legend>Card details</legend></fieldset>',
        ):
            with self.subTest(control=control):
                target = self.target_for_html(
                    '<form>' + control + '<input autocomplete="cc-number">'
                    '<input autocomplete="cc-exp"><input autocomplete="cc-csc">'
                    '<input autocomplete="postal-code"></form>'
                )
                result = target.fill(dict(
                    number='4242424242424242', exp_month=12, exp_year=2035,
                    cvc='123', billing_address={'postal_code': '10001'},
                ))
                self.assertEqual(result['filled_fields'], 4)
                self.assertTrue(self.page.frames[1].evaluate('''() =>
                    [...document.querySelectorAll('input')]
                      .filter(e => e.autocomplete).every(e => e.value.length > 0)'''))
                target.close()

    def install_brand_validation_widget(self):
        """Observed mutation categories together, without merchant-specific code."""
        self.page.frames[1].evaluate('''() => {
            document.body.innerHTML='<form><button type="submit" hidden>Pay</button><div class="group">' +
                '<div class="brand"><span>Unknown card</span></div>' +
                '<input autocomplete="cc-number" maxlength="23"><input autocomplete="cc-exp">' +
                '<input autocomplete="cc-csc" maxlength="4"><input autocomplete="cc-name">' +
                '<input autocomplete="postal-code" required disabled></div></form>';
            const group=document.querySelector('.group'), brand=document.querySelector('.brand');
            const pan=document.querySelector('[autocomplete="cc-number"]');
            pan.oninput=()=>{
                pan.maxLength=19;
                pan.minLength=12;
                const cvc=document.querySelector('[autocomplete="cc-csc"]');
                cvc.maxLength=3;cvc.minLength=3;
                pan.value=pan.value.match(/.{1,4}/g).join(' ');
                pan.setAttribute('value',pan.value);
                document.querySelector('form').className='validated';
                group.setAttribute('role','group');
                group.setAttribute('aria-label','Card details');
                group.setAttribute('aria-hidden','false');
                group.className='group recognized';
                brand.replaceChildren(Object.assign(document.createElement('span'),{textContent:'Recognized card'}));
                brand.setAttribute('role','status');brand.setAttribute('aria-live','polite');
                pan.setAttribute('aria-describedby','card-status');
                document.querySelector('[autocomplete="postal-code"]').disabled=false;
            };
            document.querySelector('[autocomplete="cc-exp"]').oninput=e=>{
                e.target.value=e.target.value.replace('/',' / ');
                e.target.setAttribute('value',e.target.value);
            };
        }''')

    def test_native_facility_brand_constraints_and_accessibility_presentation(self):
        self.install_brand_validation_widget()
        result, _ = self._run_facility(issued_card=dict(
            number='4242424242424242', cvc='123', exp_month=12, exp_year=2035,
            billing_address={'postal_code':'10001', 'name':'SYNTHETIC CARDHOLDER'},
        ))
        self.assertTrue(result['success'], result)
        self.assertEqual(result['filled_fields'], 5)
        self.assertTrue(self.page.frames[1].evaluate('''()=>{
            const inputs=[...document.querySelectorAll('input')];
            return inputs.every(e=>e.value.length>0 && !e.matches(':disabled')) &&
                inputs[0].value==='4242 4242 4242 4242' && inputs[1].value==='12 / 35' &&
                inputs[2].value==='123' && inputs[4].value==='10001';
        }'''))

    def test_brand_widget_keeps_destination_and_control_mutations_sticky(self):
        mutations = (
            "n.name='other'; n.removeAttribute('name')",
            "n.type='tel'; n.removeAttribute('type')",
            "n.autocomplete='cc-name'; n.autocomplete='cc-number'",
            "n.setAttribute('form','other'); n.removeAttribute('form')",
            "n.disabled=true; n.disabled=false",
            "n.readOnly=true; n.readOnly=false",
            "f.action='https://foreign.test/pay'; f.removeAttribute('action')",
            "g.setAttribute('aria-owns','other'); g.removeAttribute('aria-owns')",
            "n.setAttribute('role','textbox'); n.removeAttribute('role')",
            "n.replaceWith(n.cloneNode(true))",
            "g.remove(); f.append(g)",
            "f.append(n); g.append(n)",
            "g.insertAdjacentHTML('beforeend','<input autocomplete=cc-number>')",
            "g.insertAdjacentHTML('beforeend','<input name=unsupported>')",
            "document.head.append(document.createElement('base'))",
        )
        for when in ('prewrite', 'selfwrite'):
            for mutation in mutations:
                with self.subTest(when=when, mutation=mutation):
                    self.install_brand_validation_widget()
                    target=self.target_for_current_widget()
                    self.page.frames[1].evaluate('''({when,mutation})=>{
                        const n=document.querySelector('[autocomplete="cc-number"]');
                        const f=document.querySelector('form'), g=document.querySelector('.group');
                        if(when==='prewrite')eval(mutation);
                        else {const normal=n.oninput; n.oninput=()=>{normal();eval(mutation);};}
                    }''', dict(when=when, mutation=mutation))
                    result=target.invoke(target.csid,target.cg,'function(v){return this.write(v);}', ({
                        'cc-number':'4242424242424242','cc-exp':'12/35','cc-csc':'123',
                        'cc-name':'SYNTHETIC CARDHOLDER','billing postal-code':'10001',
                    },))
                    self.assertFalse(result['valid'], result)
                    self.assertEqual(result['written'], 0 if when=='prewrite' else 1)
                    target.close()

    def test_brand_widget_length_and_accessibility_changes_are_selfwrite_only(self):
        for mutation in (
            "n.maxLength=19; n.maxLength=23",
            "n.minLength=12; n.removeAttribute('minlength')",
            "g.setAttribute('aria-label','Other'); g.removeAttribute('aria-label')",
            "g.setAttribute('aria-hidden','true'); g.removeAttribute('aria-hidden')",
            "g.setAttribute('role','group'); g.removeAttribute('role')",
        ):
            with self.subTest(mutation=mutation):
                self.install_brand_validation_widget()
                target=self.target_for_current_widget()
                self.page.frames[1].evaluate('''mutation=>{
                    const n=document.querySelector('input'),g=document.querySelector('.group');eval(mutation);
                }''', mutation)
                with self.assertRaises(ValueError):
                    target.check()
                target.close()

    def test_brand_widget_never_accepts_truncation_foreign_values_or_actual_hiding(self):
        for mutation in (
            "n.maxLength=15; n.value=n.value.slice(0,15)",
            "document.querySelector('[autocomplete=cc-csc]').value='foreign'",
            "g.classList.add('invisible')",
            "g.setAttribute('aria-hidden','true')",
        ):
            with self.subTest(mutation=mutation):
                self.install_brand_validation_widget()
                self.page.frames[1].evaluate('''()=>{
                    const s=document.createElement('style');
                    s.textContent='.invisible {display:none} .group[aria-hidden="true"] {visibility:hidden}';
                    document.head.append(s);
                }''')
                target=self.target_for_current_widget()
                self.page.frames[1].evaluate('''mutation=>{
                    const n=document.querySelector('input'),g=document.querySelector('.group');
                    const normal=n.oninput;n.oninput=()=>{normal();eval(mutation);};
                }''', mutation)
                with self.assertRaises(payment_browser.WriteRefused) as caught:
                    target.fill(dict(number='4242424242424242',cvc='123',exp_month=12,exp_year=2035,
                        billing_address={'name':'SYNTHETIC CARDHOLDER','postal_code':'10001'}))
                self.assertIn(caught.exception.category, ('invalidated','field_changed','write_mismatch'))
                self.assertEqual(caught.exception.written,1)
                target.close()

    def test_native_facility_enables_retained_billing_during_pan_event(self):
        frame = self.page.frames[1]
        frame.evaluate('''() => {
            document.body.innerHTML='<form><button type="submit" hidden>Pay</button><span class="brand"></span>' +
                '<input autocomplete="cc-number"><input autocomplete="cc-exp">' +
                '<input autocomplete="cc-csc"><input autocomplete="postal-code" disabled></form>';
            document.querySelector('[autocomplete="cc-number"]').oninput=e=>{
                e.target.value=e.target.value.match(/.{1,4}/g).join(' ');
                e.target.setAttribute('value',e.target.value);
                e.target.setAttribute('aria-invalid','false');
                document.querySelector('.brand').classList.add('recognized');
                document.querySelector('[autocomplete="postal-code"]').disabled=false;
            };
            document.querySelector('[autocomplete="cc-exp"]').oninput=e=>{
                e.target.value=e.target.value.replace('/',' / ');
                e.target.setAttribute('value',e.target.value);
            };
        }''')
        result, _ = self._run_facility(issued_card=dict(
            number='4242424242424242', cvc='123', exp_month=12, exp_year=2035,
            billing_address={'postal_code': '10001'},
        ))
        self.assertTrue(result['success'], result)
        self.assertEqual(result['status'], 'filled')
        self.assertEqual(result['filled_fields'], 4)
        self.assertTrue(frame.evaluate('''() => [...document.querySelectorAll('input')]
            .every(e=>e.value.length>0 && !e.matches(':disabled'))'''))

    def test_native_facility_reports_unavailable_optional_and_required_billing(self):
        for required in (False, True):
            with self.subTest(required=required):
                frame = self.page.frames[1]
                frame.evaluate('''required => {
                    document.body.innerHTML='<form><button hidden>Pay</button>' +
                        '<input autocomplete="postal-code" disabled '+(required?'required':'')+'>' +
                        '<input autocomplete="cc-number"><input autocomplete="cc-exp">' +
                        '<input autocomplete="cc-csc"></form>';
                    window.billingEvents=0;
                    document.querySelector('[autocomplete="postal-code"]').oninput=()=>window.billingEvents++;
                }''', required)
                result, _ = self._run_facility(issued_card=dict(
                    number='4242424242424242', cvc='123', exp_month=12, exp_year=2035,
                    billing_address={'postal_code': '10001'},
                ))
                if required:
                    self.assertFalse(result['success'], result)
                    self.assertEqual(result['status'], 'write_unknown')
                    self.assertEqual(result['refusal'], 'billing_unavailable')
                    self.assertEqual(result['written_fields'], 3)
                else:
                    self.assertTrue(result['success'], result)
                    self.assertEqual(result['filled_fields'], 3)
                    self.assertEqual(result['skipped_optional_fields'], ['billing postal-code'])
                self.assertEqual(frame.evaluate('window.billingEvents'), 0)
                self.assertTrue(frame.locator('[autocomplete="postal-code"]').evaluate('(e)=>e.value==="" && e.matches(":disabled")'))

    def test_billing_dependency_matrix_late_events_and_inherited_disabled(self):
        for grouping in ('direct', 'fieldset', 'legend'):
            for trigger in ('cc-exp', 'cc-csc', 'cc-name'):
                with self.subTest(grouping=grouping, trigger=trigger):
                    billing = '<input autocomplete="postal-code" required'+(' disabled' if grouping=='direct' else '')+'>'
                    if grouping=='fieldset':
                        billing='<fieldset disabled><legend>Billing</legend>'+billing+'</fieldset>'
                    if grouping=='legend':
                        billing='<fieldset disabled><legend><button type="button">Help</button></legend>'+billing+'</fieldset>'
                    target = self.target_for_html('<form>'+billing+
                        '<button type="submit" hidden>Pay</button><input autocomplete="cc-number">'
                        '<input autocomplete="cc-exp"><input autocomplete="cc-csc"><input autocomplete="cc-name"></form>')
                    self.page.frames[1].evaluate('''({trigger,grouping})=>{
                        const zip=document.querySelector('[autocomplete="postal-code"]');
                        document.querySelector('[autocomplete="'+trigger+'"]').onchange=()=>{
                            if(grouping==='direct')zip.disabled=false;
                            else zip.closest('fieldset').disabled=false;
                        };
                        if(grouping==='direct' && trigger!=='cc-exp')
                            document.querySelector('[autocomplete="cc-exp"]').oninput=()=>{
                                zip.disabled=false;zip.disabled=true;
                            };
                    }''', dict(trigger=trigger, grouping=grouping))
                    result=target.fill(dict(number='4242424242424242', cvc='123', exp_month=12, exp_year=2035,
                        billing_address={'postal_code':'10001','name':'SYNTHETIC NAME'}))
                    self.assertEqual(result['filled_fields'], 5)
                    self.assertNotIn('skipped_optional_fields', result)
                    target.close()

    def test_readonly_billing_is_preserved_or_explicitly_skipped_never_written(self):
        for value, required, outcome in (('', False, 'skip'), ('10001', True, 'match'),
                ('', True, 'unavailable'), ('99999', False, 'conflict')):
            with self.subTest(outcome=outcome):
                target=self.target_for_html('<form><input autocomplete="cc-number"><input autocomplete="cc-exp">'
                    '<input autocomplete="postal-code" readonly value="'+value+'"'+(' required' if required else '')+'></form>')
                card=dict(number='4242424242424242', exp_month=12, exp_year=2035,
                    billing_address={'postal_code':'10001'})
                if outcome in ('unavailable','conflict'):
                    with self.assertRaises(payment_browser.WriteRefused) as caught:
                        target.fill(card)
                    self.assertEqual(caught.exception.category, 'billing_unavailable' if outcome=='unavailable' else 'initial_mismatch')
                    self.assertEqual(caught.exception.written, 2 if outcome=='unavailable' else 0)
                else:
                    result=target.fill(card)
                    self.assertEqual(result['filled_fields'], 2)
                    self.assertEqual(result.get('skipped_optional_fields', []), ['billing postal-code'] if outcome=='skip' else [])
                self.assertEqual(self.page.frames[1].locator('[autocomplete="postal-code"]').input_value(), value)
                target.close()

    def test_disabled_billing_first_legend_credential_remains_writable(self):
        target=self.target_for_html('<form><fieldset disabled><legend>'
            '<input autocomplete="cc-number"><input autocomplete="cc-exp"></legend>'
            '<input autocomplete="postal-code" required></fieldset></form>')
        self.page.frames[1].evaluate('''()=>{
            document.querySelector('[autocomplete="cc-exp"]').oninput=()=>document.querySelector('fieldset').disabled=false;
        }''')
        self.assertEqual(target.fill(dict(number='4242424242424242',exp_month=12,exp_year=2035,
            billing_address={'postal_code':'10001'}))['filled_fields'],3)

    def test_unsupplied_required_unavailable_billing_does_not_gain_false_validity(self):
        for state in ('readonly','disabled'):
            with self.subTest(state=state):
                target=self.target_for_html('<form><input autocomplete="cc-number"><input autocomplete="cc-exp">'
                    '<input autocomplete="billing address-line1" required '+state+'></form>')
                with self.assertRaises(payment_browser.WriteRefused) as caught:
                    target.fill(dict(number='4242424242424242',exp_month=12,exp_year=2035,
                        preserve_unsupplied_billing=True))
                self.assertEqual(caught.exception.category,'source_missing')
                self.assertEqual(caught.exception.written,0)
                target.close()

    def test_required_readonly_billing_empty_source_is_not_satisfied(self):
        target=self.target_for_html('<form><input autocomplete="cc-number"><input autocomplete="cc-exp">'
            '<input autocomplete="billing address-line2" required readonly></form>')
        with self.assertRaises(payment_browser.WriteRefused) as caught:
            target.fill(dict(number='4242424242424242',exp_month=12,exp_year=2035,billing_address={'line2':''}))
        self.assertEqual(caught.exception.category,'billing_unavailable')
        self.assertEqual(caught.exception.written,2)

    def test_preserved_billing_rechecks_validation_after_enabling(self):
        target=self.target_for_html('<form><input autocomplete="cc-number"><input autocomplete="cc-exp">'
            '<input autocomplete="billing address-line1" disabled required pattern="[0-9]+" value="invalid"></form>')
        self.page.frames[1].evaluate('''()=>{
            document.querySelector('[autocomplete="cc-exp"]').onchange=()=>document.querySelector('[autocomplete="billing address-line1"]').disabled=false;
        }''')
        with self.assertRaises(payment_browser.WriteRefused) as caught:
            target.fill(dict(number='4242424242424242',exp_month=12,exp_year=2035,preserve_unsupplied_billing=True))
        self.assertEqual(caught.exception.category,'source_missing')
        self.assertEqual(caught.exception.written,2)

    def test_disabled_billing_prewrite_changes_are_sticky(self):
        for mutation in ('zip.disabled=false', 'zip.disabled=false;zip.disabled=true',
                'zip.readOnly=true', 'zip.autocomplete="billing tel"', 'zip.remove()',
                'zip.replaceWith(zip.cloneNode())', 'document.body.append(zip)'):
            with self.subTest(mutation=mutation):
                target=self.target_for_html('<form><input autocomplete="cc-number"><input autocomplete="cc-exp">'
                    '<input autocomplete="postal-code" disabled></form>')
                self.page.frames[1].evaluate('''mutation=>{
                    const zip=document.querySelector('[autocomplete="postal-code"]');eval(mutation);
                }''', mutation)
                with self.assertRaises(ValueError):
                    target.fill(dict(number='4242424242424242',exp_month=12,exp_year=2035))
                self.assertTrue(self.page.frames[1].locator('[autocomplete="cc-number"]').evaluate('(e)=>e.value===""'))
                target.close()

    def test_dynamic_billing_wrong_origin_navigation_during_native_consent_refuses(self):
        frame=self.page.frames[1]
        frame.evaluate('''()=>{document.body.innerHTML='<form><input autocomplete="cc-number"><input autocomplete="cc-exp">'+
            '<input autocomplete="postal-code" disabled></form>';}''')
        self.context.route('https://foreign.test/**', lambda r:r.fulfill(content_type='text/html',
            body='<form><input autocomplete="cc-number"><input autocomplete="cc-exp"></form>'))
        result,_=self._run_facility(before_answer=lambda:frame.goto('https://foreign.test/pay'))
        self.assertFalse(result['success'], result)
        self.assertEqual(result['status'],'refused')
        self.assertEqual(result['stage'],'postconsent_target')
        self.assertEqual(result['refusal'],'target_check_failed')
        self.assertTrue(frame.evaluate('''()=>[...document.querySelectorAll('input')].every(e=>e.value==='')'''))

    def test_dynamic_billing_cannot_disable_an_already_written_field(self):
        target=self.target_for_html('<form><input autocomplete="cc-number"><input autocomplete="cc-exp">'
            '<input autocomplete="postal-code" disabled><input autocomplete="cc-name"></form>')
        self.page.frames[1].evaluate('''()=>{
            const zip=document.querySelector('[autocomplete="postal-code"]');
            document.querySelector('[autocomplete="cc-number"]').oninput=()=>zip.disabled=false;
            document.querySelector('[autocomplete="cc-name"]').oninput=()=>zip.disabled=true;
        }''')
        with self.assertRaises(payment_browser.WriteRefused) as caught:
            target.fill(dict(number='4242424242424242',exp_month=12,exp_year=2035,
                billing_address={'postal_code':'10001','name':'SYNTHETIC NAME'}))
        self.assertEqual(caught.exception.category,'invalidated')
        self.assertEqual(caught.exception.written,4)

    def test_disabled_billing_event_window_does_not_authorize_foreign_changes(self):
        for mutation in ('zip.autocomplete="billing tel"', 'zip.readOnly=true',
                'zip.replaceWith(zip.cloneNode())', 'zip.remove()',
                'zip.required=true;zip.required=false',
                'document.querySelector("[autocomplete=cc-exp]").disabled=true',
                'document.querySelector("[type=submit]").type="text"',
                'zip.value="foreign"',
                'zip.insertAdjacentHTML("afterend", "<input autocomplete=postal-code>")'):
            with self.subTest(mutation=mutation):
                target=self.target_for_html('<form><button hidden>Pay</button><input type="submit" hidden>'
                    '<input autocomplete="cc-number"><input autocomplete="cc-exp">'
                    '<input autocomplete="postal-code" disabled></form>')
                self.page.frames[1].evaluate('''mutation=>{
                    document.querySelector('[autocomplete="cc-number"]').oninput=()=>{
                        const zip=document.querySelector('[autocomplete="postal-code"]');
                        zip.disabled=false;eval(mutation);
                    };
                }''', mutation)
                with self.assertRaises(payment_browser.WriteRefused) as caught:
                    target.fill(dict(number='4242424242424242',exp_month=12,exp_year=2035,
                        billing_address={'postal_code':'10001'}))
                self.assertIn(caught.exception.category, ('invalidated','field_changed'))
                self.assertEqual(caught.exception.written, 1)
                target.close()

    def test_non_data_filter_does_not_hide_unsupported_data_inputs(self):
        for extra in (
            '<input type="hidden" autocomplete="cc-number">',
            '<input type="text" name="other">',
            '<input type="checkbox">',
            '<input autocomplete="cc-number">',
            '<textarea></textarea>',
            '<input type="password" autocomplete="cc-csc">',
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(payment_browser.BindingRefused) as caught:
                    self.target_for_html(
                        '<form><button type="submit" hidden>Pay</button>'
                        '<input autocomplete="cc-number"><input autocomplete="cc-exp">'
                        + extra + '</form>'
                    )
                self.assertEqual(caught.exception.category, 'form_layout')

    def test_generic_form_grouping_and_associated_non_data_controls(self):
        target = self.target_for_html('''
            <button form="payment" type="submit" hidden>Pay</button>
            <output form="payment" hidden>Total</output>
            <fieldset form="payment"><legend>Summary</legend></fieldset>
            <form id="payment"><fieldset><legend>Payment</legend>
              <input autocomplete="cc-number"><input autocomplete="cc-exp">
              <input autocomplete="cc-csc"><input autocomplete="postal-code">
              <button type="submit" hidden>Pay</button><output>Total</output>
            </fieldset></form>''')
        self.assertEqual(target.fill(dict(
            number='4242424242424242', exp_month=12, exp_year=2035, cvc='123',
            billing_address={'postal_code': '10001'},
        ))['filled_fields'], 4)

    def test_generic_data_control_state_and_ownership_matrix(self):
        base = '<form id="payment"><input autocomplete="cc-number"><input autocomplete="cc-exp">{}</form>'
        fixtures = [
            '<form><input autocomplete="cc-number" disabled><input autocomplete="cc-exp"></form>',
            '<form><input autocomplete="cc-number" readonly><input autocomplete="cc-exp"></form>',
            '<form><input autocomplete="cc-number"><input autocomplete="cc-exp" disabled></form>',
            '<form><input autocomplete="cc-number"><input autocomplete="cc-exp" readonly></form>',
            '<form><input autocomplete="cc-number" value="4242424242424242"><input autocomplete="cc-exp"></form>',
            '<form><input autocomplete="cc-number"><input autocomplete="cc-exp" value="12/35"></form>',
            base.format('<input autocomplete="cc-csc" value="123">'),
            base.format('<input autocomplete="cc-csc" disabled>'),
            base.format('<input autocomplete="cc-csc" readonly>'),
            base.format('<input autocomplete="postal-code" hidden>'),
            base.format('<input autocomplete="postal-code"><input autocomplete="billing postal-code">'),
            base.format('') + '<input autocomplete="postal-code">',
            base.format('') + '<input autocomplete="postal-code" form="payment">',
            '<form><fieldset disabled><input autocomplete="cc-number"><input autocomplete="cc-exp"></fieldset></form>',
        ]
        for html in fixtures:
            with self.subTest(html=html):
                with self.assertRaises(payment_browser.BindingRefused) as caught:
                    self.target_for_html(html)
                self.assertIn(caught.exception.category, ('form_layout', 'frame_lineage'))

    def test_ignored_action_input_cannot_become_data_after_binding(self):
        for restore in (False, True):
            with self.subTest(restore=restore):
                target = self.target_for_html(
                    '<form><input autocomplete="cc-number"><input autocomplete="cc-exp">'
                    '<input type="submit" hidden></form>'
                )
                self.page.frames[1].evaluate('''restore => {
                    const action=document.querySelector('[type="submit"]');
                    action.type='text';
                    if(restore)action.type='submit';
                }''', restore)
                with self.assertRaises(ValueError):
                    target.check()
                target.close()

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
            "payment_diagnostic_version": "0.5.11",
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
                    payment_diagnostic_version="0.5.11",
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
            ('input', 'pattern', '.*'),
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

    def test_native_issued_billing_is_not_registered_as_payment_secrets(self):
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
                payment_diagnostic_version="0.5.11",
            ),
        )
        for metadata in card["billing_address"].values():
            self.assertEqual(redact_registered_vault_values(metadata), metadata)
        self.assertEqual(
            redact_registered_vault_values("4242424242424242 12/30"),
            "«redacted-vault-secret» «redacted-vault-secret»",
        )

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
                "payment_diagnostic_version": "0.5.11",
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
                "payment_diagnostic_version": "0.5.11",
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
