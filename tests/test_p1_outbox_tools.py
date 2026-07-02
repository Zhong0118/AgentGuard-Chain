import json
import tempfile
import unittest
from pathlib import Path

from agents.miniagent.tools import MiniAgentTools


class MiniAgentOutboxToolTests(unittest.TestCase):
    def test_send_message_writes_file_outbox_with_id(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            tools = MiniAgentTools(workspace)

            result = tools.send_message("webhook://demo", "hello")

            payload = json.loads(result)
            self.assertEqual(payload["status"], "queued")
            self.assertEqual(payload["channel"], "message")
            self.assertTrue(payload["outbox_id"].startswith("msg-"))

            outbox = workspace / "logs" / "outbox" / "message_outbox.jsonl"
            rows = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["outbox_id"], payload["outbox_id"])
            self.assertEqual(rows[0]["target"], "webhook://demo")
            self.assertEqual(rows[0]["content"], "hello")

    def test_send_mail_writes_file_outbox_with_id(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            tools = MiniAgentTools(workspace)

            result = tools.send_mail("ops@example.com", "Report", "body")

            payload = json.loads(result)
            self.assertEqual(payload["status"], "queued")
            self.assertEqual(payload["channel"], "mail")
            self.assertTrue(payload["outbox_id"].startswith("mail-"))

            outbox = workspace / "logs" / "outbox" / "mail_outbox.jsonl"
            rows = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["outbox_id"], payload["outbox_id"])
            self.assertEqual(rows[0]["to"], "ops@example.com")
            self.assertEqual(rows[0]["subject"], "Report")
            self.assertEqual(rows[0]["body"], "body")


if __name__ == "__main__":
    unittest.main()
