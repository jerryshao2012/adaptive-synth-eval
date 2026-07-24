from __future__ import annotations

import json
import time
from collections import deque

import pytest
from pydantic import BaseModel, ConfigDict, Field

from adaptive_synth_eval.adversarial_response_engine.core.models import (
    AttackMemory,
    AttackMemoryEntry,
    SessionState,
)
from adaptive_synth_eval.adversarial_response_engine.skills.executor import (
    NativeAttackSkillExecutor,
    SkillExecutionError,
)
from adaptive_synth_eval.adversarial_response_engine.skills.registry import (
    get_builtin_registry,
)
from adaptive_synth_eval.adversarial_response_engine.skills.tools import (
    AttackSkillTool,
    AttackSkillToolRegistry,
    ToolContext,
    ToolExecutionError,
    build_default_tool_registry,
)


class _QueuedLLM:
    def __init__(self, *responses: dict):
        self.responses = deque(responses)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        return self.responses.popleft()


class _FailingLLM:
    def complete_json(self, system: str, user: str) -> dict:
        del system, user
        raise RuntimeError("provider detail must stay internal")


def _context(skill_name: str = "indirect-priming") -> ToolContext:
    skill = get_builtin_registry().get(skill_name)
    return ToolContext(
        skill=skill,
        session=SessionState(
            session_id="session-1",
            scenario="Test the configured target boundary.",
            scenario_type="prompt-injection",
        ),
        attack_memory=AttackMemory(),
        target_capabilities={
            "mode": "api",
            "endpoint": "https://user:password@example.test/private?token=secret",
            "headers": {"Authorization": "Bearer hidden"},
        },
    )


def test_executor_runs_declared_tool_and_emits_redacted_provenance() -> None:
    llm = _QueuedLLM(
        {
            "action": "call_tool",
            "tool": "transform_payload",
            "arguments": {"operation": "base64", "value": "sensitive-value"},
        },
        {
            "action": "emit_plan",
            "plan": {
                "attack_angle": "ignored",
                "sub_tactic": "context_seeding",
                "model_posture": "guarded",
                "next_generator_instruction": "Use the transformed probe.",
                "risk_level": "medium",
            },
        },
    )
    skill = get_builtin_registry().get("indirect-priming")
    executor = NativeAttackSkillExecutor(
        llm=llm,
        tools=build_default_tool_registry(),
        allowed_tools=frozenset(skill.allowed_tools),
        max_tool_calls=3,
    )

    plan = executor.plan(
        skill=skill,
        context=_context(),
        fixed_angle="indirect_priming",
    )

    assert plan.attack_angle == "indirect_priming"
    assert plan.sub_tactic == "context_seeding"
    assert plan.raw["skill_name"] == "indirect-priming"
    assert plan.raw["skill_version"] == "1.0.0"
    assert plan.raw["skill_package_digest"] == skill.package_digest
    assert plan.raw["skill_tool_events"][0]["tool"] == "transform_payload"
    assert plan.raw["skill_tool_events"][0]["status"] == "success"
    assert "sensitive-value" not in str(plan.raw["skill_tool_events"])
    assert "sensitive-value" not in llm.calls[1][1]
    assert len(llm.calls) == 2


def test_executor_rejects_tool_not_declared_by_skill() -> None:
    llm = _QueuedLLM(
        {
            "action": "call_tool",
            "tool": "inspect_target_capabilities",
            "arguments": {},
        },
        {
            "action": "call_tool",
            "tool": "inspect_target_capabilities",
            "arguments": {},
        },
    )
    skill = get_builtin_registry().get("angle-shift")
    executor = NativeAttackSkillExecutor(
        llm=llm,
        tools=build_default_tool_registry(),
        allowed_tools=frozenset(skill.allowed_tools),
    )

    with pytest.raises(SkillExecutionError, match="not permitted"):
        executor.plan(
            skill=skill, context=_context("angle-shift"), fixed_angle="angle_shift"
        )


