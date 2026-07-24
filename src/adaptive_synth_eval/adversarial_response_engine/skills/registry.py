from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Iterable

import yaml

from .models import AttackSkill

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_VERSION_RE = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$"
)
_SCENARIO_TYPE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ASE_RUNTIME_COMPATIBILITY = "ASE native attack-skill runtime v1"
_MAX_SKILL_FILE_BYTES = 10 * 1024 * 1024
_MAX_RESOURCE_FILE_BYTES = 1024 * 1024
_MAX_PACKAGE_BYTES = 20 * 1024 * 1024
_RESOURCE_EXTENSIONS = {".md", ".json", ".yaml", ".yml", ".csv", ".xml", ".txt"}
_REQUIRED_METADATA = {
    "ase-schema-version",
    "ase-angle",
    "ase-version",
    "ase-sub-tactics",
    "ase-accumulation",
    "ase-scenario-types",
}

BUILTIN_TOOL_NAMES = frozenset(
    {
        "read_skill_resource",
        "search_skill_resources",
        "inspect_target_capabilities",
        "query_attack_memory",
        "transform_payload",
    }
)


class SkillValidationError(ValueError):
    """Raised when a curated skill package violates the supported profile."""


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    if path.stat().st_size > _MAX_SKILL_FILE_BYTES:
        raise SkillValidationError(f"{path}: SKILL.md exceeds 10 MB")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillValidationError(f"{path}: SKILL.md must start with YAML frontmatter")
    try:
        closing = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise SkillValidationError(f"{path}: unterminated YAML frontmatter") from exc
    try:
        frontmatter = yaml.safe_load("\n".join(lines[1:closing]))
    except yaml.YAMLError as exc:
        raise SkillValidationError(f"{path}: invalid YAML frontmatter: {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise SkillValidationError(f"{path}: frontmatter must be a mapping")
    body = "\n".join(lines[closing + 1 :]).strip()
    if not body:
        raise SkillValidationError(f"{path}: instructions body must not be empty")
    return frontmatter, body


def _csv(metadata: dict, key: str, path: Path) -> tuple[str, ...]:
    raw = metadata.get(key)
    if not isinstance(raw, str):
        raise SkillValidationError(f"{path}: metadata.{key} must be a string")
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not values:
        raise SkillValidationError(f"{path}: metadata.{key} must not be empty")
    return values


def _bool(metadata: dict, key: str, path: Path) -> bool:
    raw = str(metadata.get(key, "")).strip().lower()
    if raw not in {"true", "false"}:
        raise SkillValidationError(f"{path}: metadata.{key} must be true or false")
    return raw == "true"


def _package_files(directory: Path) -> Iterable[Path]:
    root = directory.resolve()
    scripts = directory / "scripts"
    if scripts.exists():
        raise SkillValidationError(f"{directory}: scripts/ is not permitted in ASE v1")
    package_bytes = 0
    for candidate in sorted(directory.rglob("*")):
        if candidate.is_symlink():
            try:
                candidate.resolve().relative_to(root)
            except ValueError as exc:
                raise SkillValidationError(
                    f"{candidate}: symlink escapes the skill package"
                ) from exc
        if candidate.is_file():
            try:
                candidate.resolve().relative_to(root)
            except ValueError as exc:
                raise SkillValidationError(f"{candidate}: resource escapes the skill package") from exc
            relative = candidate.relative_to(directory)
            if relative.as_posix() != "SKILL.md":
                if (
                    relative.parts[0] not in {"references", "assets"}
                    or candidate.suffix.lower() not in _RESOURCE_EXTENSIONS
                ):
                    raise SkillValidationError(
                        f"{candidate}: unsupported resource type or package path"
                    )
            size = candidate.stat().st_size
            if relative.as_posix() != "SKILL.md" and size > _MAX_RESOURCE_FILE_BYTES:
                raise SkillValidationError(
                    f"{candidate}: resource exceeds 1 MB"
                )
            package_bytes += size
            if package_bytes > _MAX_PACKAGE_BYTES:
                raise SkillValidationError(
                    f"{directory}: skill package exceeds 20 MB"
                )
            yield candidate


def _digest_package(directory: Path, files: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(directory).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _load_skill(directory: Path, known_tools: frozenset[str]) -> AttackSkill:
    skill_file = directory / "SKILL.md"
    if not skill_file.is_file():
        raise SkillValidationError(f"{directory}: missing SKILL.md")
    frontmatter, instructions = _parse_frontmatter(skill_file)

    name = frontmatter.get("name")
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name) or len(name) > 64:
        raise SkillValidationError(f"{skill_file}: invalid skill name")
    if name != directory.name:
        raise SkillValidationError(
            f"{skill_file}: name {name!r} must match directory {directory.name!r}"
        )
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise SkillValidationError(f"{skill_file}: description must contain 1-1024 characters")
    compatibility = frontmatter.get("compatibility")
    if (
        not isinstance(compatibility, str)
        or _ASE_RUNTIME_COMPATIBILITY not in compatibility
        or len(compatibility) > 500
    ):
        raise SkillValidationError(
            f"{skill_file}: compatibility must declare {_ASE_RUNTIME_COMPATIBILITY!r}"
        )

    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict):
        raise SkillValidationError(f"{skill_file}: metadata must be a mapping")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in metadata.items()
    ):
        raise SkillValidationError(
            f"{skill_file}: ASE metadata must use flat string values"
        )
    missing = sorted(_REQUIRED_METADATA - set(metadata))
    if missing:
        raise SkillValidationError(f"{skill_file}: missing metadata fields: {', '.join(missing)}")
    if str(metadata["ase-schema-version"]) != "1":
        raise SkillValidationError(f"{skill_file}: unsupported ase-schema-version")
    angle = metadata["ase-angle"].strip()
    if not _IDENTIFIER_RE.fullmatch(angle):
        raise SkillValidationError(f"{skill_file}: invalid metadata.ase-angle")
    version = metadata["ase-version"].strip()
    if not _VERSION_RE.fullmatch(version):
        raise SkillValidationError(f"{skill_file}: invalid metadata.ase-version")
    sub_tactics = _csv(metadata, "ase-sub-tactics", skill_file)
    if (
        len(sub_tactics) != len(set(sub_tactics))
        or any(not _IDENTIFIER_RE.fullmatch(value) for value in sub_tactics)
    ):
        raise SkillValidationError(
            f"{skill_file}: invalid or duplicate metadata.ase-sub-tactics"
        )
    scenario_types = _csv(metadata, "ase-scenario-types", skill_file)
    if (
        len(scenario_types) != len(set(scenario_types))
        or any(
            value != "*" and not _SCENARIO_TYPE_RE.fullmatch(value)
            for value in scenario_types
        )
    ):
        raise SkillValidationError(
            f"{skill_file}: invalid or duplicate metadata.ase-scenario-types"
        )

    allowed_raw = frontmatter.get("allowed-tools", "")
    if not isinstance(allowed_raw, str):
        raise SkillValidationError(f"{skill_file}: allowed-tools must be space-delimited text")
    allowed_tools = tuple(part for part in allowed_raw.split() if part)
    unknown = sorted(set(allowed_tools) - known_tools)
    if unknown:
        raise SkillValidationError(f"{skill_file}: unknown tool(s): {', '.join(unknown)}")

    files = tuple(_package_files(directory))
    return AttackSkill(
        name=name,
        description=description.strip(),
        compatibility=compatibility.strip(),
        instructions=instructions,
        directory=directory.resolve(),
        angle=angle,
        version=version,
        sub_tactics=sub_tactics,
        accumulation=_bool(metadata, "ase-accumulation", skill_file),
        scenario_types=scenario_types,
        allowed_tools=allowed_tools,
        package_digest=_digest_package(directory, files),
        note=str(metadata.get("ase-note", "")).strip(),
    )


