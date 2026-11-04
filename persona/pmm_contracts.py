"""PMM 2.8 contracts. Model predictions are never observations or permissions."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Protocol, runtime_checkable
import copy, math
from .registry import LONG_IDS, REGISTRY_HASH, digest
from .traits import DISPOSITIONS, ensure_traits

SCHEMA = 'pmm-cooperation/2.8'
BLOCK_IDS = {b: tuple(k for k in LONG_IDS if k.startswith(prefix))
             for b, prefix in [('H', 'hexaco.'), ('V', 'value.'),
                               ('I', 'social.'), ('L', 'style.')]}
BLOCK_IDS['D'] = tuple(DISPOSITIONS)
BLOCK_CONTRACT = {'schema': SCHEMA, 'registry_hash': REGISTRY_HASH,
                  'blocks': {k: list(v) for k, v in BLOCK_IDS.items()}}

def finite(value, name, low=None, high=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(name + ': finite number required')
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(name + ': outside contract range')
    return float(value)

@dataclass(frozen=True)
class Envelope:
    subject_id: str
    scope: str
    event_id: str
    timestamp: float
    prior_revision: int
    evidence_refs: tuple = ()
    model_versions: dict = field(default_factory=dict)
    uncertainty: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    schema_version: str = SCHEMA

    def __post_init__(self):
        for key in ('subject_id', 'scope', 'event_id'):
            if not isinstance(getattr(self, key), str) or not getattr(self, key):
                raise ValueError('Missing ' + key)
        finite(self.timestamp, 'timestamp', 0)
        if type(self.prior_revision) is not int or self.prior_revision < 0:
            raise ValueError('Invalid revision')
        if self.schema_version != SCHEMA or any(not isinstance(x, str) or not x for x in self.evidence_refs):
            raise ValueError('Invalid schema or evidence references')
        digest(asdict(self))  # rejects NaN anywhere in provenance / uncertainty

    def json(self):
        return asdict(self)

@dataclass(frozen=True)
class TurnContext(Envelope):
    turn_id: str = ''
    person_id: str = ''
    text: str = ''

    def __post_init__(self):
        super().__post_init__()
        if not self.turn_id or not self.person_id or not isinstance(self.text, str):
            raise ValueError('Turn identity missing')

@dataclass(frozen=True)
class ComponentResult(Envelope):
    status: str = 'not_ready'
    payload: dict = field(default_factory=dict)
    executed: bool = False

    def __post_init__(self):
        super().__post_init__()
        if self.status not in ('ok', 'not_ready', 'failed', 'uncalibrated', 'disabled') or type(self.executed) is not bool:
            raise ValueError('Invalid component result')
        if not isinstance(self.payload, dict):
            raise ValueError('Invalid component payload')
        digest(self.payload)

class ReasonerAssessment(ComponentResult): pass
class TraitInference(ComponentResult): pass
class EmotionSnapshot(ComponentResult): pass
class RelationshipSnapshot(ComponentResult): pass
class PMMDecision(ComponentResult): pass
class LongitudinalSample(ComponentResult): pass
class TraitUpdateProposal(ComponentResult): pass
class PMMTrace(ComponentResult): pass

def result(cls, ctx, version, payload, status='ok', executed=True, **provenance):
    meta = {k: v for k, v in ctx.json().items() if k in Envelope.__dataclass_fields__}
    meta.update(model_versions={cls.__name__: version}, provenance=provenance)
    return cls(**meta, payload=payload, status=status, executed=executed).json()

def construct_blocks(profile):
    """Read all 68 existing priors without imputing unknown observations."""
    p = ensure_traits(profile)
    if p['trait_profile']['scope'] != 'agent_self':
        raise ValueError('Model-of-other cannot become self personality')
    blocks = {}
    for block, ids in BLOCK_IDS.items():
        fields = p['trait_profile']['dispositions'] if block == 'D' else p['psychology']['features']
        rows = [fields[k] for k in ids]
        blocks[block] = {'ids': list(ids), 'values': [r['estimate'] for r in rows],
                         'mask': [int(r['estimate'] is not None) for r in rows],
                         'uncertainty': [r.get('uncertainty' if block == 'D' else 'posterior_uncertainty') for r in rows],
                         'sources': [{'source_type': r.get('source_type', 'unknown'),
                                      'evidence_refs': copy.deepcopy(r.get('evidence', r.get('evidence_ids', [])))} for r in rows]}
    validate_blocks(blocks)
    return blocks

def validate_blocks(blocks):
    if not isinstance(blocks, dict) or set(blocks) != set(BLOCK_IDS):
        raise ValueError('All five construct blocks are required')
    for b, ids in BLOCK_IDS.items():
        item = blocks[b]
        if item.get('ids') != list(ids) or any(len(item.get(k, [])) != len(ids) for k in ('values', 'mask', 'uncertainty', 'sources')):
            raise ValueError('Construct identity/order/shape mismatch: ' + b)
        for v, m, u, source in zip(item['values'], item['mask'], item['uncertainty'], item['sources']):
            if type(m) is not int or m not in (0, 1) or bool(m) != (v is not None):
                raise ValueError('Unknown must remain null with mask=0')
            if m:
                finite(v, 'trait', 0, 1)
                if u is not None: finite(u, 'uncertainty', 0, 1)
            elif u is not None:
                raise ValueError('Unknown cannot have observed uncertainty')
            if not isinstance(source, dict) or not isinstance(source.get('source_type'), str):
                raise ValueError('Construct source missing')
    return blocks

@runtime_checkable
class ReasonerPort(Protocol):
    version: str
    def analyze(self, ctx, **inputs): ...
@runtime_checkable
class TraitDynamicsPort(Protocol):
    version: str
    def predict(self, ctx, **inputs): ...
@runtime_checkable
class AffectPort(Protocol):
    version: str
    def advance(self, ctx, **inputs): ...
@runtime_checkable
class MemoryEvidencePort(Protocol):
    version: str
    def retrieve(self, ctx, **inputs): ...
@runtime_checkable
class RelationshipPort(Protocol):
    version: str
    def evaluate(self, ctx, **inputs): ...
@runtime_checkable
class DecisionPort(Protocol):
    version: str
    def decide(self, ctx, **inputs): ...
@runtime_checkable
class LongTermEstimatorPort(Protocol):
    version: str
    def estimate(self, ctx, **inputs): ...
@runtime_checkable
class LearningPort(Protocol):
    version: str
    def train(self, **inputs): ...
