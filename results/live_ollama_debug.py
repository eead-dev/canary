"""Live diagnostic wrapper: observes the CLI without altering provider responses."""
import json
from pathlib import Path
import sys
from canary.llm import ollama
from canary.llm.errors import provider_error

events = []
destination = Path('results/comma2k19/live_debug_events.json')
original = ollama.OllamaProvider


class ObservedOllama(original):
    def respond(self, system, messages, tools, conclusion_schema):
        event = {'attempt': len(events) + 1, 'tool_count_available': len(tools)}
        for message in reversed(messages):
            if message.role == 'user' and 'selectable_candidate_refs' in message.content:
                event['selectable_candidate_refs'] = message.content['selectable_candidate_refs']
                event['allowed_evidence'] = message.content.get('allowed_evidence', [])
                event['instruction'] = message.content.get('instruction')
                break
        events.append(event)
        destination.write_text(json.dumps(events, indent=2), encoding='utf-8')
        response = super().respond(system, messages, tools, conclusion_schema)
        event['tool_calls'] = [{'name': c.name, 'arguments': c.arguments} for c in response.tool_calls]
        decision = response.conclusion
        if decision is None and response.text:
            try:
                decision = json.loads(response.text)
            except ValueError:
                pass
        if isinstance(decision, dict):
            # Only semantic schema fields: no provider text or reasoning dumps.
            event['decision'] = {k: decision[k] for k in ('candidate_ref', 'signal_confidence',
                'layout_confidence', 'layout_ambiguous', 'alternative_refs') if k in decision}
            if isinstance(decision.get('rationale'), str):
                event['decision']['rationale'] = provider_error(ValueError(decision['rationale']))['message']
        destination.write_text(json.dumps(events, indent=2), encoding='utf-8')
        return response


ollama.OllamaProvider = ObservedOllama
from canary.agent_cli import main
main()
