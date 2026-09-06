"""Isolated comparison against public Toyota definitions, after blind discovery."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from canary.relationships import compare_raw_series
from canary.observation import CandidateSpec, extract_candidate, frames_for_id, read_csv

COMMIT = '3e92d112129507debe45364891954db70238997a'
SOURCE = f'https://github.com/commaai/opendbc/blob/{COMMIT}/opendbc/dbc/generator/toyota/_toyota_2017.dbc'
DBC_SHA256 = '818872b1c1034983f61a51460a9b175b4bfe01f3d34f537c3d21f420991a8a48'


def parse_signal(text, name, source=None):
    """Read a single non-multiplexed SG_ declaration, not a general DBC importer."""
    can_id = None
    for line in text.splitlines():
        message = re.match(r'BO_ (\d+) ', line)
        if message:
            can_id = int(message[1])
        signal = re.match(r'\s*SG_ (\w+)\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*\(([^,]+),([^\)]+)\)', line)
        if signal and signal[1] == name and can_id is not None:
            dbc_start, width = int(signal[2]), int(signal[3])
            endian = 'little' if signal[4] == '1' else 'big'
            start = dbc_start if endian == 'little' else 8*(dbc_start//8)+7-dbc_start%8
            if not 0 < width <= 64 or not 0 <= start <= 64-width:
                raise ValueError('truth field lies outside classic CAN payload')
            return {'source': source, 'can_id': can_id, 'start_bit': start, 'dbc_start_bit': dbc_start,
                    'width_bits': width, 'endian': endian, 'signed': signal[5] == '-',
                    'scale': float(signal[6]), 'offset': float(signal[7]), 'signal_name': name}
    raise ValueError('requested simple signal declaration not found')


def truth_raw(payload, field):
    # Validation-only extraction can read the published 15-bit truth. This does
    # not add widths to CANary CandidateSpec, enumeration, or discovery.
    shift = field['start_bit'] if field['endian'] == 'little' else 64-field['start_bit']-field['width_bits']
    value = (int.from_bytes(payload, field['endian']) >> shift) & ((1 << field['width_bits'])-1)
    if field['signed'] and value & (1 << (field['width_bits']-1)):
        value -= 1 << field['width_bits']
    return value


def validate_saved(blind_path, can_path, dbc_path, signal='WHEEL_SPEED_RR'):
    # Require a saved completed blind run and verify its input before reading truth.
    blind = json.loads(blind_path.read_text(encoding='utf-8'))
    if not blind.get('completed_utc') or not blind.get('top_fitted'):
        raise ValueError('a completed blind result is required before validation')
    expected = blind['inputs'].get(str(can_path))
    if expected is None or hashlib.sha256(can_path.read_bytes()).hexdigest() != expected:
        raise ValueError('CAN input does not match saved blind experiment')
    best = blind['top_fitted'][0]
    fields = ('can_id', 'start_bit', 'width_bits', 'endian', 'signed', 'scale', 'offset')
    discovered = {k: best[k] for k in fields}
    checksum = hashlib.sha256(dbc_path.read_bytes()).hexdigest()
    if checksum != DBC_SHA256:
        raise ValueError('validation requires the pinned public DBC checksum')
    truth = parse_signal(dbc_path.read_text(encoding='utf-8'), signal, SOURCE)
    truth['dbc_sha256'] = checksum
    frames = frames_for_id(read_csv(can_path), best['can_id'])
    selected = CandidateSpec(best['start_bit'], best['width_bits'], best['endian'], best['signed'], best['can_id'])
    raw = [v for _, v in extract_candidate(frames, best['can_id'], selected)]
    relationship = None
    if truth['can_id'] == best['can_id']:
        actual = [truth_raw(f.data, truth) for f in frames]
        evidence = compare_raw_series(actual, raw)
        if evidence.scale_between_raw is not None:
            relationship = {'equation': 'discovered_raw = multiplier * defined_raw + intercept',
                            'multiplier': evidence.scale_between_raw, 'intercept': evidence.offset_between_raw,
                            'max_absolute_residual_raw': evidence.max_abs_residual, 'frames_checked': len(frames),
                            'relationship_type': evidence.relationship_type, 'rmse_between_raw': evidence.rmse_between_raw}
    proxy = relationship is not None and relationship['multiplier'] != 0 and relationship['max_absolute_residual_raw'] < 1e-8
    notes = [
        'Vehicle identity: dataset dongle mapping plus paper IV-A identify a 2017 Toyota RAV4 Platinum.',
        'Pinned opendbc Toyota RAV4 2017-18 platform uses toyota_new_mc_pt_generated, which imports this definition.',
        'This is a rear-right wheel-speed signal, not an independently established fused vehicle-speed signal.',
        'The selected window is not the declared signal layout. Affine identity is evidence only on this capture.',
        'Raw coefficient differences below compare different encodings; mapped coefficients put them on the defined raw basis.',
        'No OEM/VIN-specific certification is claimed; public definitions establish the comparison.'
    ]
    comparison = {'signal_match': proxy, 'signal_match_basis': 'exact nonconstant affine proxy of the public wheel-speed field on the complete selected-ID capture',
                  'layout_match': all(best[k] == truth[k] for k in fields[:5]),
                  'scale_error': best['scale']-truth['scale'], 'offset_error': best['offset']-truth['offset'],
                  'notes': notes}
    if proxy:
        mapped_scale = best['scale']*relationship['multiplier']
        mapped_offset = best['offset']+best['scale']*relationship['intercept']
        comparison['mapped_scale_error'] = mapped_scale-truth['scale']
        comparison['mapped_offset_error'] = mapped_offset-truth['offset']
    return {'schema_version': 1, 'validated_utc': datetime.now(timezone.utc).isoformat(),
            'blind_results_sha256': hashlib.sha256(blind_path.read_bytes()).hexdigest(),
            'status': 'public_definition_proxy_confirmed' if proxy else 'not_confirmed',
            'discovered': discovered, 'ground_truth': truth, 'comparison': comparison,
            'raw_relationship': relationship,
            'blind_affine_hypotheses': [{k: h[k] for k in ('rank', 'layout_ambiguous', 'ambiguity_reason', 'affine_equivalents')}
                                       for h in blind.get('distinct_hypotheses', []) if h.get('affine_equivalents')],
            'vehicle_evidence': ['https://arxiv.org/html/1812.05752v1#S4.SS1',
                f'https://github.com/commaai/opendbc/blob/{COMMIT}/opendbc/car/toyota/values.py',
                f'https://github.com/commaai/opendbc/blob/{COMMIT}/opendbc/dbc/generator/toyota/toyota_new_mc_pt.dbc']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blind-results', type=Path, default=Path('results/comma2k19/blind_results.json'))
    parser.add_argument('--can-log', type=Path, default=Path('datasets/real/comma2k19/real_can_log.csv'))
    parser.add_argument('--dbc', type=Path, default=Path('validation/comma2k19/toyota_2017.dbc'))
    parser.add_argument('--output', type=Path, default=Path('results/comma2k19/validation.json'))
    args = parser.parse_args()
    try:
        result = validate_saved(args.blind_results, args.can_log, args.dbc)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        print(json.dumps(result, indent=2))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
