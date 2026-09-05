import ast
from contextlib import redirect_stdout
from dataclasses import asdict
import json
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

from canary.agent import CONCLUSION_SCHEMA, TOOL_SCHEMAS, ToolDispatcher, checked_conclusion, run_agent, validate
from canary.llm.base import Message, ModelResponse, ToolCall
from canary.llm.fake import FakeProvider
from canary.observation import Frame


class ScriptProvider:
    def __init__(self, responses):
        self.responses, self.messages = iter(responses), []

    def respond(self, system, messages, tools, conclusion_schema):
        self.messages = list(messages)
        return next(self.responses)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.can, self.ref = [Path(self.directory.name) / p for p in ("can.csv", "ref.csv")]
        self.can.write_text("timestamp,can_id,data\n" + "".join(
            f"{i},291,{i:02X} 00 00 00 00 00 00 00\n" for i in range(4)), encoding="utf-8")
        self.ref.write_text("timestamp,value\n0,5\n1,7\n2,9\n3,11\n", encoding="utf-8")
        self.dispatcher = ToolDispatcher([Frame(i, 291, bytes([i]) + bytes(7)) for i in range(4)],
                                         [(i, 2*i+5) for i in range(4)])

    def run_provider(self, provider, **kwargs):
        return run_agent(self.can, self.ref, "value", provider, **kwargs)

    def test_fake_provider_loop_and_conclusion(self):
        result = self.run_provider(FakeProvider())
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.turns, 3)
        self.assertEqual([e["name"] for e in result.trace],
                         ["summarize_capture", "search_candidates", "inspect_can_id", "analyze_candidate"])
        self.assertEqual(result.conclusion.scale, 2)
        self.assertEqual(result.conclusion.offset, 5)
        self.assertEqual(result.conclusion.selected_candidate["can_id"], 291)
        validate(asdict(result.conclusion), CONCLUSION_SCHEMA)
        json.dumps(asdict(result), allow_nan=False)

    def test_all_tool_dispatch(self):
        for name in TOOL_SCHEMAS:
            args = {}
            if name in ("inspect_can_id", "list_candidate_fields", "analyze_candidate", "fit_candidate"):
                args["can_id"] = 291
            if name in ("analyze_candidate", "fit_candidate"):
                args.update(byte_offset=0, width_bits=8)
            with self.subTest(name=name):
                self.assertTrue(self.dispatcher.dispatch(ToolCall("1", name, args))["ok"])

    def test_argument_validation(self):
        for args in ({}, {"can_id": True}, {"can_id": "291"}, {"can_id": 2048},
                     {"can_id": 291, "path": "anything"}):
            with self.subTest(args=args):
                result = self.dispatcher.dispatch(ToolCall("1", "inspect_can_id", args))
                self.assertEqual(result["error"]["code"], "invalid_arguments")
        result = self.dispatcher.dispatch(ToolCall("1", "analyze_candidate", {"can_id": 291, "byte_offset": 7, "width_bits": 16}))
        self.assertFalse(result["ok"])
        self.assertFalse(self.dispatcher.dispatch(ToolCall("1", "search_candidates", {"tolerance": float("nan")}))["ok"])

    def test_unknown_tool_and_tool_results_returned(self):
        provider = ScriptProvider([ModelResponse(tool_calls=[ToolCall("1", "shell", {})]), ModelResponse()])
        result = self.run_provider(provider, max_turns=2)
        self.assertEqual(result.trace[0]["output"]["error"]["code"], "unknown_tool")
        self.assertTrue(any(m.role == "tool" and not m.content["output"]["ok"] for m in provider.messages))

    def test_maximum_turns(self):
        result = self.run_provider(ScriptProvider([ModelResponse(text="still thinking")] * 2), max_turns=2)
        self.assertEqual(result.status, "max_turns")
        self.assertIsNone(result.conclusion)

    def test_maximum_calls(self):
        provider = ScriptProvider([ModelResponse(tool_calls=[ToolCall(str(i), "summarize_capture", {}) for i in range(3)])])
        result = self.run_provider(provider, max_tool_calls=2)
        self.assertEqual(result.status, "max_tool_calls")
        self.assertEqual(result.trace, [])

    def test_malformed_responses(self):
        for response in (None, {}, ModelResponse(tool_calls=[{}]), ModelResponse(conclusion={})):
            with self.subTest(response=response):
                self.assertEqual(self.run_provider(ScriptProvider([response]), max_turns=1).status, "max_turns")

    def test_duplicate_calls(self):
        result = self.run_provider(ScriptProvider([ModelResponse(tool_calls=[
            ToolCall("same", "summarize_capture", {}), ToolCall("same", "summarize_capture", {})])]), max_turns=1)
        self.assertEqual(result.trace[1]["output"]["error"]["code"], "duplicate_call_id")

    def test_fabricated_conclusion_rejected(self):
        result = self.run_provider(FakeProvider())
        data = asdict(result.conclusion)
        with self.assertRaises(ValueError):
            checked_conclusion(data, "value", [])
        data["scale"] = 99
        with self.assertRaises(ValueError):
            checked_conclusion(data, "value", result.trace)

    def test_provider_failure_is_sanitized(self):
        provider = MagicMock()
        provider.respond.side_effect = RuntimeError("credential-sensitive transport details")
        result = self.run_provider(provider)
        self.assertEqual(result.status, "provider_error")
        self.assertNotIn("credential-sensitive", json.dumps(asdict(result)))
        self.assertEqual(result.error["type"], "RuntimeError")

    def test_provider_diagnostics_preserve_useful_message(self):
        provider = MagicMock()
        provider.respond.side_effect = ValueError("400 INVALID_ARGUMENT: unsupported model configuration")
        with patch.dict("os.environ", {}, clear=True):
            result = self.run_provider(provider)
        self.assertEqual(result.status, "provider_error")
        self.assertEqual(result.error, {"type": "ValueError", "message": "400 INVALID_ARGUMENT: unsupported model configuration"})

    def test_provider_diagnostics_redact_sensitive_details(self):
        from canary.llm.errors import provider_error
        message = ('403 PERMISSION_DENIED\nGEMINI_API_KEY=key-example-123\n'
                   'Authorization: Bearer private-auth\n'
                   'headers={"x-goog-api-key": "header-only-secret"}\n'
                   'password="not-in-environment"\n'
                   'location private/location and private%2Flocation\n'
                   'unlabeled key-example-123\nhttps://example.test/run?token=private-query')
        with patch.dict("os.environ", {"GEMINI_API_KEY": "key-example-123", "OTHER": "private/location"}, clear=True):
            result = provider_error(RuntimeError(message))
        serialized = json.dumps(result)
        self.assertIn("403 PERMISSION_DENIED", serialized)
        for value in ("GEMINI_API_KEY", "Authorization", "private-auth", "header-only-secret",
                      "not-in-environment", "private/location", "private%2Flocation", "key-example-123", "private-query"):
            self.assertNotIn(value, serialized)

    def test_cli_provider_error_json(self):
        from canary.agent_cli import main
        provider = MagicMock()
        provider.respond.side_effect = RuntimeError("404 NOT_FOUND: model unavailable\nAuthorization: Bearer hidden")
        output = io.StringIO()
        with patch("canary.agent_cli.FakeProvider", return_value=provider), patch.dict("os.environ", {}, clear=True), patch("sys.argv", [
            "canary.agent_cli", str(self.can), str(self.ref), "--value-column", "value", "--dry-run"
        ]), redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main()
        self.assertEqual(raised.exception.code, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "provider_error")
        self.assertEqual(result["error"]["type"], "RuntimeError")
        self.assertIn("404 NOT_FOUND", result["error"]["message"])
        self.assertNotIn("hidden", output.getvalue())

    def test_gemini_environment_key_required(self):
        from canary.llm.gemini import GeminiProvider
        with patch.dict("os.environ", {}, clear=True), self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
            GeminiProvider()

    def test_gemini_adapter_offline(self):
        from canary.llm.gemini import GeminiProvider
        # SDK-shaped stubs only: no installed SDK or network is needed.
        class Part:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
            @staticmethod
            def from_text(text):
                return Part(text=text)
        types = SimpleNamespace(Part=Part, FunctionDeclaration=SimpleNamespace, Tool=SimpleNamespace,
                                GenerateContentConfig=SimpleNamespace, AutomaticFunctionCallingConfig=SimpleNamespace,
                                FunctionResponse=SimpleNamespace, HttpOptions=SimpleNamespace)
        chat = MagicMock()
        chat.send_message.return_value = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
            SimpleNamespace(function_call=SimpleNamespace(name="summarize_capture", args={}, id="sdk-id"))]))])
        client = MagicMock()
        client.chats.create.return_value = chat
        genai = SimpleNamespace(Client=MagicMock(return_value=client), types=types)
        with patch.dict("sys.modules", {"google": SimpleNamespace(genai=genai), "google.genai": genai}), patch.dict("os.environ", {"GEMINI_API_KEY": "offline-test-placeholder"}):
            provider = GeminiProvider()
            messages = [Message("user", {"reference_name": "value"})]
            response = provider.respond("system", messages, [], CONCLUSION_SCHEMA)
            self.assertEqual(response.tool_calls[0].name, "summarize_capture")
            self.assertTrue(client.chats.create.call_args.kwargs["config"].automatic_function_calling.disable)
            messages.append(Message("tool", {"id": "1", "name": "summarize_capture", "output": {"ok": True}}))
            provider.respond("system", messages, [], CONCLUSION_SCHEMA)
            self.assertEqual(chat.send_message.call_args.args[0][0].function_response.id, "sdk-id")
            self.assertEqual(client.chats.create.call_count, 1)
            provider.close()
            client.close.assert_called_once()

    def test_recursive_production_isolation(self):
        root = Path(__file__).resolve().parent.parent / "canary"
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("ground_truth", source)
                self.assertNotIn("simulator", source)
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("google"):
                        self.assertEqual(path.name, "gemini.py")

    def test_dry_run_cli_without_sdk(self):
        from canary.agent_cli import main
        output = io.StringIO()
        with patch.dict("sys.modules", {"google.genai": None}), patch("sys.argv", [
            "canary.agent_cli", str(self.can), str(self.ref), "--value-column", "value", "--dry-run"
        ]), redirect_stdout(output):
            main()
        self.assertEqual(json.loads(output.getvalue())["status"], "complete")

    def test_transient_retry_preserves_agent_state(self):
        class TransientError(Exception):
            code = 503
        fake = FakeProvider()
        snapshots = []
        def respond(system, messages, declarations, schema):
            snapshots.append([asdict(m) for m in messages])
            if len(snapshots) == 2:
                raise TransientError("503 UNAVAILABLE")
            return fake.respond(system, messages, declarations, schema)
        provider = MagicMock()
        provider.respond.side_effect = respond
        sleep = MagicMock()
        result = self.run_provider(provider, retry_sleep=sleep, retry_jitter=lambda lo, hi: hi)
        self.assertEqual(result.status, "complete")
        self.assertEqual((result.turns, result.retry_count, result.provider_attempts), (3, 1, 4))
        self.assertEqual(snapshots[1], snapshots[2])
        self.assertEqual([e["name"] for e in result.trace],
                         ["summarize_capture", "search_candidates", "inspect_can_id", "analyze_candidate"])
        sleep.assert_called_once_with(1.0)

    def test_retry_exhaustion_is_sanitized(self):
        class TransientError(Exception):
            code = 503
        provider = MagicMock()
        provider.respond.side_effect = TransientError("503 UNAVAILABLE\nAuthorization: Bearer hidden-key")
        sleep = MagicMock()
        result = self.run_provider(provider, retry_sleep=sleep)
        self.assertEqual(result.status, "provider_error")
        self.assertEqual((result.retry_count, result.provider_attempts, result.turns), (3, 4, 1))
        self.assertEqual(sleep.call_count, 3)
        self.assertNotIn("hidden-key", json.dumps(asdict(result)))

    def test_gemini_retries_same_pending_tool_results(self):
        from canary.llm.gemini import GeminiProvider
        from canary.llm.retry import RetryingProvider
        class TransientError(Exception):
            code = 503
        provider = GeminiProvider.__new__(GeminiProvider)
        provider.types = SimpleNamespace(Part=lambda **kw: SimpleNamespace(**kw), FunctionResponse=SimpleNamespace)
        provider.cursor = 1
        provider.sequence = 0
        provider.call_ids = {"1": "original-id"}
        provider.pending_conclusion = True
        provider.conclusion_id = "conclusion-id"
        provider.chat = MagicMock()
        provider.chat.send_message.side_effect = [TransientError("503"), SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))])]
        messages = [Message("user", {}), Message("tool", {"id": "1", "name": "summarize_capture", "output": {"ok": True}}),
                    Message("user", {"error": {"message": "correct conclusion"}})]
        retry = RetryingProvider(provider, sleep=MagicMock())
        retry.respond("system", messages, [], CONCLUSION_SCHEMA)
        calls = provider.chat.send_message.call_args_list
        self.assertEqual(calls[0].args, calls[1].args)
        self.assertEqual(provider.cursor, len(messages))
        self.assertFalse(provider.pending_conclusion)


if __name__ == "__main__":
    unittest.main()
