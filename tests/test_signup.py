"""Disposable Chrome/native encrypted vault + genuine synthetic native approval."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class SignupTests(unittest.TestCase):
    def setUp(self):
        from agent.vault_store import VaultStore
        from gateway.session_context import clear_session_vars, set_session_vars
        from hermes_constants import get_hermes_home, profile_name_for_home
        from test_payment_browser import PaymentBrowserTests

        from secure_entry.service import Service

        self.fixture = PaymentBrowserTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = VaultStore(Path(self.tmp.name))
        self.secret = "Synthetic-Signup-Only!27"
        self.handle = self.store.add_item(
            "login",
            "Synthetic signup",
            {
                "identifier_type": "email",
                "identifier": "synthetic@example.test",
                "password": self.secret,
            },
            origin="https://merchant.test",
        ).id
        tokens = set_session_vars(
            platform="photon",
            chat_type="dm",
            chat_id="synthetic-chat",
            user_id="synthetic-owner",
            session_key="synthetic-signup-key",
            session_id="synthetic-session",
            profile=profile_name_for_home(get_hermes_home()) or "",
            cron_session="",
        )
        self.addCleanup(clear_session_vars, tokens)
        self.service = Service(
            "https://example.invalid",
            str(get_hermes_home()),
            port=0,
            store_factory=lambda: self.store,
        )
        self.addCleanup(self.service.close)
        from tools import approval

        self.prompts = []
        self.choice = "once"
        self.before_answer = lambda: None

        def notify(data):
            self.prompts.append(data)
            self.before_answer()
            approval.resolve_gateway_approval(
                "synthetic-signup-key", self.choice, request_id=data["request_id"]
            )

        approval.register_gateway_notify("synthetic-signup-key", notify)
        self.addCleanup(approval.unregister_gateway_notify, "synthetic-signup-key")
        self.install('<input id="p" type="password" autocomplete="new-password">')

    def install(self, html, topology="root"):
        self.topology = topology
        page = self.fixture.page
        if topology == "root":
            page.evaluate("html=>document.body.innerHTML=html", html)
            self.document = page
            sid = self.fixture.capture.page_session_id
            self.frame = self.fixture.capture.call(
                "Page.getFrameTree", {}, session_id=sid
            )["result"]["frameTree"]["frame"]["id"]
        else:
            url = (
                "https://merchant.test/child"
                if topology == "same"
                else "https://provider.test/child"
            )
            self.fixture.context.route(
                url, lambda r: r.fulfill(content_type="text/html", body=html)
            )
            page.evaluate(
                'url=>document.body.innerHTML=`<iframe src="${url}"></iframe>`', url
            )
            page.locator("iframe").wait_for()
            page.frames[1].wait_for_load_state()
            self.document = page.frames[1]
            session = self.fixture.context.new_cdp_session(page)
            root = session.send("DOM.getDocument")["root"]["nodeId"]
            node = session.send(
                "DOM.querySelector", {"nodeId": root, "selector": "iframe"}
            )["nodeId"]
            self.frame = session.send("DOM.describeNode", {"nodeId": node})["node"][
                "frameId"
            ]
        self.args = {
            "handle": self.handle,
            "origin": "https://merchant.test",
            "identifier": "synthetic@example.test",
            "parent": self.fixture.parent,
            "frame": self.frame,
            "frame_origin": (
                "https://provider.test"
                if topology == "cross"
                else "https://merchant.test"
            ),
            "password_nodes": self.nodes(),
        }

    def nodes(self):
        # Resolve inspected IDs in the actual selected document/renderer.
        from playwright.sync_api import Error as PlaywrightError

        try:
            session = self.fixture.context.new_cdp_session(self.document)
        except PlaywrightError:
            session = self.fixture.context.new_cdp_session(self.fixture.page)
        context = session.send("Page.createIsolatedWorld", {"frameId": self.frame})[
            "executionContextId"
        ]
        count = session.send(
            "Runtime.evaluate",
            {
                "contextId": context,
                "expression": 'document.querySelectorAll("input[type=password]").length',
                "returnByValue": True,
            },
        )["result"]["value"]
        nodes = []
        for index in range(count):
            obj = session.send(
                "Runtime.evaluate",
                {
                    "contextId": context,
                    "expression": f'document.querySelectorAll("input[type=password]")[{index}]',
                },
            )["result"]["objectId"]
            nodes.append(
                session.send("DOM.describeNode", {"objectId": obj})["node"][
                    "backendNodeId"
                ]
            )
            session.send("Runtime.releaseObject", {"objectId": obj})
        return nodes

    def fill(self, **overrides):
        self.assertTrue(
            callable(getattr(self.service, "signup_fill", None)),
            "signup native handler missing",
        )
        from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager

        ctx = PluginContext(
            PluginManifest(name="synthetic-signup"), get_plugin_manager()
        )
        registration = ctx.register_tool(
            name="secure_entry_signup_fill",
            toolset="secure_entry",
            schema={
                "name": "secure_entry_signup_fill",
                "parameters": {"type": "object"},
            },
            handler=self.service.signup_fill,
        )
        self.addCleanup(registration.dispose)
        result = json.loads(
            ctx.dispatch_tool(
                "secure_entry_signup_fill",
                {**self.args, **overrides},
                task_id="synthetic-payment",
            )
        )
        self.assertNotIn(self.secret, json.dumps(result) + str(self.prompts))
        return result

    def test_direct_same_and_cross_origin_iframes(self):
        for topology in ("same", "cross"):
            with self.subTest(topology=topology):
                self.install(
                    '<input id="p" type="password"><article>Other step</article><input id="q" type="password">',
                    topology,
                )
                result = self.fill()
                self.assertTrue(result.get("success"), result)
                self.assertEqual(result["filled_fields"], 2)
                self.assertTrue(
                    self.document.evaluate(
                        '(p)=>[...document.querySelectorAll("input")].every(e=>e.value===p)',
                        self.secret,
                    )
                )

    def test_generic_shapes_selected_prefills_and_framework_events(self):
        shapes = (
            '<form><input id="p" type="password" value="replace-me"><input name="unrelated"><input type="checkbox"></form><form><input type="search"><input type="password" id="leave"></form>',
            '<input id="p" type="password"><aside><input name="billing"></aside><section><input id="q" type="password"></section><input type="checkbox">',
            '<form><input id="p" type="password" autocomplete="new-password"></form><article>Another step</article><form><input id="q" type="password"></form>',
            '<input id="p" type="password"><div><input id="q" type="password"></div><section><input id="r" type="password"></section>',
        )
        for html in shapes:
            with self.subTest(html=html):
                self.install(html)
                self.args["password_nodes"] = (
                    self.args["password_nodes"][:1]
                    if 'id="leave"' in html
                    else self.args["password_nodes"]
                )
                before = self.document.evaluate(
                    """()=>[...document.querySelectorAll('input')].map(e=>[...e.attributes].map(a=>[a.name,a.value]))"""
                )
                self.document.evaluate("""()=>{
                    window.inputs=0;window.changes=0;window.submits=0;
                    document.addEventListener('submit',()=>window.submits++);
                    for(const e of document.querySelectorAll('input[type=password]:not(#leave)')){
                        e.addEventListener('input',()=>{window.inputs++; e.setAttribute('value',e.value);
                            e.classList.add('valid');e.setAttribute('aria-invalid','false');
                            document.body.className='step2';});
                        e.addEventListener('change',()=>window.changes++);
                    }
                }""")

                def presentation():
                    self.document.evaluate("""()=>{document.body.setAttribute('aria-busy','false');
                        document.body.insertAdjacentHTML('beforeend','<form><input name="search"></form>');
                        document.querySelector('#p').className='ready';}""")

                self.before_answer = presentation
                result = self.fill()
                self.assertTrue(result.get("success"), result)
                count = len(self.args["password_nodes"])
                self.assertTrue(
                    self.document.evaluate(
                        """({p,n})=>window.inputs===n && window.changes===n && window.submits===0 &&
                    [...document.querySelectorAll('input[type=password]:not(#leave)')].every(e=>e.value===p) &&
                    !document.querySelector('#leave')?.value && [...document.querySelectorAll('input[type=checkbox]')].every(e=>!e.checked)""",
                        {"p": self.secret, "n": count},
                    )
                )
                # Native code must not rewrite classification/type/name/layout attributes.
                after = self.document.evaluate(
                    """()=>[...document.querySelectorAll('input')].map(e=>[...e.attributes].filter(a=>!['value','class','aria-invalid'].includes(a.name)).map(a=>[a.name,a.value]))"""
                )
                expected = [
                    [
                        [k, v]
                        for k, v in attrs
                        if k not in ("value", "class", "aria-invalid")
                    ]
                    for attrs in before
                ]
                self.assertEqual(after[: len(expected)], expected)

    def test_denial_never_retrieves_and_always_yes_does_not_autoconfirm(self):
        from tools import approval

        approval.enable_session_yolo("synthetic-signup-key")
        self.addCleanup(approval.disable_session_yolo, "synthetic-signup-key")
        self.choice = "deny"
        with (
            patch.object(
                self.store,
                "resolve_secret",
                side_effect=AssertionError("must not retrieve"),
            ) as resolve,
            patch.dict(
                "os.environ", {"HERMES_YOLO_MODE": "1", "HERMES_AUTO_APPROVE": "1"}
            ),
        ):
            result = self.fill()
            self.assertEqual(result["status"], "consent_declined")
            resolve.assert_not_called()
        self.assertEqual(len(self.prompts), 1)
        self.assertTrue(
            self.document.evaluate('document.querySelector("#p").value===""')
        )

    def test_wrong_origin_account_handle_and_kind_refuse_before_retrieval(self):
        payment = self.store.add_item(
            "payment",
            "Synthetic payment",
            {
                "card_number": "4242424242424242",
                "cvc": "123",
                "exp_month": "12",
                "exp_year": "2035",
            },
            origin="https://merchant.test",
        ).id
        for overrides in (
            {"origin": "https://foreign.test"},
            {"identifier": "other@example.test"},
            {"handle": "vault_000000000000"},
            {"handle": payment},
            {"handle": "not-a-handle"},
            {"origin": "http://merchant.test"},
            {"frame_origin": "https://foreign.test"},
            {"password_nodes": []},
            {"password_nodes": [True]},
            {"password_nodes": self.args["password_nodes"] * 2},
        ):
            with (
                self.subTest(overrides=overrides),
                patch.object(self.store, "resolve_secret") as resolve,
            ):
                self.assertEqual(self.fill(**overrides)["status"], "refused")
                resolve.assert_not_called()
        self.assertEqual(len(self.prompts), 0)

    def test_selected_target_replacement_navigation_and_type_change_during_consent(
        self,
    ):
        for code in (
            "document.querySelector('#p').replaceWith(document.querySelector('#p').cloneNode(true))",
            "document.querySelector('#p').type='text';document.querySelector('#p').type='password'",
            "document.body.innerHTML='<input id=p type=password>'",
            "history.pushState({},'', '/next-step')",
        ):
            with self.subTest(code=code):
                self.install('<input id="p" type="password">')
                self.before_answer = lambda code=code: self.document.evaluate(code)
                with patch.object(self.store, "resolve_secret") as resolve:
                    result = self.fill()
                    self.assertEqual(result["status"], "refused", result)
                    resolve.assert_not_called()

    def test_lifecycle_takeover_and_profile_change_during_consent(self):
        from gateway.session_context import clear_session_vars, set_session_vars
        from tools.bot_desktop import lease

        tokens = []
        self.addCleanup(lambda: [clear_session_vars(t) for t in reversed(tokens)])

        def takeover():
            lease.acquire("synthetic-signup-viewer")
            lease.release("synthetic-signup-viewer")

        for action in (
            lambda: self.service.stopped(session_id="synthetic-session"),
            takeover,
            lambda: tokens.append(set_session_vars(profile="foreign-profile")),
        ):
            with (
                self.subTest(action=action),
                patch.object(self.store, "resolve_secret") as resolve,
            ):
                self.before_answer = action
                self.assertEqual(self.fill()["status"], "refused")
                resolve.assert_not_called()

    def test_postdispatch_target_loss_is_unknown_not_retry(self):
        self.document.evaluate(
            """()=>document.querySelector('#p').oninput=e=>e.target.replaceWith(e.target.cloneNode(true))"""
        )
        with patch.object(
            self.store, "resolve_secret", wraps=self.store.resolve_secret
        ) as resolve:
            result = self.fill()
            self.assertEqual(result["status"], "write_unknown", result)
            self.assertEqual(resolve.call_count, 1)
        self.assertEqual(len(self.prompts), 1)

    def test_private_equality_and_constraint_verification(self):
        for script in (
            "e.target.value+='altered'",
            "e.target.setCustomValidity('invalid')",
        ):
            with self.subTest(script=script):
                self.install(
                    '<input id="p" type="password"><input id="q" type="password">'
                )
                self.document.evaluate(
                    """script=>document.querySelector('#p').onchange=e=>eval(script)""",
                    script,
                )
                result = self.fill()
                self.assertEqual(result["status"], "write_unknown", result)

    def test_expiry_before_retrieval(self):
        clock = [0.0]
        self.before_answer = lambda: clock.__setitem__(0, 181.0)
        with (
            patch("secure_entry.signup.time.monotonic", side_effect=lambda: clock[0]),
            patch("tools.approval_human_wait.human_wait_seconds", return_value=0),
            patch.object(self.store, "resolve_secret") as resolve,
        ):
            result = self.fill()
            self.assertEqual(result["status"], "refused", result)
            self.assertEqual(result["stage"], "postconsent_current")
            resolve.assert_not_called()

    def test_actual_navigation_during_consent_prevents_retrieval(self):
        self.before_answer = lambda: self.fixture.page.goto(
            "https://merchant.test/next"
        )
        with patch.object(self.store, "resolve_secret") as resolve:
            result = self.fill()
            self.assertEqual(result["status"], "refused", result)
            resolve.assert_not_called()

    def test_selected_controls_must_be_actual_writable_passwords(self):
        for attribute in (
            'type="text"',
            'type="password" disabled',
            'type="password" readonly',
            'type="password" style="display:none"',
            'type="password" inert',
        ):
            with self.subTest(attribute=attribute):
                self.install('<input id="p" type="password">')
                node = self.args["password_nodes"]
                self.document.evaluate(
                    'attrs=>document.querySelector("#p").outerHTML=`<input id="p" ${attrs}>`',
                    attribute,
                )
                # Inspect the replacement rather than accidentally testing stale IDs.
                session = self.fixture.context.new_cdp_session(self.fixture.page)
                root = session.send("DOM.getDocument")["root"]["nodeId"]
                frontend = session.send(
                    "DOM.querySelector", {"nodeId": root, "selector": "#p"}
                )["nodeId"]
                node = session.send("DOM.describeNode", {"nodeId": frontend})["node"][
                    "backendNodeId"
                ]
                with patch.object(self.store, "resolve_secret") as resolve:
                    self.assertEqual(
                        self.fill(password_nodes=[node])["status"], "refused"
                    )
                    resolve.assert_not_called()

    def test_lost_cdp_reply_after_dispatch_is_unknown(self):
        from secure_entry.signup import SignupTarget

        original = SignupTarget.invoke

        def invoke(target, sid, obj, function, args=()):
            result = original(target, sid, obj, function, args)
            if "this.write" in function:
                raise TimeoutError("synthetic lost reply")
            return result

        with patch.object(SignupTarget, "invoke", invoke):
            result = self.fill()
            self.assertEqual(result["status"], "write_unknown", result)
        self.assertTrue(
            self.document.evaluate(
                '(p)=>document.querySelector("#p").value===p', self.secret
            )
        )

    def test_single_new_password_registered_native_fill(self):
        result = self.fill()
        self.assertTrue(result.get("success"), result)
        self.assertEqual(result["filled_fields"], 1)
        self.assertEqual(len(self.prompts), 1)
        self.assertIn("registration", str(self.prompts).lower())
        self.assertIn(self.handle, str(self.prompts))
        self.assertIn(self.args["identifier"], str(self.prompts))
        self.assertTrue(
            self.document.evaluate(
                '(want)=>document.querySelector("#p").value===want', self.secret
            )
        )


if __name__ == "__main__":
    unittest.main()
