"""Prepare the pinned official one-minute example using raw CAN and u-blox GNSS."""

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
from urllib.request import urlopen

COMMIT = '4c7f1a6e1957745beadc1def0e7225f559b09a2a'
SEGMENT = 'b0c9d2329ad1606b|2018-08-02--08-34-47/40'
ROOT = Path('datasets/real/comma2k19')
BASE = f'https://raw.githubusercontent.com/commaai/comma2k19/{COMMIT}/'
PREFIX = 'Example_1/' + SEGMENT.replace('|', '%7C') + '/processed_log/'
FILES = {
    'can_address.npy': ('CAN/raw_can/address', '581d1e63b955b1218b3c4d667878e2c30f67c979df2c5b046f76c4741be0dd5e'),
    'can_data.npy': ('CAN/raw_can/data', '04842858174a318e441f6a1e3f38583d52be135327a43de1e51750ce5cea4938'),
    'can_src.npy': ('CAN/raw_can/src', 'c2ac62cdcb420cd416073f3c30eaaefb51307f2a6ab45e0e4f86eca09c14a935'),
    'can_t.npy': ('CAN/raw_can/t', '57ee5a9875ac96c08e0e5be94a6e4529fa46bb675cbed1727837f98bcafbba79'),
    'gnss_t.npy': ('GNSS/live_gnss_ublox/t', '238794a8b336a9dc69e6787116d6e8fe4ce9013e4f454ca2bcde010b43011e95'),
    'gnss_value.npy': ('GNSS/live_gnss_ublox/value', '1136d8819a640d482c06ed6460efdb84a625ddf765ed581b1cf28f030dabfff3'),
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def download(source):
    source.mkdir(parents=True, exist_ok=True)
    for filename, (remote, expected) in FILES.items():
        path = source / filename
        if path.exists() and sha256(path) == expected:
            continue
        with urlopen(BASE + PREFIX + remote, timeout=60) as response:
            content = response.read(2_000_001)
        if len(content) > 2_000_000 or hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f'{filename}: source size/checksum mismatch')
        path.write_bytes(content)


def ordered(values, name, strict=False):
    if any(not math.isfinite(v) for v in values):
        raise ValueError(f'{name}: timestamps must be finite')
    if any(b <= a if strict else b < a for a, b in zip(values, values[1:])):
        raise ValueError(f'{name}: timestamps must be {"strictly increasing" if strict else "nondecreasing"}')


def convert_can(times, addresses, payloads, sources, bus=0):
    if type(bus) is not int or not 0 <= bus < 128:
        raise ValueError('bus must be an integer in 0..127')
    if len({len(times), len(addresses), len(payloads), len(sources)}) != 1:
        raise ValueError('CAN arrays must have matching lengths')
    ordered(times, 'CAN')
    frames, excluded_extended = [], 0
    for t, address, payload, src in zip(times, addresses, payloads, sources):
        if type(src) is not int or src < 0 or type(address) is not int or not 0 <= address <= 0x1FFFFFFF:
            raise ValueError('CAN source/address must be valid nonnegative integers')
        if not isinstance(payload, bytes) or len(payload) != 8:
            raise ValueError('CAN storage must contain exactly eight bytes per row')
        if src != bus:
            continue
        if address > 0x7FF:
            excluded_extended += 1
            continue
        frames.append((float(t), address, payload.hex(' ').upper()))
    if not frames:
        raise ValueError('selected bus contains no standard CAN frames')
    return frames, {'source_counts': dict(sorted(Counter(sources).items())),
                    'selected_bus': bus, 'excluded_other_sources': sum(s != bus for s in sources),
                    'excluded_extended_ids': excluded_extended}


def convert_gnss(times, values):
    if len(times) != len(values) or not times:
        raise ValueError('GNSS arrays must have equal, nonzero lengths')
    ordered(times, 'GNSS', strict=True)
    result = []
    for t, row in zip(times, values):
        if len(row) != 6 or not math.isfinite(row[2]) or row[2] < 0:
            raise ValueError('GNSS rows require six columns and finite nonnegative speed at column 2')
        speed = float(row[2])*3.6
        if not math.isfinite(speed):
            raise ValueError('converted GNSS speed must be finite')
        result.append((float(t), speed))
    return result


