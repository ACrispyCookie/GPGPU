"""Configuration loading and immutable resolved configuration values."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any
import re

import yaml


_PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_MISSING = object()


class ConfigError(ValueError):
    """Raised when project configuration cannot be resolved safely."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(_thaw(item) for item in value)
    return value


def _load_yaml(path: Path, *, required: bool) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise ConfigError(f"Profile not found: {path}")
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"Configuration root must be a mapping: {path}")
    return loaded


def _record_sources(value: Mapping[str, Any], source: str, prefix: str, output: dict[str, str]) -> None:
    for key, item in value.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            _record_sources(item, source, dotted, output)
        else:
            output[dotted] = source


def _merge(target: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    for key, value in incoming.items():
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _merge(current, value)
        else:
            target[key] = _thaw(value)


def _lookup(values: Mapping[str, Any], dotted_key: str, default: Any = _MISSING) -> Any:
    current: Any = values
    for part in dotted_key.split("."):
        if not part or not isinstance(current, Mapping) or part not in current:
            if default is _MISSING:
                raise ConfigError(f"Unknown configuration option: {dotted_key}")
            return default
        current = current[part]
    return current


def _set_dotted(values: dict[str, Any], dotted_key: str, value: Any, *, allow_new: bool) -> None:
    parts = dotted_key.split(".")
    if any(not part for part in parts):
        raise ConfigError(f"Invalid configuration option: {dotted_key!r}")
    if not allow_new:
        _lookup(values, dotted_key)
    current = values
    for part in parts[:-1]:
        child = current.get(part)
        if child is None and allow_new:
            child = {}
            current[part] = child
        if not isinstance(child, dict):
            raise ConfigError(f"Cannot set {dotted_key!r}: {part!r} is not a mapping")
        current = child
    current[parts[-1]] = value


def _parse_override(raw: str) -> tuple[str, Any]:
    if "=" not in raw:
        raise ConfigError(f"Invalid --set value {raw!r}; expected OPTION=VALUE")
    key, raw_value = raw.split("=", 1)
    if not key:
        raise ConfigError(f"Invalid --set value {raw!r}; option name is empty")
    try:
        value = yaml.safe_load(raw_value)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML value in --set {raw!r}: {exc}") from exc
    return key, value


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    """Deeply immutable configuration produced for one CLI invocation."""

    profile: str
    repo_root: Path
    values: Mapping[str, Any]
    provenance: Mapping[str, str]

    def get(self, dotted_key: str, default: Any = _MISSING) -> Any:
        """Return a value by dotted key, or *default* when supplied."""

        return _lookup(self.values, dotted_key, default)

    def source_of(self, dotted_key: str) -> str:
        """Return the layer that supplied the final leaf value."""

        try:
            return self.provenance[dotted_key]
        except KeyError as exc:
            raise ConfigError(f"No source recorded for configuration option: {dotted_key}") from exc

    def repo_path(self, dotted_key: str) -> Path:
        """Resolve a configured path relative to the repository root."""

        raw = self.get(dotted_key)
        if not isinstance(raw, str):
            raise ConfigError(f"Configuration option {dotted_key!r} must be a path string")
        path = Path(raw).expanduser()
        return (path if path.is_absolute() else self.repo_root / path).resolve()

    def to_dict(self) -> dict[str, Any]:
        """Return a mutable copy suitable for serialization."""

        return _thaw(self.values)


@dataclass(frozen=True, slots=True)
class ConfigValidationReport:
    """Errors and warnings found in a resolved configuration."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def _value_kind(value: Any) -> type[Any]:
    if isinstance(value, bool):
        return bool
    if isinstance(value, int):
        return int
    if isinstance(value, float):
        return float
    if isinstance(value, str):
        return str
    if isinstance(value, tuple | list):
        return tuple
    return type(value)


def _validate_options(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    prefix: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    for key, expected_value in expected.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if key not in actual:
            errors.append(f"Missing option: {dotted}")
            continue
        actual_value = actual[key]
        if isinstance(expected_value, Mapping):
            if not isinstance(actual_value, Mapping):
                errors.append(f"Invalid option type: {dotted} must be a mapping")
            else:
                _validate_options(expected_value, actual_value, dotted, errors, warnings)
        elif actual_value is None:
            errors.append(f"Missing value: {dotted} is null")
        elif isinstance(actual_value, Mapping) or _value_kind(actual_value) is not _value_kind(expected_value):
            errors.append(
                f"Invalid option type: {dotted} must be {_value_kind(expected_value).__name__}"
            )

    for key, actual_value in actual.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if key not in expected:
            if isinstance(actual_value, Mapping):
                leaves: list[tuple[str, Any]] = []

                def collect(value: Mapping[str, Any], base: str) -> None:
                    for child_key, child_value in value.items():
                        child = f"{base}.{child_key}"
                        if isinstance(child_value, Mapping):
                            collect(child_value, child)
                        else:
                            leaves.append((child, child_value))

                collect(actual_value, dotted)
                warnings.extend(f"Unknown option: {leaf}" for leaf, _ in leaves)
                if not leaves:
                    warnings.append(f"Unknown option: {dotted}")
            else:
                warnings.append(f"Unknown option: {dotted}")


def validate_config(config: ResolvedConfig) -> ConfigValidationReport:
    """Validate a resolved profile against the canonical default-profile shape."""

    default_path = config.repo_root / "config/profiles/default.yaml"
    expected = _load_yaml(default_path, required=True)
    errors: list[str] = []
    warnings: list[str] = []
    _validate_options(expected, config.values, "", errors, warnings)
    return ConfigValidationReport(tuple(errors), tuple(warnings))


def resolve_config(
    repo_root: str | Path,
    *,
    profile: str = "default",
    overrides: Iterable[str] = (),
    allow_new_keys: bool = False,
) -> ResolvedConfig:
    """Resolve default, selected profile, local, and CLI layers by precedence."""

    if not _PROFILE_NAME.fullmatch(profile):
        raise ConfigError(f"Invalid profile name: {profile!r}")

    root = Path(repo_root).resolve()
    default_path = root / "config" / "profiles" / "default.yaml"
    profile_path = root / "config" / "profiles" / f"{profile}.yaml"
    local_path = root / "config" / "local.yaml"
    default_values = _load_yaml(default_path, required=True)
    profile_values = (
        default_values if profile == "default" else _load_yaml(profile_path, required=True)
    )
    local_values = _load_yaml(local_path, required=False)

    merged: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    layers = [(default_values, default_path)]
    if profile != "default":
        layers.append((profile_values, profile_path))
    layers.append((local_values, local_path))
    for values, source_path in layers:
        _merge(merged, values)
        _record_sources(values, str(source_path), "", provenance)

    for raw_override in overrides:
        key, value = _parse_override(raw_override)
        _set_dotted(merged, key, value, allow_new=allow_new_keys)
        if isinstance(value, Mapping):
            _record_sources(value, "cli", key, provenance)
        else:
            provenance[key] = "cli"

    return ResolvedConfig(
        profile=profile,
        repo_root=root,
        values=_freeze(merged),
        provenance=_freeze(provenance),
    )
