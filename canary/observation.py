"""Read classic CAN CSV observations without signal-layout knowledge."""

from collections import Counter
import csv
from dataclasses import dataclass
import math
from pathlib import Path
import re


def _validate_id(can_id: int) -> None:
    if type(can_id) is not int or not 0 <= can_id <= 0x7FF:
        raise ValueError("CAN ID must be an integer in 0..0x7FF")


@dataclass(frozen=True)
class Frame:
    timestamp: float
    can_id: int
    data: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, (int, float)) or not math.isfinite(self.timestamp):
            raise ValueError("timestamp must be a finite number")
        _validate_id(self.can_id)
        if not isinstance(self.data, bytes) or len(self.data) != 8:
            raise ValueError("payload must be exactly 8 bytes")


def read_csv(path: str | Path) -> list[Frame]:
    """Read frames in file order. IDs accept decimal or 0x-prefixed hex.

    Extra named columns are ignored; duplicate/missing headers and ragged rows
    are errors. Payloads accept contiguous hex or whitespace-separated bytes.
    """
    frames = []
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream, strict=True)
        try:
            header = next(reader, None)
            required = ("timestamp", "can_id", "data")
            if (header is None or len(set(header)) != len(header)
                    or not all(name in header for name in required)):
                raise ValueError("CSV header must contain unique timestamp, can_id, data columns")
            positions = [header.index(name) for name in required]
            for row in reader:
                try:
                    if len(row) != len(header):
                        raise ValueError(f"expected {len(header)} columns, got {len(row)}")
                    timestamp_text, id_text, payload_text = (row[i].strip() for i in positions)
                    try:
                        timestamp = float(timestamp_text)
                    except ValueError:
                        raise ValueError("timestamp must be a finite number") from None
                    if not math.isfinite(timestamp):
                        raise ValueError("timestamp must be a finite number")
                    if not re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)", id_text):
                        raise ValueError("CAN ID must be decimal or 0x-prefixed hexadecimal")
                    can_id = int(id_text, 16 if id_text.lower().startswith("0x") else 10)
                    _validate_id(can_id)
                    try:
                        payload = bytes.fromhex(payload_text)
                    except ValueError:
                        raise ValueError("payload must be valid hexadecimal") from None
                    frames.append(Frame(timestamp, can_id, payload))
                except ValueError as exc:
                    raise ValueError(f"{path}: line {reader.line_num}: {exc}") from exc
        except csv.Error as exc:
            raise ValueError(f"{path}: line {reader.line_num}: malformed CSV: {exc}") from exc
    return frames


def frame_counts(frames: list[Frame]) -> dict[int, int]:
    return dict(sorted(Counter(frame.can_id for frame in frames).items()))


def unique_ids(frames: list[Frame]) -> list[int]:
    return sorted({frame.can_id for frame in frames})


def timestamp_bounds(frames: list[Frame]) -> tuple[float, float] | None:
    """Return earliest/latest timestamps, or None for an empty capture."""
    if not frames:
        return None
    return min(f.timestamp for f in frames), max(f.timestamp for f in frames)


def frames_for_id(frames: list[Frame], can_id: int) -> list[Frame]:
    """Select an ID, retaining file order."""
    _validate_id(can_id)
    return [frame for frame in frames if frame.can_id == can_id]


def update_frequencies(frames: list[Frame]) -> dict[int, float | None]:
    """Estimate average observed Hz as (n-1)/(max time-min time).

    Unordered input is accepted. Duplicate timestamps count as observations.
    Singleton IDs and IDs with zero elapsed time have unavailable frequency.
    """
    result = {}
    for can_id, count in frame_counts(frames).items():
        first, last = timestamp_bounds(frames_for_id(frames, can_id))
        result[can_id] = (count - 1) / (last - first) if count > 1 and last > first else None
    return result


@dataclass(frozen=True)
class CandidateSpec:
    """Normalized bit locator: LE uses LSB0; BE uses MSB0 (not DBC sawtooth).

    LE start_bit is the field's least significant bit. BE start_bit is its most
    significant bit in a stream ordered byte 0 MSB through byte 7 LSB.
    """

    start_bit: int
    width_bits: int
    endian: str = "little"
    signed: bool = False
    can_id: int | None = None

    @property
    def byte_offset(self) -> int | None:
        return self.start_bit // 8 if self.start_bit % 8 == 0 else None

    def __post_init__(self) -> None:
        if self.endian not in ("little", "big"):
            raise ValueError("endian must be little or big")
        if type(self.signed) is not bool:
            raise ValueError("signed must be boolean")
        if self.can_id is not None:
            _validate_id(self.can_id)
        if type(self.width_bits) is not int or self.width_bits not in (8, 12, 16):
            raise ValueError("candidate width must be 8, 12 or 16 bits")
        if (type(self.start_bit) is not int
                or not 0 <= self.start_bit <= 64 - self.width_bits):
            raise ValueError("candidate must fit within the 8-byte payload")
        if self.width_bits == 8 and self.start_bit % 8 == 0:
            object.__setattr__(self, "endian", "little")


def Candidate(byte_offset: int | None = None, width_bits: int | None = None,
              endian: str = "little", signed: bool = False, can_id: int | None = None,
              *, start_bit: int | None = None) -> CandidateSpec:
    """Compatibility constructor: give either a byte offset or a start bit."""
    if start_bit is None:
        if type(byte_offset) is not int:
            raise ValueError("provide an integer byte_offset or start_bit")
        start_bit = byte_offset * 8
    elif byte_offset is not None:
        raise ValueError("provide start_bit or byte_offset, not both")
    return CandidateSpec(start_bit, width_bits, endian, signed, can_id)


def byte_aligned_candidates(can_id: int | None = None) -> list[CandidateSpec]:
    """Legacy 44-configuration subset, retained for compatibility."""
    return [Candidate(offset, width, endian, signed, can_id)
            for width in (8, 16) for offset in range(9 - width // 8)
            for endian in (("little",) if width == 8 else ("little", "big"))
            for signed in (False, True)]


def candidate_fields(can_id: int | None = None) -> list[CandidateSpec]:
    return [CandidateSpec(start, width, endian, signed, can_id)
            for width in (8, 12, 16) for start in range(65 - width)
            for endian in (("little",) if width == 8 and start % 8 == 0 else ("little", "big"))
            for signed in (False, True)]


def decode_words(words: list[int], candidate: CandidateSpec) -> list[int]:
    """Decode pre-parsed payload integers in the candidate's byte order."""
    shift = candidate.start_bit if candidate.endian == "little" else 64 - candidate.start_bit - candidate.width_bits
    modulus = 1 << candidate.width_bits
    mask = modulus - 1
    values = [(word >> shift) & mask for word in words]
    if candidate.signed:
        sign = modulus >> 1
        return [value - modulus if value & sign else value for value in values]
    return values


def extract_candidate(frames: list[Frame], can_id: int,
                      candidate: CandidateSpec) -> list[tuple[float, int]]:
    """Return (timestamp, decoded integer) pairs in file order."""
    if candidate.can_id is not None and candidate.can_id != can_id:
        raise ValueError("candidate CAN ID does not match selected CAN ID")
    selected = frames_for_id(frames, can_id)
    values = decode_words([int.from_bytes(frame.data, candidate.endian) for frame in selected], candidate)
    return [(frame.timestamp, value) for frame, value in zip(selected, values)]
