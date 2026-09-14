"""
VLA tool definitions  tools exposed to the cloud VLA model.

Tools available: select_object, request_clarification, suggest_recovery.
These are advisory only  the VLA cannot directly move the robot.
"""
VLA_TOOLS = [
    {
        "name": "select_object",
        "description": "Choose which detected object to manipulate next.",
        "input_schema": {
            "type": "object",
            "properties": {
                "object_label": {"type": "string"},
                "reasoning": {"type": "string"},
            },
            "required": ["object_label"],
        },
    },
    {
        "name": "request_clarification",
        "description": "Ask the user for clarification when the scene is ambiguous.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "suggest_recovery",
        "description": "Suggest a recovery strategy after a failure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["strategy"],
        },
    },
]
