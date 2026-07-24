from __future__ import annotations

import base64
import json
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.models import AttackMemory, SessionState
from .models import AttackSkill

_RESOURCE_EXTENSIONS = {".md", ".json", ".yaml", ".yml", ".csv", ".xml", ".txt"}
_MAX_TOOL_OUTPUT_CHARS = 4000


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReadSkillResourceArgs(_StrictModel):
    path: str = Field(min_length=1, max_length=500)


class SearchSkillResourcesArgs(_StrictModel):
    query: str = Field(min_length=1, max_length=200)
    max_results: int = Field(default=5, ge=1, le=10)


class InspectTargetCapabilitiesArgs(_StrictModel):
    pass


class QueryAttackMemoryArgs(_StrictModel):
    failure_threshold: int = Field(default=3, ge=1, le=4)
    per_band: int = Field(default=6, ge=1, le=10)


class TransformPayloadArgs(_StrictModel):
    operation: Literal["base64", "urlencode", "json_escape", "unicode_escape"]
    value: str = Field(max_length=8192)


@dataclass(frozen=True)
class ToolContext:
    skill: AttackSkill
    session: SessionState
    attack_memory: AttackMemory | None
    target_capabilities: dict[str, Any]


@dataclass(frozen=True)
class AttackSkillTool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[BaseModel, ToolContext], Any]
    timeout_seconds: float = 5.0


class ToolExecutionError(RuntimeError):
    pass


def _resource_path(skill: AttackSkill, relative: str) -> Path:
    candidate_relative = Path(relative)
    if candidate_relative.is_absolute() or ".." in candidate_relative.parts:
        raise ToolExecutionError("skill resource path must remain contained in the package")
    if not candidate_relative.parts or candidate_relative.parts[0] not in {"references", "assets"}:
        raise ToolExecutionError("skill resources must be under references/ or assets/")
    root = skill.directory.resolve()
    candidate = (root / candidate_relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ToolExecutionError("skill resource path must remain contained in the package") from exc
    if not candidate.is_file() or candidate.suffix.lower() not in _RESOURCE_EXTENSIONS:
        raise ToolExecutionError("skill resource does not exist or has an unsupported type")
    return candidate


def _read_resource(args: BaseModel, context: ToolContext) -> dict[str, Any]:
    parsed = ReadSkillResourceArgs.model_validate(args)
    path = _resource_path(context.skill, parsed.path)
    with path.open("r", encoding="utf-8") as handle:
        content = handle.read(_MAX_TOOL_OUTPUT_CHARS)
    return {"path": parsed.path, "content": content}


def _search_resources(args: BaseModel, context: ToolContext) -> dict[str, Any]:
    parsed = SearchSkillResourcesArgs.model_validate(args)
    query = parsed.query.casefold()
    matches: list[dict[str, Any]] = []
    for folder in ("references", "assets"):
        root = context.skill.directory / folder
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _RESOURCE_EXTENSIONS:
                continue
            safe_path = _resource_path(context.skill, path.relative_to(context.skill.directory).as_posix())
            text = safe_path.read_text(encoding="utf-8")
            index = text.casefold().find(query)
            if index < 0:
                continue
            start = max(0, index - 160)
            excerpt = text[start : start + 500]
            matches.append(
                {
                    "path": safe_path.relative_to(context.skill.directory).as_posix(),
                    "excerpt": excerpt,
                }
            )
            if len(matches) >= parsed.max_results:
                return {"matches": matches}
    return {"matches": matches}


def _sanitize_endpoint(raw: Any) -> str:
    if not isinstance(raw, str) or not raw:
        return ""
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.hostname:
        return ""
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, "", "", ""))


def _inspect_capabilities(args: BaseModel, context: ToolContext) -> dict[str, Any]:
    InspectTargetCapabilitiesArgs.model_validate(args)
    source = context.target_capabilities
    result: dict[str, Any] = {}
    for key in ("mode", "enabled", "timeout_seconds", "trace_field"):
        value = source.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
    endpoint = _sanitize_endpoint(source.get("endpoint"))
    if endpoint:
        result["endpoint"] = endpoint
    declared_tools = source.get("declared_tools")
    if isinstance(declared_tools, (list, tuple)):
        result["declared_tools"] = [str(name)[:100] for name in declared_tools[:100]]
    return result


def _query_memory(args: BaseModel, context: ToolContext) -> dict[str, Any]:
    parsed = QueryAttackMemoryArgs.model_validate(args)
    if context.attack_memory is None:
        return {
            "summary": "No cross-session attack memory is configured.",
            "skill_stats": {},
            "recent_signals": [],
        }
    stats = context.attack_memory.skill_stats()
    recent = context.attack_memory.recent_entries(parsed.per_band)
    return {
        "summary": context.attack_memory.to_context_str(
            failure_threshold=parsed.failure_threshold,
            per_band=parsed.per_band,
        ),
        "skill_stats": {
            key: {
                "n": stat.n,
                "mean_score": stat.mean_score,
                "any_near_miss": stat.any_near_miss,
            }
            for key, stat in sorted(stats.items())
        },
        "recent_signals": [
            {
                "scenario_type": entry.scenario_type,
                "angle": entry.angle,
                "sub_tactic": entry.sub_tactic,
                "skill_name": entry.skill_name,
                "skill_version": entry.skill_version,
                "failure_score": entry.failure_score,
                "effective_failure_score": entry.effective_failure_score,
                "near_miss": entry.near_miss,
            }
            for entry in recent
        ],
    }


