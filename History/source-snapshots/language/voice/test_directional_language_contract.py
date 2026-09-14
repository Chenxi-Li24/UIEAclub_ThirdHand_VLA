import math
import unittest

from voice_agent import (
    DIRECTIONAL_LANGUAGE_EXAMPLES,
    ROBOT_TOOLS,
    SYSTEM_PROMPT,
)
from voice_bridge import VoiceBridge


ACTIONS = [
    "turn.left", "turn.right", "lift.up", "lift.down",
    "wrist.pitch.up", "wrist.pitch.down",
    "wrist.yaw.left", "wrist.yaw.right",
    "wrist.roll.clockwise", "wrist.roll.counterclockwise",
]


class DirectionalLanguageContractTests(unittest.TestCase):
    def test_language_examples_cover_every_directional_action_bilingually(self):
        self.assertEqual(set(DIRECTIONAL_LANGUAGE_EXAMPLES), set(ACTIONS))
        for action, examples in DIRECTIONAL_LANGUAGE_EXAMPLES.items():
            with self.subTest(action=action):
                self.assertGreaterEqual(len(examples), 4)
                self.assertTrue(any(not example.isascii() for example in examples))
                self.assertTrue(any(example.isascii() for example in examples))

    def test_language_examples_preserve_agreed_subject_and_motion_distinctions(self):
        self.assertIn("向左一点", DIRECTIONAL_LANGUAGE_EXAMPLES["turn.left"])
        self.assertIn("整个机械臂向左转", DIRECTIONAL_LANGUAGE_EXAMPLES["turn.left"])
        self.assertIn("向右一点", DIRECTIONAL_LANGUAGE_EXAMPLES["turn.right"])
        self.assertIn("帮我看看左边", DIRECTIONAL_LANGUAGE_EXAMPLES["wrist.yaw.left"])
        self.assertIn("镜头看右边", DIRECTIONAL_LANGUAGE_EXAMPLES["wrist.yaw.right"])
        self.assertIn("把夹爪往上抬一下", DIRECTIONAL_LANGUAGE_EXAMPLES["lift.up"])
        self.assertIn("放低一点", DIRECTIONAL_LANGUAGE_EXAMPLES["lift.down"])
        self.assertIn("抬头看看", DIRECTIONAL_LANGUAGE_EXAMPLES["wrist.pitch.up"])
        self.assertIn("低头一点", DIRECTIONAL_LANGUAGE_EXAMPLES["wrist.pitch.down"])

    def test_prompt_exposes_home_gripper_and_top_one_candidate_examples(self):
        for phrase in (
            "回到home", "归位", "回零", "go home",
            "松开夹爪", "open the gripper",
            "把夹爪合上", "close the gripper",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, SYSTEM_PROMPT)
        self.assertIn(
            "Choose exactly one most likely supported interpretation",
            SYSTEM_PROMPT,
        )
        self.assertIn(
            "Do not ask a follow-up clarification when at least one supported action is plausible",
            SYSTEM_PROMPT,
        )
        self.assertNotIn(
            "For genuinely vague requests, ask for clarification",
            SYSTEM_PROMPT,
        )

    def test_prompt_treats_again_as_a_new_candidate_not_a_clarification_chat(self):
        self.assertIn(
            "Treat 再, 再来一点, 再多一点, again, and a little more as a new request",
            SYSTEM_PROMPT,
        )
        self.assertIn(
            "The repeated action still creates a new candidate and requires a new confirmation",
            SYSTEM_PROMPT,
        )
        self.assertNotIn(
            'If the user says only "more", "a lot", 更多, or 再多一些 without a number, ask for clarification',
            SYSTEM_PROMPT,
        )

    def test_directional_tool_exposes_actions_but_not_robot_targets(self):
        tool = next(item for item in ROBOT_TOOLS if item["name"] == "directional_joint_control")
        schema = tool["input_schema"]
        self.assertEqual(schema["properties"]["action"]["enum"], ACTIONS)
        self.assertEqual(schema["properties"]["delta_deg"]["exclusiveMinimum"], 0)
        self.assertEqual(schema["properties"]["delta_deg"]["default"], 20)
        moves = schema["properties"]["moves"]
        self.assertEqual(moves["minItems"], 2)
        self.assertEqual(moves["maxItems"], 5)
        self.assertEqual(moves["items"]["properties"]["action"]["enum"], ACTIONS)
        self.assertEqual(moves["items"]["properties"]["delta_deg"]["default"], 20)
        self.assertNotIn("joints", schema["properties"])
        self.assertNotIn("speed", schema["properties"])
        self.assertNotIn("trajectory", schema["properties"])

    def test_every_action_maps_to_directional_candidate(self):
        for action in ACTIONS:
            with self.subTest(action=action):
                candidate = VoiceBridge._candidate_from_action(
                    {
                        "tool": "directional_joint_control",
                        "input": {"action": action, "delta_deg": 35},
                    },
                    "test input",
                )
                self.assertEqual(candidate["skill"], "directional_joint_control@1")
                self.assertEqual(candidate["intent"], action)
                self.assertEqual(candidate["payload"]["params"], {
                    "action": action,
                    "deltaDeg": 35,
                })
                self.assertTrue(candidate["requiresConfirmation"])
                self.assertEqual(candidate["expiresAt"] - candidate["createdAt"], 120_000)
                self.assertNotIn("joints", candidate["payload"]["params"])
                self.assertNotIn("speedScale", candidate["payload"]["params"])

    def test_unspecified_magnitude_defaults_to_twenty_degrees(self):
        candidate = VoiceBridge._candidate_from_action(
            {"tool": "directional_joint_control", "input": {"action": "turn.left"}},
            "向左转",
        )
        self.assertEqual(candidate["payload"]["params"]["deltaDeg"], 20)

    def test_compound_moves_default_independently_to_twenty_degrees(self):
        candidate = VoiceBridge._candidate_from_action(
            {
                "tool": "directional_joint_control",
                "input": {
                    "moves": [
                        {"action": "lift.up"},
                        {"action": "turn.left"},
                    ],
                },
            },
            "抬高点，向左点",
        )
        self.assertEqual(candidate["intent"], "directional.compound")
        self.assertEqual(candidate["payload"]["params"], {
            "moves": [
                {"action": "lift.up", "deltaDeg": 20},
                {"action": "turn.left", "deltaDeg": 20},
            ],
        })
        self.assertEqual(candidate["args"], candidate["payload"]["params"])

    def test_compound_moves_preserve_shared_or_distinct_explicit_magnitudes(self):
        shared = VoiceBridge._candidate_from_action(
            {"tool": "directional_joint_control", "input": {"moves": [
                {"action": "lift.up", "delta_deg": 10},
                {"action": "turn.left", "delta_deg": 10},
            ]}},
            "抬高并向左 10 度",
        )
        distinct = VoiceBridge._candidate_from_action(
            {"tool": "directional_joint_control", "input": {"moves": [
                {"action": "lift.up", "delta_deg": 10},
                {"action": "turn.left", "delta_deg": 15},
            ]}},
            "抬高 10 度，向左 15 度",
        )
        self.assertEqual(
            [move["deltaDeg"] for move in shared["payload"]["params"]["moves"]],
            [10, 10],
        )
        self.assertEqual(
            [move["deltaDeg"] for move in distinct["payload"]["params"]["moves"]],
            [10, 15],
        )

    def test_compound_rejects_conflicts_invalid_counts_and_mixed_shapes(self):
        invalid = [
            {"moves": [{"action": "turn.left"}]},
            {"moves": [
                {"action": "turn.left"},
                {"action": "turn.right"},
            ]},
            {"moves": [
                {"action": "turn.left"},
                {"action": "turn.left"},
            ]},
            {"moves": [
                {"action": "lift.up", "delta_deg": 0},
                {"action": "turn.left"},
            ]},
            {
                "action": "turn.left",
                "moves": [
                    {"action": "lift.up"},
                    {"action": "turn.left"},
                ],
            },
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                self.assertIsNone(VoiceBridge._candidate_from_action(
                    {"tool": "directional_joint_control", "input": arguments},
                    "invalid compound",
                ))

    def test_prompt_treats_little_as_default_and_coordinated_trailing_angle_as_shared(self):
        self.assertIn('"抬高点，向左点"', SYSTEM_PROMPT)
        self.assertIn('lift.up 20 and turn.left 20', SYSTEM_PROMPT)
        self.assertIn('"抬高并向左 10 度"', SYSTEM_PROMPT)
        self.assertIn('lift.up 10 and turn.left 10', SYSTEM_PROMPT)
        self.assertIn('"抬高 10 度，向左 15 度"', SYSTEM_PROMPT)
        self.assertIn('lift.up 10 and turn.left 15', SYSTEM_PROMPT)

    def test_chinese_and_english_text_preserve_source_but_share_action(self):
        chinese = VoiceBridge._candidate_from_action(
            {"tool": "directional_joint_control", "input": {"action": "lift.up"}},
            "抬高",
        )
        english = VoiceBridge._candidate_from_action(
            {"tool": "directional_joint_control", "input": {"action": "lift.up"}},
            "raise the gripper",
        )
        self.assertEqual(chinese["payload"], english["payload"])
        self.assertEqual(chinese["sourceText"], "抬高")
        self.assertEqual(english["sourceText"], "raise the gripper")

    def test_invalid_action_or_magnitude_never_creates_candidate(self):
        invalid = [
            {"action": "move.forward", "delta_deg": 20},
            {"action": "turn.left", "delta_deg": 0},
            {"action": "turn.left", "delta_deg": -1},
            {"action": "turn.left", "delta_deg": math.nan},
            {"action": "turn.left", "delta_deg": "twenty"},
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                self.assertIsNone(VoiceBridge._candidate_from_action(
                    {"tool": "directional_joint_control", "input": arguments},
                    "invalid",
                ))


if __name__ == "__main__":
    unittest.main()