def test_executor_stops_after_two_malformed_actions() -> None:
    llm = _QueuedLLM({"unexpected": True}, {"action": "wat"})
    skill = get_builtin_registry().get("angle-shift")
    executor = NativeAttackSkillExecutor(
        llm=llm,
        tools=build_default_tool_registry(),
        allowed_tools=frozenset(skill.allowed_tools),
    )

    with pytest.raises(SkillExecutionError, match="malformed"):
        executor.plan(
            skill=skill, context=_context("angle-shift"), fixed_angle="angle_shift"
        )

    assert len(llm.calls) == 2


def test_executor_strictly_validates_emit_plan_types() -> None:
    invalid = {
        "action": "emit_plan",
        "plan": {
            "attack_angle": "angle_shift",
            "sub_tactic": "academic_frame",
            "model_posture": "guarded",
            "next_generator_instruction": "Continue.",
            "risk_level": "extreme",
            "stop_session": "false",
        },
    }
    llm = _QueuedLLM(invalid, invalid)
    skill = get_builtin_registry().get("angle-shift")
    executor = NativeAttackSkillExecutor(
        llm=llm,
        tools=build_default_tool_registry(),
        allowed_tools=frozenset(skill.allowed_tools),
    )

    with pytest.raises(SkillExecutionError, match="malformed"):
        executor.plan(
            skill=skill,
            context=_context("angle-shift"),
            fixed_angle="angle_shift",
        )


def test_tool_inputs_reject_type_coercion() -> None:
    registry = build_default_tool_registry()

    with pytest.raises(ToolExecutionError, match="invalid arguments"):
        registry.execute(
            "search_skill_resources",
            {"query": "probe", "max_results": "5"},
            _context(),
        )


def test_failed_tools_consume_tool_budget_not_malformed_budget() -> None:
    failed_call = {
        "action": "call_tool",
        "tool": "query_attack_memory",
        "arguments": {"unexpected": "value"},
    }
    llm = _QueuedLLM(
        failed_call,
        failed_call,
        {
            "action": "emit_plan",
            "plan": {
                "attack_angle": "angle_shift",
                "sub_tactic": "academic_frame",
                "model_posture": "guarded",
                "next_generator_instruction": "Continue after tool errors.",
            },
        },
    )
    skill = get_builtin_registry().get("angle-shift")
    executor = NativeAttackSkillExecutor(
        llm=llm,
        tools=build_default_tool_registry(),
        allowed_tools=frozenset(skill.allowed_tools),
        max_tool_calls=3,
        max_malformed_actions=1,
    )

    plan = executor.plan(
        skill=skill,
        context=_context("angle-shift"),
        fixed_angle="angle_shift",
    )

    assert plan.raw["skill_tool_events"] == [
        {
            "tool": "query_attack_memory",
            "status": "error",
            "error": "tool execution failed",
        },
        {
            "tool": "query_attack_memory",
            "status": "error",
            "error": "tool execution failed",
        },
    ]


def test_unpermitted_tool_name_is_redacted_from_events_and_error() -> None:
    secret_name = "secret-token-value"
    llm = _QueuedLLM(
        {"action": "call_tool", "tool": secret_name, "arguments": {}},
        {"action": "call_tool", "tool": secret_name, "arguments": {}},
    )
    skill = get_builtin_registry().get("angle-shift")
    executor = NativeAttackSkillExecutor(
        llm=llm,
        tools=build_default_tool_registry(),
        allowed_tools=frozenset(skill.allowed_tools),
    )

    with pytest.raises(SkillExecutionError) as exc_info:
        executor.plan(
            skill=skill,
            context=_context("angle-shift"),
            fixed_angle="angle_shift",
        )

    assert secret_name not in str(exc_info.value)
    assert secret_name not in str(exc_info.value.events)


def test_executor_enforces_tool_call_cap() -> None:
    tool_call = {
        "action": "call_tool",
        "tool": "query_attack_memory",
        "arguments": {},
    }
    llm = _QueuedLLM(tool_call, tool_call, tool_call, tool_call)
    skill = get_builtin_registry().get("angle-shift")
    executor = NativeAttackSkillExecutor(
        llm=llm,
        tools=build_default_tool_registry(),
        allowed_tools=frozenset(skill.allowed_tools),
        max_tool_calls=3,
    )

    with pytest.raises(SkillExecutionError, match="maximum tool calls"):
        executor.plan(
            skill=skill, context=_context("angle-shift"), fixed_angle="angle_shift"
        )

    assert len(llm.calls) == 4


