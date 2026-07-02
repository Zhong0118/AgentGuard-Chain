import unittest

from agentguard_chain.guard import OutputRedactor, ResultInspector


class ResultInspectorTests(unittest.TestCase):
    def test_inspector_finds_common_secret_outputs(self):
        text = (
            "API_KEY=sk-test-output-demo\n"
            "password=hunter2\n"
            "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
        )

        findings = ResultInspector().inspect(text)
        secret_types = {finding.secret_type for finding in findings}

        self.assertIn("api_key", secret_types)
        self.assertIn("password", secret_types)
        self.assertIn("private_key", secret_types)
        self.assertTrue(all(finding.risk_type == "sensitive_output" for finding in findings))

    def test_redactor_removes_raw_secret_values(self):
        text = "API_KEY=sk-test-output-demo\npassword=hunter2"

        result = OutputRedactor().redact(text)

        self.assertTrue(result.applied)
        self.assertIn("api_key", result.redacted_types)
        self.assertIn("password", result.redacted_types)
        self.assertNotIn("sk-test-output-demo", result.text)
        self.assertNotIn("hunter2", result.text)
        self.assertIn("<redacted:api_key>", result.text)
        self.assertIn("<redacted:password>", result.text)

    def test_redactor_collapses_private_key_block(self):
        text = "x\n-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\ny"

        result = OutputRedactor().redact(text)

        self.assertTrue(result.applied)
        self.assertIn("private_key", result.redacted_types)
        self.assertNotIn("abc", result.text)
        self.assertIn("<redacted:private_key>", result.text)


if __name__ == "__main__":
    unittest.main()
