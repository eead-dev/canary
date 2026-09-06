"""Run the engineering agent with a selected provider or an offline fake."""

import argparse
from dataclasses import asdict
import json

from .agent import run_agent
from .analysis_config import AnalysisConfig
from .llm.fake import FakeProvider


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("can_log")
    parser.add_argument("reference")
    parser.add_argument("--value-column", required=True)
    parser.add_argument("--provider", choices=("gemini", "openrouter", "ollama", "fake"), default="gemini")
    parser.add_argument("--model", help="required for OpenRouter/Ollama; Gemini defaults to gemini-3.7-flash")
    parser.add_argument('--ollama-max-tokens', type=int, help='optional Ollama output limit; default omitted')
    parser.add_argument("--dry-run", action="store_true", help="use offline fake provider, regardless of provider setting")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument('--max-finalization-attempts', type=int, default=3)
    parser.add_argument("--max-tool-calls", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--base-delay-seconds", type=float, default=1.0)
    parser.add_argument("--max-delay-seconds", type=float, default=8.0)
    parser.add_argument('--alignment', choices=('exact', 'nearest'), default='exact')
    parser.add_argument('--timestamp-tolerance', type=float, default=0.0)
    parser.add_argument('--min-samples', type=int, default=3)
    args = parser.parse_args()
    if args.ollama_max_tokens is not None and (args.provider != 'ollama' or args.ollama_max_tokens <= 0):
        parser.error('--ollama-max-tokens requires --provider ollama and a positive integer')
    provider = None
    try:
        analysis_config = AnalysisConfig(args.alignment, args.timestamp_tolerance, args.min_samples)
        if args.dry_run or args.provider == "fake":
            provider = FakeProvider()
        elif args.provider == 'openrouter':
            from .llm.openrouter import OpenRouterProvider
            provider = OpenRouterProvider(args.model)
        elif args.provider == 'ollama':
            from .llm.ollama import OllamaProvider
            provider = OllamaProvider(args.model, max_tokens=args.ollama_max_tokens)
        else:
            from .llm.gemini import GeminiProvider
            provider = GeminiProvider(args.model if args.model is not None else 'gemini-3.7-flash')
        result = run_agent(args.can_log, args.reference, args.value_column, provider,
                           max_turns=args.max_turns, max_tool_calls=args.max_tool_calls,
                           max_finalization_attempts=args.max_finalization_attempts,
                           max_retries=args.max_retries, base_delay_seconds=args.base_delay_seconds,
                           max_delay_seconds=args.max_delay_seconds, analysis_config=analysis_config)
        print(json.dumps(asdict(result), indent=2, allow_nan=False))
        if result.status != "complete":
            raise SystemExit(1)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    finally:
        if provider is not None and hasattr(provider, "close"):
            provider.close()


if __name__ == "__main__":
    main()
