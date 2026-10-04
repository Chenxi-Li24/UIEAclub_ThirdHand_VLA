from __future__ import annotations


class PersonFollowRuntime:
    def __init__(self, gateway, max_observation_age_s=0.5):
        self.gateway = gateway
        self.max_observation_age_s = float(max_observation_age_s)

    async def handle(self, observation, now: float):
        if now - float(observation.get("captured_at", 0)) > self.max_observation_age_s:
            return "HOLDING"
        if observation.get("identity_state") != "LOCKED" or not observation.get("identity_id"):
            return "HOLDING"
        return "LOCKED"
