"""Strict manifest and case contracts for the shadow benchmark."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from ..runtime.models import (
    CONTENT_ID_PATTERN,
    SEMVER_PATTERN,
    FrozenModel,
    ReplayBundle,
    RuntimeState,
)


class ScenarioFamily(str, Enum):
    CLEAN_SUCCESS = "clean_success"
    EFFECT_FAIL = "effect_fail"
    EFFECT_UNKNOWN_RESOLVED = "effect_unknown_resolved"
    EFFECT_UNKNOWN_EXHAUSTED = "effect_unknown_exhausted"
    HANDOFF_FAIL = "handoff_fail"
    HANDOFF_UNKNOWN_RESOLVED = "handoff_unknown_resolved"
    STALE_POST_OBSERVATION = "stale_post_observation"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    INVALID_DEPTH_CALIBRATION = "invalid_depth_calibration"
    TIMEOUT_RETRY_GOAL_FAIL = "timeout_retry_goal_fail"


class FailureCategory(str, Enum):
    NONE = "none"
    EFFECT = "effect"
    UNKNOWN = "unknown"
    HANDOFF = "handoff"
    OBSERVATION_ORDER = "observation_order"
    IDENTITY = "identity"
    GEOMETRY = "geometry"
    EXECUTION_AND_GOAL = "execution_and_goal"


class ScenarioExpectation(FrozenModel):
    final_state: RuntimeState
    dispatch_min: int = Field(ge=0)
    dispatch_max: int = Field(ge=0)
    recovery_min: int = Field(ge=0)
    recovery_max: int = Field(ge=0)
    replan_min: int = Field(ge=0, le=1)
    replan_max: int = Field(ge=0, le=1)
    failure_category: FailureCategory

    @model_validator(mode="after")
    def ordered_bounds(self) -> ScenarioExpectation:
        for low, high, name in (
            (self.dispatch_min, self.dispatch_max, "dispatch"),
            (self.recovery_min, self.recovery_max, "recovery"),
            (self.replan_min, self.replan_max, "replan"),
        ):
            if low > high:
                raise ValueError(f"{name} bounds must be ordered")
        if (
            self.final_state is RuntimeState.DONE
            and self.failure_category is not FailureCategory.NONE
        ):
            raise ValueError("successful cases cannot have a failure category")
        return self


class ScenarioCase(FrozenModel):
    schema_version: str
    scenario_id: str = Field(min_length=1)
    family: ScenarioFamily
    condition: Literal["clean", "chained"]
    robot_execution_enabled: Literal[False]
    replay: ReplayBundle
    expectation: ScenarioExpectation

    @field_validator("schema_version")
    @classmethod
    def semantic_version(cls, value: str) -> str:
        if not SEMVER_PATTERN.fullmatch(value):
            raise ValueError("case schema version must be semantic x.y.z")
        return value

    @model_validator(mode="after")
    def episode_matches_case(self) -> ScenarioCase:
        if self.replay.plan.episode_id != self.scenario_id:
            raise ValueError("case ID must equal replay episode ID")
        observation_episodes = {item.episode_id for item in self.replay.observations}
        if observation_episodes != {self.scenario_id}:
            raise ValueError("all observations must belong to the case episode")
        labels = [(item.step_id, item.attempt) for item in self.replay.ground_truth]
        if len(labels) != len(set(labels)):
            raise ValueError("ground-truth labels must be unique")
        return self


class ManifestEntry(FrozenModel):
    scenario_id: str = Field(min_length=1)
    family: ScenarioFamily
    fixture: str = Field(min_length=1)
    content_id: str

    @field_validator("content_id")
    @classmethod
    def content_addressed(cls, value: str) -> str:
        if not CONTENT_ID_PATTERN.fullmatch(value):
            raise ValueError("manifest content ID must be sha256:<64 hex>")
        return value


class _ManifestFile(FrozenModel):
    schema_version: str
    benchmark_id: str = Field(min_length=1)
    robot_execution_enabled: Literal[False]
    entries: tuple[ManifestEntry, ...] = Field(min_length=10, max_length=10)

    @field_validator("schema_version")
    @classmethod
    def semantic_version(cls, value: str) -> str:
        if not SEMVER_PATTERN.fullmatch(value):
            raise ValueError("manifest schema version must be semantic x.y.z")
        return value


class BenchmarkManifest(FrozenModel):
    schema_version: str
    benchmark_id: str
    robot_execution_enabled: Literal[False]
    entries: tuple[ManifestEntry, ...]
    cases: tuple[ScenarioCase, ...]


def load_case(path: Path) -> ScenarioCase:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"case fixture is not a non-symlink regular file: {path}")
    try:
        return ScenarioCase.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid benchmark case {path}: {exc}") from exc


def load_manifest(path: Path) -> BenchmarkManifest:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"manifest is not a non-symlink regular file: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        manifest = _ManifestFile.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"invalid benchmark manifest {path}: {exc}") from exc

    ids = [entry.scenario_id for entry in manifest.entries]
    families = [entry.family for entry in manifest.entries]
    if len(ids) != len(set(ids)):
        raise ValueError("manifest scenario IDs must be unique")
    if set(families) != set(ScenarioFamily):
        raise ValueError("manifest must contain each scenario family exactly once")

    repository = path.resolve().parents[2]
    cases: list[ScenarioCase] = []
    for entry in manifest.entries:
        unresolved = path.parent / entry.fixture
        if unresolved.is_symlink():
            raise ValueError("case fixture must not be a symlink")
        fixture = unresolved.resolve()
        try:
            fixture.relative_to(repository)
        except ValueError as exc:
            raise ValueError("case fixture escapes the repository") from exc
        if not fixture.is_file():
            raise ValueError(f"case fixture is not a regular file: {fixture}")
        actual = "sha256:" + hashlib.sha256(fixture.read_bytes()).hexdigest()
        if actual != entry.content_id:
            raise ValueError(f"case content hash mismatch: {entry.scenario_id}")
        case = load_case(fixture)
        if case.scenario_id != entry.scenario_id or case.family is not entry.family:
            raise ValueError(f"manifest identity mismatch: {entry.scenario_id}")
        cases.append(case)
    return BenchmarkManifest(
        schema_version=manifest.schema_version,
        benchmark_id=manifest.benchmark_id,
        robot_execution_enabled=False,
        entries=manifest.entries,
        cases=tuple(cases),
    )


__all__ = [
    "BenchmarkManifest",
    "FailureCategory",
    "ManifestEntry",
    "ScenarioCase",
    "ScenarioExpectation",
    "ScenarioFamily",
    "load_case",
    "load_manifest",
]