def load_arrays(source):
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError('Preparation requires the optional comma2k19 extra (NumPy)') from exc
    arrays = {name: np.load(source/name, allow_pickle=False) for name in FILES}
    if arrays['gnss_value.npy'].ndim != 2 or arrays['gnss_value.npy'].shape[1] != 6:
        raise ValueError('GNSS value array must have shape (n, 6)')
    for name in ('can_t.npy', 'gnss_t.npy', 'gnss_value.npy'):
        if arrays[name].dtype.kind not in 'fiu':
            raise ValueError(f'{name}: expected numeric storage')
    for name in ('can_t.npy', 'can_address.npy', 'can_src.npy', 'can_data.npy', 'gnss_t.npy'):
        if arrays[name].ndim != 1:
            raise ValueError(f'{name}: expected one-dimensional array')
    for name in ('can_address.npy', 'can_src.npy'):
        if arrays[name].dtype.kind not in 'iu':
            raise ValueError(f'{name}: expected integer storage')
    if arrays['can_data.npy'].dtype != np.dtype('S8'):
        raise ValueError('CAN payload array must use S8 storage')
    # Scalar numpy.bytes_ strips trailing NULs. View the complete S8 storage
    # instead; the source has already discarded original DLC information.
    data = [row.tobytes() for row in arrays['can_data.npy'].view('u1').reshape(-1, 8)]
    return (arrays['can_t.npy'].tolist(), arrays['can_address.npy'].tolist(), data,
            arrays['can_src.npy'].tolist(), arrays['gnss_t.npy'].tolist(), arrays['gnss_value.npy'].tolist())


def prepare(source, output, bus=0):
    # Only the six whitelisted observation arrays may enter preparation.
    provenance = []
    for name, (remote, expected) in FILES.items():
        actual = sha256(source/name)
        if actual != expected:
            raise ValueError(f'{name}: pinned source checksum mismatch')
        provenance.append({'file': name, 'url': BASE+PREFIX+remote, 'sha256': actual,
                           'bytes': (source/name).stat().st_size})
    times, addresses, data, sources, gnss_times, gnss_values = load_arrays(source)
    frames, summary = convert_can(times, addresses, data, sources, bus)
    reference = convert_gnss(gnss_times, gnss_values)
    output.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, header, rows in (('real_can_log.csv', ('timestamp', 'can_id', 'data'), frames),
                               ('real_speed_reference.csv', ('timestamp', 'speed_kph'), reference)):
        path = output/name
        with path.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
        hashes[name] = sha256(path)
    manifest = {'schema_version': 1, 'source': 'comma.ai comma2k19', 'license': 'MIT',
                'repository': 'https://github.com/commaai/comma2k19', 'commit': COMMIT,
                'segment': SEGMENT, 'vehicle': 'Toyota RAV4 (dataset dongle mapping; model year unconfirmed)',
                'files': provenance, 'output_sha256': hashes, 'bus_selection': summary,
                'frame_count': len(frames), 'unique_can_ids': sorted({r[1] for r in frames}),
                'capture_duration_seconds': frames[-1][0]-frames[0][0],
                'first_timestamp': frames[0][0], 'last_timestamp': frames[-1][0],
                'reference_sample_count': len(reference), 'reference_speed_kph_range': [min(r[1] for r in reference), max(r[1] for r in reference)],
                'timestamp_basis': 'device boot time in seconds, unchanged for both inputs',
                'reference_origin': 'live_gnss_ublox/value[:,2] m/s multiplied by 3.6',
                'payload_limitation': 'fixed S8 source storage; original DLC unavailable; all stored bytes preserved'}
    (output/'provenance.json').write_text(json.dumps(manifest, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, default=ROOT/'source')
    parser.add_argument('--output-dir', type=Path, default=ROOT)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--bus', type=int, default=0)
    args = parser.parse_args()
    try:
        if args.download:
            download(args.source_dir)
        print(json.dumps(prepare(args.source_dir, args.output_dir, args.bus), indent=2))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
