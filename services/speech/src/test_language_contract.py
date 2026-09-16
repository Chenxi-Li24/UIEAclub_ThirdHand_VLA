import json
import unittest

from voice_bridge import ConnectionContext, ProtocolError, VoiceBridge


class FakeTTS:
    def __init__(self):
        self.texts = []

    def synthesize_info(self, text):
        self.texts.append(text)
        return {"audioBase64": "AA==", "mimeType": "audio/mpeg", "text": text}


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


class LanguageCandidateContractTests(unittest.TestCase):
    def test_allowed_tools_map_to_manual_contract(self):
        cases = [
            ("set_joint_angle", {"joint": 1, "target_deg": 2}, "joint.set"),
            ("adjust_joint_angle", {"joint": 2, "delta_deg": 20}, "joint.step"),
            ("open_gripper", {}, "gripper.open"),
            ("close_gripper", {}, "gripper.close"),
            ("get_robot_status", {}, "robot.status"),
            ("go_home", {}, "robot.home"),
        ]
        for tool, arguments, action in cases:
            with self.subTest(tool=tool):
                candidate = VoiceBridge._candidate_from_action(
                    {"tool": tool, "input": arguments}, "test"
                )
                self.assertEqual(candidate["skill"], "manual_joint_control@1")
                self.assertEqual(candidate["payload"]["params"]["action"], action)
                self.assertTrue(candidate["requiresConfirmation"])
                self.assertEqual(candidate["expiresAt"] - candidate["createdAt"], 120_000)

    def test_explicit_multi_joint_candidate_preserves_all_angles(self):
        candidate = VoiceBridge._candidate_from_action(
            {"tool": "move_multiple_joints", "input": {"moves": [
                {"joint": 1, "delta_deg": 10},
                {"joint": 2, "delta_deg": -10},
                {"joint": 3, "target_deg": -20},
            ]}}, "J1 +10, J2 -10, J3 到 -20 度"
        )
        self.assertEqual(candidate["intent"], "joint.multi")
        self.assertEqual(candidate["skill"], "manual_joint_control@1")
        self.assertEqual(candidate["payload"]["params"], {"action": "joint.multi", "moves": [
            {"joint": 1, "deltaDeg": 10},
            {"joint": 2, "deltaDeg": -10},
            {"joint": 3, "targetDeg": -20},
        ]})
        self.assertTrue(candidate["requiresConfirmation"])

    def test_explicit_multi_joint_rejects_invalid_structure(self):
        invalid = [
            [{"joint": 1, "delta_deg": 10}],
            [{"joint": 1, "delta_deg": 10}, {"joint": 1, "delta_deg": -10}],
            [{"joint": 1, "delta_deg": 10, "target_deg": 20}, {"joint": 2, "delta_deg": 1}],
            [{"joint": 1, "delta_deg": 0}, {"joint": 2, "delta_deg": 1}],
            [{"joint": 7, "delta_deg": 1}, {"joint": 2, "delta_deg": 1}],
        ]
        for moves in invalid:
            with self.subTest(moves=moves):
                self.assertIsNone(VoiceBridge._candidate_from_action(
                    {"tool": "move_multiple_joints", "input": {"moves": moves}}, "invalid"
                ))

    def test_stop_is_immediate_and_old_tools_are_rejected(self):
        stop = VoiceBridge._candidate_from_action(
            {"tool": "software_stop", "input": {}}, "停止"
        )
        self.assertEqual(stop["payload"]["params"]["action"], "safety.stop.request")
        self.assertFalse(stop["requiresConfirmation"])
        self.assertIsNone(VoiceBridge._candidate_from_action(
            {"tool": "move_to", "input": {"x": 0, "y": 0, "z": 0}}, "move"
        ))

    def test_coke_request_selects_contract_without_motion(self):
        candidate = VoiceBridge._candidate_from_action(
            {"tool": "pick_and_place_bottle", "input": {}},
            "拿一个可乐放到 B 区",
        )
        self.assertEqual(candidate["skill"], "pick_and_place_bottle@1")
        self.assertEqual(candidate["intent"], "pick_and_place_bottle")
        self.assertEqual(candidate["payload"]["params"], {
            "object": "coke_bottle",
            "destination": {
                "id": "drop_zone_b",
                "type": "configured_drop_zone",
            },
        })
        self.assertNotIn("jointsRad", candidate["payload"]["params"])
        self.assertTrue(candidate["requiresConfirmation"])


class ExactTTSRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_only_staging_rejects_audio_without_loading_asr(self):
        bridge = VoiceBridge(None, None)
        context = ConnectionContext(websocket=FakeSocket())
        with self.assertRaises(ProtocolError) as raised:
            await bridge._start_session(context, {
                "messageId": "message-audio",
                "sessionId": "session-audio",
                "payload": {},
            })
        self.assertEqual(raised.exception.code, "ASR_DISABLED")

    async def test_tts_request_speaks_exact_text_without_llm(self):
        tts = FakeTTS()
        bridge = VoiceBridge(object(), None, tts_bridge=tts)
        socket = FakeSocket()
        context = ConnectionContext(websocket=socket)
        await bridge._handle_tts_request(context, {
            "messageId": "message-1",
            "sessionId": "session-1",
            "payload": {"text": "J1 已达到 1.00 度"},
        })
        self.assertEqual(tts.texts, ["J1 已达到 1.00 度"])
        self.assertEqual([item["type"] for item in socket.sent], [
            "assistant.audio", "session.completed"
        ])


if __name__ == "__main__":
    unittest.main()
