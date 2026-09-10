import json
from pathlib import Path

from uiea_thirdhand_vla.orchestration.runtime.models import (
    Argument,
    CommandRequest,
    ExecutorKind,
    ReceiptStatus,
)
from uiea_thirdhand_vla.orchestration.runtime.registry import SkillRegistry
from uiea_thirdhand_vla.orchestration.shadow.execution import (
    ExecutionCapability,
    PreviewBinding,
    PreviewResolver,
    StartouchShadowExecutor,
)
from uiea_thirdhand_vla.orchestration.shadow.startouch_preview import (
    GripperPreview,
    JointWaypointPreview,
    load_shadow_limits,
)

ROOT = Path(__file__).resolve().parents[3]
LIMITS_PATH = ROOT / "configs" / "orchestration" / "startouch_shadow.yaml"
PICK_PATH = ROOT / "configs" / "skills" / "tabletop_pick_shadow.yaml"


def request(*, version: str = "0.1.0") -> CommandRequest:
    return CommandRequest(
        episode_id="episode-1",
        step_id="pick-1",
        skill_id="tabletop.pick",
        contract_version=version,
        attempt=0,
        request_id="episode-1:pick-1:0",
        arguments=(
            Argument(name="target_id", value=7),
            Argument(name="destination_region", value="tray"),
        ),
    )


def binding(*, unsafe: bool = False) -> PreviewBinding:
    waypoint = (0.0, -0.1, -0.2, 0.0, 0.0, 0.0)
    if unsafe:
        waypoint = (0.0, -1.0, -0.2, 0.0, 0.0, 0.0)
    return PreviewBinding(
        skill_id="tabletop.pick",
        contract_version="0.1.0",
        arguments=request().arguments,
        policy_id="shadow.pick",
        policy_version="0.1.0",
        command=JointWaypointPreview(
            command_type="move_joint_path",
            waypoints_rad=(waypoint,),
            time_sec=2.0,
            speed_percent=20.0,
            angle_unit="rad",
        ),
    )


def executor(output: Path, item: PreviewBinding) -> StartouchShadowExecutor:
    return StartouchShadowExecutor(
        output_dir=output,
        resolver=PreviewResolver((item,)),
        limits=load_shadow_limits(LIMITS_PATH),
        capability=ExecutionCapability.shadow(),
    )


def test_shadow_capability_cannot_represent_real_execution():
    capability = ExecutionCapability.shadow()

    assert capability.kind is ExecutorKind.SHADOW
    assert capability.can_execute_world is False
    assert capability.robot_execution_enabled is False
    assert {item.value for item in ExecutorKind} == {"fake", "shadow"}


def test_executor_writes_canonical_content_addressed_preview(tmp_path):
    shadow = executor(tmp_path / "previews", binding())

    receipt = shadow.execute(request())

    assert receipt.status is ReceiptStatus.COMPLETED
    assert shadow.kind is ExecutorKind.SHADOW
    assert shadow.can_execute_world is False
    assert len(receipt.evidence_ids) == 1
    content_id = receipt.evidence_ids[0]
    artifact = tmp_path / "previews" / f"{content_id.removeprefix('sha256:')}.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["evidence_kind"] == "shadow_command_preview"
    assert payload["robot_execution_enabled"] is False
    assert payload["can_execute_world"] is False
    assert payload["command"]["angle_unit"] == "rad"


def test_duplicate_request_is_idempotent(tmp_path):
    shadow = executor(tmp_path / "previews", binding())

    first = shadow.execute(request())
    second = shadow.execute(request())

    assert first == second
    assert len(tuple((tmp_path / "previews").glob("*.json"))) == 1


def test_unknown_version_is_rejected_without_artifact(tmp_path):
    output = tmp_path / "previews"
    shadow = executor(output, binding())

    receipt = shadow.execute(request(version="9.9.9"))

    assert receipt.status is ReceiptStatus.REJECTED
    assert receipt.evidence_ids == ()
    assert not output.exists()


def test_unsafe_preview_is_rejected_without_partial_file(tmp_path):
    output = tmp_path / "previews"
    shadow = executor(output, binding(unsafe=True))

    receipt = shadow.execute(request())

    assert receipt.status is ReceiptStatus.REJECTED
    assert receipt.evidence_ids == ()
    assert not output.exists()


def test_shadow_contract_requires_explicit_shadow_registry():
    registry = SkillRegistry.from_paths(
        (PICK_PATH,), allowed_executor_kinds=(ExecutorKind.SHADOW,)
    )

    contract = registry.resolve("tabletop.pick", "0.1.0")

    assert contract.executor_kind is ExecutorKind.SHADOW
    assert contract.policy_cards[0].executor_kind is ExecutorKind.SHADOW


def test_gripper_binding_requires_exact_arguments(tmp_path):
    item = PreviewBinding(
        skill_id="tabletop.pick",
        contract_version="0.1.0",
        arguments=request().arguments,
        policy_id="shadow.pick",
        policy_version="0.1.0",
        command=GripperPreview(
            command_type="gripper",
            position_normalized=0.5,
            position_unit="normalized",
        ),
    )
    wrong = request().model_copy(
        update={
            "arguments": (
                Argument(name="target_id", value=8),
                Argument(name="destination_region", value="tray"),
            )
        }
    )

    receipt = executor(tmp_path / "previews", item).execute(wrong)

    assert receipt.status is ReceiptStatus.REJECTED
