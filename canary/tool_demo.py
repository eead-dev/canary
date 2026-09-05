"""Demonstrate structured tools deterministically without a model."""

import argparse
import json
from pathlib import Path

from .observation import read_csv
from .reference import read_reference
from .tools import (analyze_candidate, fit_candidate, inspect_can_id, list_can_ids,
                    list_candidate_fields, search_candidates, summarize_capture)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("can_log", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--value-column", required=True)
    args = parser.parse_args()
    try:
        frames = read_csv(args.can_log)
        reference = read_reference(args.reference, args.value_column)
        search = search_candidates(frames, reference, top_n=3)
        output = {"summarize_capture": summarize_capture(frames), "list_can_ids": list_can_ids(frames),
                  "search_candidates": search}
        if search["results"]:
            best = search["results"][0]
            can_id = best["can_id"]
            selection = {"frames": frames, "can_id": can_id, "start_bit": best["start_bit"],
                         "width_bits": best["width_bits"], "reference": reference}
            output.update({"inspect_can_id": inspect_can_id(frames, can_id),
                           "list_candidate_fields": list_candidate_fields(frames, can_id),
                           "analyze_candidate": analyze_candidate(**selection, include_fit=True, endian=best["endian"], signed=best["signed"]),
                           "fit_candidate": fit_candidate(**selection, endian=best["endian"], signed=best["signed"])})
        else:
            output["selection_status"] = "No ranked candidate; selected-candidate tools not invoked."
        print(json.dumps(output, indent=2, allow_nan=False))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
