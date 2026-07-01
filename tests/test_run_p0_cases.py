import tempfile
import unittest
from pathlib import Path

from experiments.run_p0_cases import run_cases


class P0CaseRunnerTests(unittest.TestCase):
    def test_runner_evaluates_smoke_dataset_and_writes_audit_log(self):
        with tempfile.TemporaryDirectory() as temp:
            tmpdir = Path(temp)
            log_path = tmpdir / "audit.jsonl"

            summary = run_cases(
                dataset_path=Path("datasets/p0_smoke_cases.jsonl"),
                audit_log_path=log_path,
                workspace_root=Path.cwd(),
            )

            self.assertEqual(summary["total_cases"], 10)
            self.assertEqual(summary["correct_cases"], 10)
            self.assertEqual(summary["false_positive_rate"], 0.0)
            self.assertEqual(summary["false_negative_rate"], 0.0)
            self.assertTrue(log_path.exists())
            self.assertEqual(len(log_path.read_text(encoding="utf-8").splitlines()), 10)


if __name__ == "__main__":
    unittest.main()
