"""Validate operator evidence completeness; never claim to inspect hosting remotely."""
from datetime import datetime, timezone, timedelta
from typing import Literal
from pydantic import Field, model_validator
from app.contracts.common import Contract
from app.contracts.hashing import digest

CONTROLS = ('raw_duplication_off', 'restricted_access', 'metadata_30_days', 'scheduled_purge')


class Observation(Contract):
    status: Literal['CONFIRMED', 'FAILED', 'UNKNOWN']
    # Reference to restricted evidence; do not copy log bodies or secrets here.
    reference: str | None


class LoggingEvidence(Contract):
    schema_version: Literal['r_logging_evidence/v1'] = 'r_logging_evidence/v1'
    service: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    deployed_commit: str = Field(pattern=r'^[0-9a-f]{40}$')
    observed_at: datetime
    reviewer: str = Field(min_length=1)
    controls: dict[str, Observation]

    @model_validator(mode='after')
    def attributed(self):
        if set(self.controls) != set(CONTROLS) or self.observed_at.tzinfo is None:
            raise ValueError('all controls and timezone required')
        if any(not x.strip() for x in (self.service,self.environment,self.reviewer)):
            raise ValueError('explicit attribution required')
        return self


def check_evidence(raw, *, service, environment, deployed_commit, now=None):
    evidence = LoggingEvidence.model_validate(raw)
    now = now or datetime.now(timezone.utc)
    reasons = []
    if (evidence.service,evidence.environment,evidence.deployed_commit) != (service,environment,deployed_commit):
        reasons.append('DEPLOYMENT_MISMATCH')
    if not now - timedelta(days=30) <= evidence.observed_at <= now:
        reasons.append('STALE_OR_FUTURE_OBSERVATION')
    for name, control in evidence.controls.items():
        if control.status != 'CONFIRMED' or not (control.reference and control.reference.strip()):
            reasons.append(name.upper() + '_UNCONFIRMED')
    return dict(schema_version='r_logging_evidence_check/v1', evidence_hash=digest(evidence.model_dump(mode='json')),
        status='BLOCKED' if reasons else 'READY_FOR_REVIEW', reasons=reasons,
        hosting_verified_by_tool=False)
