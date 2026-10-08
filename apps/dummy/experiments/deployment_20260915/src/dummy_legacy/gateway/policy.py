from __future__ import annotations

from dataclasses import dataclass

from .protocol import ExecuteProposalRequest


@dataclass(frozen=True)
class Decision:
    ok: bool
    reason_code: str
    message: dict | None = None


class GatewayPolicy:
    def __init__(self, max_step_deg=0.75):
        self.max_step_deg = float(max_step_deg)
        self._used_proposals = set()

    def authorize_command(self, message):
        if message.get("cmd") in {"ping", "status", "get_state", "software_stop"}:
            return Decision(True, "ALLOWED", dict(message))
        return Decision(False, "COMMAND_BLOCKED")

    def authorize(self, request: ExecuteProposalRequest, leases, current_joints, now: float):
        proposal = request.proposal
        if not leases.valid(request.lease_id, proposal.session_id, now):
            return Decision(False, "LEASE_INVALID")
        if not proposal.is_fresh(now):
            return Decision(False, "PROPOSAL_EXPIRED")
        if proposal.proposal_id in self._used_proposals:
            return Decision(False, "PROPOSAL_REPLAY")
        current = tuple(float(v) for v in current_joints)
        if len(current) != len(proposal.joints_deg):
            return Decision(False, "JOINT_COUNT_MISMATCH")
        if any(abs(target - base) > self.max_step_deg for target, base in zip(proposal.joints_deg, current)):
            return Decision(False, "STEP_LIMIT")
        self._used_proposals.add(proposal.proposal_id)
        return Decision(True, "AUTHORIZED", {"cmd": "move_joint", "joints_deg": list(proposal.joints_deg), "source": "dummy_1023_gateway", "request_id": request.request_id, "proposal_id": proposal.proposal_id})
