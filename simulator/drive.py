"""A deterministic, simplified longitudinal vehicle model."""

from dataclasses import dataclass

DURATION_SECONDS = 60
SAMPLE_RATE_HZ = 100


@dataclass(frozen=True)
class Sample:
    timestamp: float
    speed_kph: float
    accelerator_pct: float
    brake: bool
    engine_rpm: float


def controls(timestamp: float) -> tuple[float, bool]:
    """Pedal schedule: accelerate, coast, brake, then repeat."""
    for end, accelerator, brake in (
        (3, 0.0, False),
        (15, 65.0, False),
        (22, 0.0, False),
        (27, 0.0, True),
        (40, 80.0, False),
        (48, 25.0, False),
        (53, 0.0, False),
        (60, 0.0, True),
    ):
        if timestamp < end:
            return accelerator, brake
    return 0.0, False


def simulate_drive() -> list[Sample]:
    """Return 6,000 samples over [0, 60) seconds, starting at rest.

    Pedal force opposes rolling/aerodynamic drag; brakes add deceleration.
    RPM follows speed and throttle with a lag in a simplified fixed gear.
    Controls at each sample act over the following 10 ms interval.
    """
    speed_mps = 0.0
    rpm = 800.0
    dt = 1 / SAMPLE_RATE_HZ
    samples = []
    for index in range(DURATION_SECONDS * SAMPLE_RATE_HZ):
        timestamp = index / SAMPLE_RATE_HZ
        accelerator, brake = controls(timestamp)
        samples.append(Sample(timestamp, speed_mps * 3.6, accelerator, brake, rpm))
        acceleration = 3.0 * accelerator / 100 - 0.12 - 0.0015 * speed_mps**2
        if brake:
            acceleration -= 3.5
        speed_mps = max(0.0, speed_mps + acceleration * dt)
        target_rpm = 800 + speed_mps * 3.6 * 35 + accelerator * 8
        rpm += (target_rpm - rpm) * dt / 0.4
    return samples
