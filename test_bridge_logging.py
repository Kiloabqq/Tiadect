import contextlib
import io
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import bridge as b

class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name).resolve()
        (self.root / ".git").mkdir()
        self.cfg = b.Config("owner/mailbox", 30, [self.root], self.root, "codex", "gh", 50000)

    def test_success_and_modes(self):
        for quiet, verbose in [(False, False), (False, True), (True, False)]:
            stream = io.StringIO()
            with contextlib.redirect_stderr(stream):
                b.configure_logging(verbose, quiet)
                with patch.object(b, "set_state") as state, patch.object(b, "comment"), patch.object(b, "codex_exec", return_value=(0, "SECRET_RESPONSE", "")) as execute:
                    b.process_issue(self.cfg, {"number": 7, "body": "SECRET_PROMPT", "labels": []})
                    self.assertEqual(execute.call_args.args[-1], "read-only")
                    self.assertEqual(state.call_args.args[2], b.DONE)
            output = stream.getvalue()
            self.assertNotIn("SECRET", output)
            if quiet:
                self.assertEqual(output, "")
            else:
                for event in ("discovered", "claimed", "repository=", "response posted", "done"):
                    self.assertIn(event, output)
            if verbose:
                self.assertIn("Parsing task envelope", output)

    def test_failure_quiet_redacts_exception(self):
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            b.configure_logging(quiet=True)
            with patch.object(b, "set_state"), patch.object(b, "comment"), patch.object(b, "codex_exec", side_effect=RuntimeError("SECRET_TOKEN")):
                b.process_issue(self.cfg, {"number": 8, "body": "SECRET_PROMPT", "labels": []})
        self.assertIn("failed", stream.getvalue())
        self.assertNotIn("SECRET", stream.getvalue())

    def test_boundaries(self):
        with self.assertRaises(ValueError):
            b.resolve_repo(self.cfg, str(self.root.parent))
        for mode in ("danger-full-access", "yolo", "SECRET"):
            with self.assertRaises(ValueError):
                b.codex_exec(self.cfg, self.root, "prompt", mode)

    def test_codex_timing_and_arguments(self):
        with self.assertLogs("tiadect", level="DEBUG") as logs:
            with patch.object(b, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
                b.codex_exec(self.cfg, self.root, "SECRET", "workspace-write")
        self.assertIn("completion exit=0 elapsed=", " ".join(logs.output))
        self.assertNotIn("SECRET", " ".join(logs.output))
        self.assertEqual(run.call_args.kwargs["stdin"], "SECRET")
        self.assertEqual(run.call_args.args[0][1:4], ["exec", "--sandbox", "workspace-write"])

    def test_subprocess_logs_no_arguments_or_output(self):
        with self.assertLogs("tiadect", level="DEBUG") as logs:
            with patch.object(b.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "SECRET", "SECRET")):
                b.run(["tool", "SECRET"])
        self.assertNotIn("SECRET", " ".join(logs.output))


    def test_failure_comments_and_logs_never_include_secrets(self):
        secret = "TOKEN_ENV_PROMPT_COMMAND_OUTPUT_SECRET"
        errors = [
            RuntimeError(secret), ValueError(secret), OSError(secret),
            subprocess.CalledProcessError(1, [secret], output=secret, stderr=secret),
            subprocess.TimeoutExpired(secret, 1, output=secret, stderr=secret),
            b.TaskValidationError(secret),
            type(secret, (Exception,), {})(secret),
        ]
        for error in errors:
            for verbose, quiet in [(False, False), (True, False), (False, True)]:
                with self.subTest(error=type(error), verbose=verbose, quiet=quiet):
                    stream = io.StringIO()
                    with contextlib.redirect_stderr(stream):
                        b.configure_logging(verbose, quiet)
                        with patch.object(b, "set_state"), patch.object(b, "comment") as comments, patch.object(b, "codex_exec", side_effect=error):
                            b.process_issue(self.cfg, {"number": 9, "body": secret, "labels": []})
                    posted = "\n".join(c.args[2] for c in comments.call_args_list)
                    self.assertIn("Tiadect bridge failure", posted)
                    self.assertNotIn(secret, posted + stream.getvalue())

    def test_nonzero_codex_output_is_not_published(self):
        with self.assertLogs("tiadect", level="DEBUG") as logs:
            with patch.object(b, "set_state"), patch.object(b, "comment") as comments, patch.object(b, "codex_exec", return_value=(1, "SECRET_FINAL", "SECRET_EVENTS")):
                b.process_issue(self.cfg, {"number": 10, "body": "SECRET_PROMPT", "labels": []})
        posted = "\n".join(c.args[2] for c in comments.call_args_list)
        self.assertIn("Task failure [codex]", posted)
        self.assertNotIn("SECRET", posted + " ".join(logs.output))

    def test_expected_validation_categories(self):
        cases = [
            ("", "prompt"),
            ('```tiadect\n{"prompt":"SECRET","mode":"SECRET"}\n```', "sandbox"),
            ('```tiadect\nSECRET\n```', "envelope"),
            ('```tiadect\n[]\n```', "envelope"),
        ]
        for body, category in cases:
            with self.assertLogs("tiadect", level="ERROR") as logs:
                with patch.object(b, "set_state"), patch.object(b, "comment") as comments:
                    b.process_issue(self.cfg, {"number": 11, "body": body, "labels": []})
            posted = "\n".join(c.args[2] for c in comments.call_args_list)
            self.assertIn("[" + category + "]", posted)
            self.assertNotIn("SECRET", posted + " ".join(logs.output))
        for path, category in [(self.root.parent, "outside_root"), (self.root / "absent", "checkout")]:
            with self.assertRaises(b.TaskValidationError) as caught:
                b.resolve_repo(self.cfg, str(path))
            self.assertIn("[" + category + "]", b.safe_failure(caught.exception))

if __name__ == "__main__":
    unittest.main()