def test_executor_wraps_provider_failure_as_structured_skill_error() -> None:
    skill = get_builtin_registry().get("angle-shift")
    executor = NativeAttackSkillExecutor(
        llm=_FailingLLM(),
        tools=build_default_tool_registry(),
        allowed_tools=frozenset(skill.allowed_tools),
    )

    with pytest.raises(
        SkillExecutionError,
        match="planner action request failed",
    ) as exc_info:
        executor.plan(
            skill=skill,
            context=_context("angle-shift"),
            fixed_angle="angle_shift",
        )

    assert "provider detail" not in str(exc_info.value)


def test_resource_tool_rejects_parent_traversal() -> None:
    tools = build_default_tool_registry()

    with pytest.raises(ToolExecutionError, match="contained"):
        tools.execute(
            "read_skill_resource",
            {"path": "../SKILL.md"},
            _context(),
        )


def test_capabilities_tool_removes_credentials_and_secrets() -> None:
    result, event = build_default_tool_registry().execute(
        "inspect_target_capabilities",
        {},
        _context("authority-injection"),
    )

    assert result["mode"] == "api"
    assert result["endpoint"] == "https://example.test"
    assert "headers" not in result
    assert "password" not in str(result)
    assert "secret" not in str(result)
    assert event["status"] == "success"


def test_memory_tool_returns_aggregate_skill_and_recent_signals() -> None:
    context = _context("angle-shift")
    context.attack_memory.entries.append(
        AttackMemoryEntry(
            session_id="prior",
            strategy_instruction="do not expose this raw instruction",
            failure_score=2,
            scenario_type="prompt-injection",
            angle="angle_shift",
            sub_tactic="academic_frame",
            skill_name="angle-shift",
            skill_version="1.0.0",
            near_miss=True,
        )
    )

    result, _ = build_default_tool_registry().execute(
        "query_attack_memory",
        {},
        context,
    )

    assert result["skill_stats"]["angle-shift@1.0.0"]["n"] == 1
    assert result["recent_signals"][0]["sub_tactic"] == "academic_frame"
    assert "do not expose" not in str(result)


class _SecretArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(max_length=4)


def _echo_secret(args: BaseModel, context: ToolContext) -> dict:
    del context
    return {"value": str(args.value)}


def _slow_tool(args: BaseModel, context: ToolContext) -> dict:
    del args, context
    time.sleep(0.05)
    return {"ok": True}


def test_tool_validation_error_does_not_echo_secret_arguments() -> None:
    registry = AttackSkillToolRegistry(
        [
            AttackSkillTool(
                name="test_tool",
                description="Test tool.",
                args_model=_SecretArgs,
                handler=_echo_secret,
            )
        ]
    )

    with pytest.raises(ToolExecutionError) as exc_info:
        registry.execute("test_tool", {"value": "do-not-leak"}, _context())

    assert "do-not-leak" not in str(exc_info.value)


def test_tool_timeout_is_reported_without_waiting_for_completion() -> None:
    registry = AttackSkillToolRegistry(
        [
            AttackSkillTool(
                name="slow_tool",
                description="Slow test tool.",
                args_model=_SecretArgs,
                handler=_slow_tool,
                timeout_seconds=0.001,
            )
        ]
    )

    with pytest.raises(ToolExecutionError, match="exceeded"):
        registry.execute("slow_tool", {"value": "safe"}, _context())


def test_tool_output_is_truncated_before_audit_shape_is_recorded() -> None:
    registry = AttackSkillToolRegistry(
        [
            AttackSkillTool(
                name="large_tool",
                description="Large-output test tool.",
                args_model=_SecretArgs,
                handler=lambda args, context: {"content": "x" * 5000},
            )
        ]
    )

    result, event = registry.execute("large_tool", {"value": "safe"}, _context())

    assert result["truncated"] is True
    assert result["content"]
    assert len(json.dumps(result)) <= 4000
    assert event["result"]["characters"] <= 4000
