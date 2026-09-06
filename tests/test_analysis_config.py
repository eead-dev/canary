from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict, FrozenInstanceError
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from canary import tools
from canary.agent import ToolDispatcher, run_agent
from canary.agent_cli import main
from canary.analysis_config import AnalysisConfig
from canary.llm.base import ToolCall
from canary.llm.fake import FakeProvider
from canary.observation import Frame


class AnalysisConfigTests(unittest.TestCase):
    def test_validation_and_immutability(self):
        for kwargs in ({'alignment': 'invalid'}, {'timestamp_tolerance': -1},
                       {'timestamp_tolerance': float('nan')}, {'timestamp_tolerance': float('inf')},
                       {'min_samples': 0}, {'min_samples': -1}, {'min_samples': 2}, {'min_samples': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                AnalysisConfig(**kwargs)
        config = AnalysisConfig()
        with self.assertRaises(FrozenInstanceError):
            config.min_samples = 300
        self.assertEqual(asdict(config), {'alignment': 'exact', 'timestamp_tolerance': 0.0, 'min_samples': 3})

    def fixture(self, directory, jitter=0.005, count=301):
        can, ref = Path(directory)/'can.csv', Path(directory)/'reference.csv'
        can.write_text('timestamp,can_id,data\n' + ''.join(
            f'{i/10+jitter},291,{(i%256).to_bytes(8, "little").hex()}\n' for i in range(count)))
        ref.write_text('timestamp,value\n' + ''.join(f'{i/10},{2*(i%256)+5}\n' for i in range(count)))
        return can, ref

    def test_fake_propagation_overrides_shared_run_and_json(self):
        class AttemptedOverrides(FakeProvider):
            def respond(self, system, messages, declarations, schema):
                for declaration in declarations:
                    assert 'tolerance' not in declaration['parameters']['properties']
                    assert 'min_samples' not in declaration['parameters']['properties']
                response = super().respond(system, messages, declarations, schema)
                analysis = next((c for c in response.tool_calls if c.name == 'analyze_candidate'), None)
                if analysis:
                    args = {k: v for k, v in analysis.arguments.items() if k != 'include_fit'}
                    response.tool_calls.append(ToolCall('explicit-fit', 'fit_candidate', args))
                for call in response.tool_calls:
                    if call.name in ('search_candidates', 'analyze_candidate', 'fit_candidate'):
                        call.arguments.update(tolerance=0, min_samples=3)
                return response
        config = AnalysisConfig('nearest', 0.02, 300)
        with tempfile.TemporaryDirectory() as directory:
            can, ref = self.fixture(directory)
            with patch('canary.tools.search_candidates', wraps=tools.search_candidates) as search, \
                 patch('canary.tools.analyze_candidate', wraps=tools.analyze_candidate) as analyze, \
                 patch('canary.tools.fit_candidate', wraps=tools.fit_candidate) as fit:
                result = run_agent(can, ref, 'value', AttemptedOverrides(), analysis_config=config)
            self.assertEqual(result.status, 'complete')
            calls = [c for spy in (search, analyze, fit) for c in spy.call_args_list]
            self.assertTrue(all(spy.called for spy in (search, analyze, fit)))
            for call in calls:
                self.assertEqual({k: call.kwargs[k] for k in ('alignment', 'tolerance', 'min_samples')},
                                 config.tool_arguments())
                self.assertIs(call.kwargs['run'], calls[0].kwargs['run'])
            for event in result.trace:
                if event['name'] in ('search_candidates', 'analyze_candidate', 'fit_candidate'):
                    self.assertEqual(event['analysis_config'], 'session')
            self.assertEqual(result.conclusion.scale, 2)
            self.assertEqual(result.conclusion.offset, 5)
            self.assertEqual(asdict(result)['analysis_config'], asdict(config))
            json.dumps(asdict(result), allow_nan=False)

    def test_default_exact_and_explicit_exact_not_inferred_nearest(self):
        with tempfile.TemporaryDirectory() as directory:
            can, ref = self.fixture(directory, jitter=0, count=4)
            result = run_agent(can, ref, 'value', FakeProvider())
            self.assertEqual(result.status, 'complete')
            self.assertEqual(result.analysis_config, AnalysisConfig())
        frames = [Frame(i+.01, 1, i.to_bytes(8, 'little')) for i in range(4)]
        dispatcher = ToolDispatcher(frames, list(enumerate(range(4))), AnalysisConfig('exact', .02, 3))
        result = dispatcher.dispatch(ToolCall('search', 'search_candidates', {'tolerance': .02}))
        self.assertEqual(result['result']['candidates_ranked'], 0)
        self.assertFalse(dispatcher.dispatch(ToolCall('override', 'search_candidates', {'alignment': 'nearest'}))['ok'])

    def test_cli_config_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            can, ref = self.fixture(directory)
            argv = ['agent', str(can), str(ref), '--value-column', 'value', '--dry-run',
                    '--alignment', 'nearest', '--timestamp-tolerance', '.02', '--min-samples', '300']
            with patch('sys.argv', argv), redirect_stdout(io.StringIO()) as output:
                main()
            self.assertEqual(json.loads(output.getvalue())['analysis_config'],
                             asdict(AnalysisConfig('nearest', .02, 300)))
            for option, value in (('--timestamp-tolerance', '-1'), ('--min-samples', '0'), ('--alignment', 'bad')):
                with patch('sys.argv', argv+[option, value]), patch('canary.agent_cli.FakeProvider') as provider, \
                     redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    main()
                provider.assert_not_called()
