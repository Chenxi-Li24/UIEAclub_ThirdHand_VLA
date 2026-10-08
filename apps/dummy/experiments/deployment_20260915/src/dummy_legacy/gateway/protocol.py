from __future__ import annotations

from dataclasses import dataclass

from dummy_legacy.person_follow.contracts import MotionProposal


@dataclass(frozen=True)
class ExecuteProposalRequest:
    request_id: str
    lease_id: str
    proposal: MotionProposal


def validate_request(value):
    if not isinstance(value, dict) or value.get("cmd") != "execute_proposal":
        raise ValueError("unsupported gateway request")
    if not value.get("request_id") or not value.get("lease_id") or not isinstance(value.get("proposal"), dict):
        raise ValueError("missing gateway request fields")
    return ExecuteProposalRequest(value["request_id"], value["lease_id"], MotionProposal.from_dict(value["proposal"]))
