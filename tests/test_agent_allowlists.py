"""Evidence-derived decision constraints and normal CLI regressions."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import patch

from canary.agent import DECISION_SCHEMA, validate
from canary.agent_evidence import EvidenceRegistry
from canary.agent_cli import main
from canary.llm.base import ModelResponse, ToolCall
from tests import test_agent as fixtures
from tests.test_agent_decision import DecisionProvider


class ConstraintProvider(DecisionProvider):
    def respond(self, system, messages, tools, schema):
        if tools:
            for tool in tools:
                if tool['name'] in ('analyze_candidate', 'fit_candidate'):
                    assert 'byte_offset' not in tool['parameters']['properties']
                    assert 'start_bit' in tool['parameters']['required']
        else:
            prompt = messages[-1].content
            assert prompt['valid_candidate_refs'] == schema['properties']['candidate_ref']['enum']
            assert list(prompt['valid_alternative_refs_by_candidate'].values()) == [[]]
            assert schema['properties']['alternative_refs']['maxItems'] == 0
        return super().respond(system, messages, tools, schema)


class AllowlistTests(unittest.TestCase):
    setUp = fixtures.AgentTests.setUp
    run_provider = fixtures.AgentTests.run_provider

    def test_zero_alternatives_repair_never_accepts_invented_ref(self):
        calls = []
        def mutate(decision):
            calls.append(1)
            if len(calls) == 1:
                decision['alternative_refs'] = ['not-fitted']
        provider = ConstraintProvider(mutate)
        result = self.run_provider(provider)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(len(provider.decisions), 2)
        self.assertEqual(provider.decisions[-1]['alternative_refs'], [])
        self.assertEqual(result.turn_trace[-2]['validation'], 'failed')

    def test_normal_cli_uses_same_constraints(self):
        output = io.StringIO()
        with patch('canary.agent_cli.FakeProvider', ConstraintProvider), patch('sys.argv', [
            'canary.agent_cli', str(self.can), str(self.ref), '--value-column', 'value', '--dry-run']), redirect_stdout(output):
            main()
        result = json.loads(output.getvalue())
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['turn_trace'][-1]['decision']['alternative_refs'], [])

    def test_per_candidate_alternatives_exclude_equivalent_subset(self):
        registry = EvidenceRegistry()
        layouts = [dict(can_id=291, start_bit=i, width_bits=8, endian='little', signed=False) for i in (0, 8, 16)]
        for i, candidate in enumerate(layouts):
            group = {'representative': layouts[0], 'equivalent_candidates': [layouts[1]]} if i < 2 else {
                'representative': candidate, 'equivalent_candidates': []}
            registry.collect('analyze_candidate', {'ok': True, 'result': {**candidate,
                'fit': dict(scale=1, offset=0, rmse=0, mae=0, r_squared=1), 'correlation': 1,
                'equivalence': group, 'affine_equivalents': [], 'ambiguity_reason': 'none'}})
        a, b, c = registry.selectable_refs()
        self.assertEqual(registry.alternative_allowlists(), {a: [c], b: [c], c: [a, b]})
        schema = registry.decision_schema(DECISION_SCHEMA)
        self.assertEqual(schema['properties']['candidate_ref']['enum'], [a, b, c])
        with self.assertRaisesRegex(ValueError, 'non-equivalent'):
            registry.assemble({'candidate_ref': a, 'alternative_refs': [b]}, 'value')
        self.assertNotIn('enum', DECISION_SCHEMA['properties']['candidate_ref'])

    def test_enum_and_empty_array_constraints_reject_invalid_output(self):
        for seed in range(5):
            schema = deepcopy(DECISION_SCHEMA)
            schema['properties']['candidate_ref']['enum'] = ['valid']
            schema['properties']['alternative_refs']['maxItems'] = 0
            decision = dict(candidate_ref='valid', alternative_refs=[f'invented-{seed}'],
                            signal_confidence='high', layout_confidence='low', layout_ambiguous=True, rationale='Evidence')
            with self.assertRaises(ValueError):
                validate(decision, schema)
            decision.update(candidate_ref=f'invented-{seed}', alternative_refs=[])
            with self.assertRaises(ValueError):
                validate(decision, schema)

    def test_model_metadata_omits_redundant_locator(self):
        original = dict(can_id=291, start_bit=1, width_bits=8, endian='little', signed=False, byte_offset=None)
        result = EvidenceRegistry().annotate(original)
        self.assertNotIn('byte_offset', result)
        self.assertIn('byte_offset', original)

    def comparison_run(self, malformed=False):
        class Provider(DecisionProvider):
            calls = 0
            def respond(self, system, messages, tools, schema):
                self.calls += 1
                if self.calls == 1:
                    return ModelResponse(tool_calls=[ToolCall('search', 'search_candidates', {'top_n': 100})])
                if self.calls == 2:
                    top = messages[-1].content['output']['result']['results'][0]
                    return ModelResponse(tool_calls=[ToolCall('fit', 'analyze_candidate', {
                        **{k: top[k] for k in ('can_id', 'start_bit', 'width_bits', 'endian', 'signed')}, 'include_fit': True})])
                if self.calls == 3:
                    evidence = messages[-1].content['output']['result']
                    if malformed:
                        return ModelResponse(text=json.dumps({'start_bit': evidence['start_bit'], 'include_fit': True}))
                    return ModelResponse(conclusion=dict(candidate_ref=evidence['candidate_ref'],
                        alternative_refs=[], signal_confidence='high', layout_confidence='low',
                        layout_ambiguous=True, rationale='Evidence'))
                if self.calls == 4:
                    assert tools
                    feedback = messages[-1].content
                    assert feedback['code'] == 'comparison_evidence_required'
                    candidate = feedback['unfitted_search_comparisons'][0]
                    return ModelResponse(tool_calls=[ToolCall('compare', 'analyze_candidate', {
                        **{k: candidate[k] for k in ('can_id', 'start_bit', 'width_bits', 'endian', 'signed')}, 'include_fit': True})])
                return super().respond(system, messages, tools, schema)
        result = self.run_provider(Provider())
        self.assertEqual(result.status, 'complete')
        self.assertEqual(result.turn_trace[2]['transition'], 'awaiting_comparison_evidence')
        self.assertEqual(result.turn_trace[3]['phase'], 'exploration')
        self.assertTrue(result.conclusion.alternative_candidates)

    def test_missing_search_comparison_keeps_tools_available(self):
        self.comparison_run()

    def test_malformed_analysis_json_does_not_lock_comparison_tools(self):
        self.comparison_run(malformed=True)
