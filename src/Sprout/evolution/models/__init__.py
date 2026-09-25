"""Evolution domain models: evidence and signals.

Proposal/artifact lifecycle lives in ``Sprout.artifacts.models``; the old
proposal model belonged to the retired observation track.
"""

from Sprout.evolution.models.evidence import EvidenceRef
from Sprout.evolution.models.signals import GrowthSignal, SignalType

__all__ = [
    "EvidenceRef",
    "GrowthSignal",
    "SignalType",
]
