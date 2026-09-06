"""Immutable analysis settings owned by an agent session."""

from dataclasses import dataclass

from .alignment import AlignmentConfig


@dataclass(frozen=True)
class AnalysisConfig:
    alignment: str = 'exact'
    timestamp_tolerance: float = 0.0
    min_samples: int = 3

    def __post_init__(self):
        AlignmentConfig(self.alignment, self.timestamp_tolerance)
        if type(self.min_samples) is not int or self.min_samples < 3:
            raise ValueError('min_samples must be an integer of at least 3')

    def tool_arguments(self):
        return {'alignment': self.alignment, 'tolerance': self.timestamp_tolerance,
                'min_samples': self.min_samples}
