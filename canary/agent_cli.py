"""Run the engineering agent with Gemini or an offline fake provider."""

import argparse
from dataclasses import asdict
import json

from .agent import run_agent
from .llm.fake import FakeProvider


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("can_log")
    parser.add_argument("reference")
    parser.add_argument("--value-column", required=True)
    parser.add_argument("--provider", choices=("gemini", "fake"), default="gemini")
    parser.add_argument("--model", default="gemini-3.7-flash")
    parser.add_argument("--dry-run", action="store_true", help="use offline fake provider, regardless of provider setting")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--max-tool-calls", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--base-delay-seconds", type=float, default=1.0)
    parser.add_argument("--max-delay-seconds", type=float, default=8.0)
    args = parser.parse_args()
    provider = None
    try:
        if args.dry_run or args.provider == "fake":
            provider = FakeProvider()
        else:
            from .llm.gemini import GeminiProvider
            provider = GeminiProvider(args.model)
        result = run_agent(args.can_log, args.reference, args.value_column, provider,
                           max_turns=args.max_turns, max_tool_calls=args.max_tool_calls,
                           max_retries=args.max_retries, base_delay_seconds=args.base_delay_seconds,
                           max_delay_seconds=args.max_delay_seconds)
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
