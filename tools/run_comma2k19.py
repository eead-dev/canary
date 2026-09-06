"""Blind experiment: only normalized CAN/reference CSVs enter discovery."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from canary.analysis import AnalysisRun
from canary.discovery import discover_signal
from canary.fitting import fit_ranked, write_reconstruction
from canary.observation import CandidateSpec, read_csv, timestamp_bounds, unique_ids
from canary.reference import read_reference
from canary.reporting import write_report


def experiment(can_path, reference_path, output, tolerance=0.02, min_samples=300):
    if any((output/name).resolve() in (can_path.resolve(), reference_path.resolve())
           for name in ('blind_results.json', 'reconstructed.csv', 'report.html')):
        raise ValueError('experiment output must not overwrite an input')
    frames = read_csv(can_path)
    reference = read_reference(reference_path, 'speed_kph')
    run = AnalysisRun(frames, reference, alignment='nearest', tolerance=tolerance)
    ranked = discover_signal(frames, reference, run=run, alignment='nearest',
                             tolerance=tolerance, min_samples=min_samples)
    top = fit_ranked(frames, reference, ranked[:10], run=run, alignment='nearest',
                     tolerance=tolerance, min_samples=min_samples)
    if not top:
        raise ValueError('No fitted candidates meet the declared coverage threshold')
    distinct, seen = [], set()
    for rank, result in enumerate(ranked, 1):
        representative = result.equivalence.representative
        if representative not in seen:
            distinct.append((rank, result))
            seen.add(representative)
        if len(distinct) == 5:
            break
    fits = fit_ranked(frames, reference, [r for _, r in distinct], run=run, alignment='nearest',
                      tolerance=tolerance, min_samples=min_samples)
    first, last = timestamp_bounds(frames)
    compared = [CandidateSpec(r.start_bit, r.width_bits, r.endian, r.signed, r.can_id) for r in fits]
    hypotheses = [{'rank': rank, **asdict(fit), **run.ambiguity(candidate, compared)}
                  for (rank, _), fit, candidate in zip(distinct, fits, compared)]
    result = {'schema_version': 1, 'completed_utc': datetime.now(timezone.utc).isoformat(),
              'inputs': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (can_path, reference_path)},
              'alignment': 'nearest', 'tolerance_seconds': tolerance, 'min_samples': min_samples,
              'frame_count': len(frames), 'unique_can_ids': unique_ids(frames),
              'capture_duration_seconds': last-first, 'reference_samples': len(reference),
              'candidates_ranked': len(ranked), 'performance': run.statistics(),
              'top_fitted': [asdict(r) for r in top],
              'distinct_hypotheses': hypotheses}
    output.mkdir(parents=True, exist_ok=True)
    (output/'blind_results.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    write_reconstruction(output/'reconstructed.csv', frames, reference, top[0], run=run,
                         alignment='nearest', tolerance=tolerance)
    write_report(output/'report.html', frames, reference, top, 'speed_kph', run=run,
                 alignment='nearest', tolerance=tolerance)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--can-log', type=Path, default=Path('datasets/real/comma2k19/real_can_log.csv'))
    parser.add_argument('--reference', type=Path, default=Path('datasets/real/comma2k19/real_speed_reference.csv'))
    parser.add_argument('--output-dir', type=Path, default=Path('results/comma2k19'))
    parser.add_argument('--tolerance', type=float, default=0.02)
    parser.add_argument('--min-samples', type=int, default=300)
    args = parser.parse_args()
    try:
        result = experiment(args.can_log, args.reference, args.output_dir, args.tolerance, args.min_samples)
        print(json.dumps({k: v for k, v in result.items() if k != 'top_fitted'}, indent=2))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