class AttackSkillRegistry:
    def __init__(self, skills: Iterable[AttackSkill]):
        ordered = tuple(sorted(skills, key=lambda item: item.name))
        if not ordered:
            raise SkillValidationError("attack skill registry must not be empty")
        names = [skill.name for skill in ordered]
        if len(names) != len(set(names)):
            raise SkillValidationError("duplicate attack skill name")
        self.skills = ordered
        self._by_name = {skill.name: skill for skill in ordered}

    @classmethod
    def from_directory(
        cls,
        root: Path,
        *,
        known_tools: Iterable[str] = BUILTIN_TOOL_NAMES,
    ) -> "AttackSkillRegistry":
        root = root.resolve()
        if not root.is_dir():
            raise SkillValidationError(f"{root}: skill catalog directory does not exist")
        known = frozenset(known_tools)
        directories = tuple(
            path for path in sorted(root.iterdir()) if path.is_dir() and not path.name.startswith("_")
        )
        return cls(_load_skill(directory, known) for directory in directories)

    def get(self, name: str) -> AttackSkill:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise SkillValidationError(f"unknown attack skill: {name}") from exc

    def candidates(
        self,
        *,
        angle: str,
        scenario_type: str,
        include: Iterable[str] = (),
    ) -> tuple[AttackSkill, ...]:
        included = frozenset(include)
        return tuple(
            skill
            for skill in self.skills
            if skill.angle == angle
            and skill.supports_scenario(scenario_type)
            and (not included or skill.name in included)
        )

    def selected(self, include: Iterable[str] = ()) -> tuple[AttackSkill, ...]:
        included = frozenset(include)
        if not included:
            return self.skills
        missing = sorted(included - self._by_name.keys())
        if missing:
            raise SkillValidationError(f"unknown attack skill(s): {', '.join(missing)}")
        return tuple(skill for skill in self.skills if skill.name in included)


@lru_cache(maxsize=1)
def get_builtin_registry() -> AttackSkillRegistry:
    catalog = resources.files(__package__).joinpath("catalog")
    return AttackSkillRegistry.from_directory(Path(str(catalog)))
