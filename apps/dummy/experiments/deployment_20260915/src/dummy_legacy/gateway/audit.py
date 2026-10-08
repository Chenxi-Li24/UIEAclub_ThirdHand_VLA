from dummy_legacy.person_follow.logging import JsonlEventLogger


class GatewayAudit:
    def __init__(self, path):
        self.logger = JsonlEventLogger(path, "gateway_31023")

    def decision(self, decision, **context):
        return self.logger.emit("gateway_decision", level="INFO" if decision.ok else "WARNING", reason_code=decision.reason_code, **context)