def _transform_payload(args: BaseModel, context: ToolContext) -> dict[str, Any]:
    del context
    parsed = TransformPayloadArgs.model_validate(args)
    if parsed.operation == "base64":
        transformed = base64.b64encode(parsed.value.encode("utf-8")).decode("ascii")
    elif parsed.operation == "urlencode":
        transformed = quote(parsed.value, safe="")
    elif parsed.operation == "json_escape":
        transformed = json.dumps(parsed.value, ensure_ascii=False)[1:-1]
    else:
        transformed = parsed.value.encode("unicode_escape").decode("ascii")
    return {"operation": parsed.operation, "value": transformed}


def _shape(value: Any) -> dict[str, Any]:
    serialized = json.dumps(value, default=str, sort_keys=True)
    return {
        "type": type(value).__name__,
        "characters": len(serialized),
    }


def _truncate_output(value: Any) -> Any:
    serialized = json.dumps(value, default=str)
    if len(serialized) <= _MAX_TOOL_OUTPUT_CHARS:
        return value
    content = serialized[:_MAX_TOOL_OUTPUT_CHARS]
    truncated = {"truncated": True, "content": content}
    while len(json.dumps(truncated)) > _MAX_TOOL_OUTPUT_CHARS and content:
        overflow = len(json.dumps(truncated)) - _MAX_TOOL_OUTPUT_CHARS
        content = content[: max(0, len(content) - overflow)]
        truncated["content"] = content
    return truncated


def _execute_with_timeout(
    tool: AttackSkillTool,
    parsed: BaseModel,
    context: ToolContext,
) -> Any:
    outcome: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def invoke() -> None:
        try:
            outcome.put((True, tool.handler(parsed, context)))
        except BaseException as exc:  # carried back to the calling thread
            outcome.put((False, exc))

    worker = threading.Thread(
        target=invoke,
        name=f"ase-skill-{tool.name}",
        daemon=True,
    )
    worker.start()
    worker.join(timeout=tool.timeout_seconds)
    if worker.is_alive():
        raise ToolExecutionError(
            f"tool {tool.name} exceeded {tool.timeout_seconds:g}s timeout"
        )
    succeeded, value = outcome.get_nowait()
    if succeeded:
        return value
    if isinstance(value, ToolExecutionError):
        raise value
    raise ToolExecutionError(f"tool {tool.name} failed") from value


class AttackSkillToolRegistry:
    def __init__(self, tools: list[AttackSkillTool]):
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("duplicate attack skill tool name")

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def descriptions(self, names: frozenset[str]) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "arguments": tool.args_model.model_json_schema(),
            }
            for name, tool in sorted(self._tools.items())
            if name in names
        ]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> tuple[Any, dict[str, Any]]:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolExecutionError(f"unknown attack skill tool: {name}")
        try:
            parsed = tool.args_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolExecutionError(f"invalid arguments for {name}") from exc

        try:
            result = _execute_with_timeout(tool, parsed, context)
        except ToolExecutionError:
            raise
        result = _truncate_output(result)
        event = {
            "tool": name,
            "status": "success",
            "arguments": _shape(arguments),
            "result": _shape(result),
        }
        return result, event


def build_default_tool_registry() -> AttackSkillToolRegistry:
    return AttackSkillToolRegistry(
        [
            AttackSkillTool(
                name="read_skill_resource",
                description="Read one text resource inside the selected skill package.",
                args_model=ReadSkillResourceArgs,
                handler=_read_resource,
            ),
            AttackSkillTool(
                name="search_skill_resources",
                description="Search text resources inside the selected skill package.",
                args_model=SearchSkillResourcesArgs,
                handler=_search_resources,
            ),
            AttackSkillTool(
                name="inspect_target_capabilities",
                description="Inspect sanitized target capabilities declared by the contract.",
                args_model=InspectTargetCapabilitiesArgs,
                handler=_inspect_capabilities,
            ),
            AttackSkillTool(
                name="query_attack_memory",
                description="Read aggregate, redacted cross-session attack outcome signals.",
                args_model=QueryAttackMemoryArgs,
                handler=_query_memory,
            ),
            AttackSkillTool(
                name="transform_payload",
                description="Apply a deterministic encoding or escaping transform.",
                args_model=TransformPayloadArgs,
                handler=_transform_payload,
            ),
        ]
    )
