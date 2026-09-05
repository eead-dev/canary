"""Generator-only signal layout; never written into observation CSVs.

Future discovery code must consume datasets, not import this module.
"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class UnsignedField:
    can_id: int
    start_byte: int
    width: int
    scale: float
    offset: float = 0.0

    def __post_init__(self) -> None:
        if not 0 <= self.can_id <= 0x7FF:
            raise ValueError("CAN ID must be standard 11-bit")
        if self.width < 1 or self.start_byte < 0 or self.start_byte + self.width > 8:
            raise ValueError("Field must fit an 8-byte payload")
        if not math.isfinite(self.scale) or self.scale <= 0:
            raise ValueError("Scale must be finite and positive")
        if not math.isfinite(self.offset):
            raise ValueError("Offset must be finite")

    def encode(self, payload: bytearray, physical_value: float) -> None:
        if len(payload) != 8:
            raise ValueError("Payload must contain exactly 8 bytes")
        raw_float = (physical_value - self.offset) / self.scale
        if not math.isfinite(raw_float) or not 0 <= raw_float <= 2 ** (8 * self.width) - 1:
            raise ValueError("Physical value is outside the unsigned field range")
        raw = round(raw_float)
        payload[self.start_byte:self.start_byte + self.width] = raw.to_bytes(self.width, "little")

    def decode(self, payload: bytes) -> float:
        if len(payload) != 8:
            raise ValueError("Payload must contain exactly 8 bytes")
        raw = int.from_bytes(payload[self.start_byte:self.start_byte + self.width], "little")
        return raw * self.scale + self.offset


SPEED = UnsignedField(0x1A4, 2, 2, 0.01)
ACCELERATOR = UnsignedField(0x245, 5, 1, 0.5)
RPM = UnsignedField(0x316, 0, 2, 1.0)
BRAKE_CAN_ID = 0x245
BRAKE_BYTE = 1
BRAKE_MASK = 0x04
NOISE_IDS = (0x083, 0x427, 0x6B2)
