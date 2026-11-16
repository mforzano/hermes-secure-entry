"""The distinct registration adapter must not weaken native login detection."""

import unittest


class LoginRegressionTests(unittest.TestCase):
    def test_native_login_still_excludes_new_and_confirmation_passwords(self):
        from agent.vault_login_classifier import LoginControl, classify_login_control

        for attributes in (
            {"autocomplete": "new-password"},
            {"label": "New password"},
            {"label": "Confirm Password"},
            {"label": "Repeat password"},
            {"autocomplete": "one-time-code"},
        ):
            control = LoginControl(
                **dict(
                    {
                        "index": 0,
                        "form_index": 0,
                        "type": "password",
                        "label": "",
                        "name": "",
                        "autocomplete": "",
                    },
                    **attributes,
                )
            )
            self.assertIsNone(classify_login_control(control))
        ordinary = LoginControl(
            index=0,
            form_index=0,
            type="password",
            autocomplete="current-password",
            label="",
            name="",
        )
        self.assertEqual(classify_login_control(ordinary).token, "current-password")

    def test_signup_does_not_intercept_native_login_fill(self):
        from hermes_constants import get_hermes_home

        from secure_entry.service import Service

        service = Service("https://example.invalid", str(get_hermes_home()), port=0)
        self.addCleanup(service.close)
        called = []
        result = service.middleware(
            tool_name="browser_vault",
            args={"action": "fill", "handle": "synthetic"},
            next_call=lambda a: called.append(a) or "native-unchanged",
        )
        self.assertEqual(result, "native-unchanged")
        self.assertEqual(called, [{"action": "fill", "handle": "synthetic"}])
