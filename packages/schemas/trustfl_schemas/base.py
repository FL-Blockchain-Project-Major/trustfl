"""
Lightweight Pydantic v2 compatible layer fallback when pydantic is not installed in the local environment.
If pydantic is installed, this module transparently re-exports everything from real pydantic.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import (
    Any,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

try:
    from pydantic import (
        AfterValidator,
        BaseModel,
        ConfigDict,
        Field,
        field_validator,
    )
    from pydantic import (
        ValidationError as PydanticValidationError,
    )

    HAVE_REAL_PYDANTIC = True
except ImportError:
    HAVE_REAL_PYDANTIC = False


if not HAVE_REAL_PYDANTIC:

    class PydanticValidationError(ValueError):
        """Mock ValidationError matching pydantic interface."""

        pass

    class ConfigDict(dict):
        def __init__(self, **kwargs: Any):
            super().__init__(**kwargs)

    class FieldInfo:
        def __init__(self, default: Any = ..., **kwargs: Any):
            self.default = default
            self.kwargs = kwargs

    def Field(default: Any = ..., **kwargs: Any) -> Any:
        return FieldInfo(default=default, **kwargs)

    class AfterValidator:
        def __init__(self, func: Callable[[Any], Any]):
            self.func = func

    def field_validator(*fields: str, mode: str = "after") -> Callable:
        def decorator(func: Callable) -> Callable:
            func.__field_validator_fields__ = fields
            func.__field_validator_mode__ = mode
            return func

        return decorator

    T = TypeVar("T", bound="BaseModel")

    def _resolve_type(target_type: Any, val: Any) -> Any:
        """Recursively parses dicts into inner BaseModel / Enum / Primitives."""
        if val is None:
            return None
        origin = get_origin(target_type)
        if origin is Union:
            args = get_args(target_type)
            # Try to resolve to non-NoneType
            non_none = [a for a in args if a is not type(None)]
            for cand in non_none:
                try:
                    return _resolve_type(cand, val)
                except Exception:
                    pass
            return val
        if origin is list:
            elem_type = get_args(target_type)[0] if get_args(target_type) else Any
            if isinstance(val, list):
                return [_resolve_type(elem_type, x) for x in val]
            return val
        if inspect.isclass(target_type):
            if issubclass(target_type, BaseModel) and isinstance(val, dict):
                return target_type.model_validate(val)
            if issubclass(target_type, Enum) and not isinstance(val, Enum):
                return target_type(val)
        return val

    class BaseModel:
        model_config: ConfigDict = ConfigDict()

        def __init__(self, **data: Any):
            # Gather annotations across inheritance hierarchy
            annotations: dict[str, Any] = {}
            for base in self.__class__.__mro__:
                if hasattr(base, "__annotations__"):
                    for k, v in base.__annotations__.items():
                        if k not in annotations:
                            annotations[k] = v

            config = getattr(self.__class__, "model_config", {})
            extra_rule = config.get("extra", "allow")

            # Check extra fields
            for k in data:
                if k not in annotations:
                    if extra_rule == "forbid":
                        raise PydanticValidationError(f"Extra field '{k}' is forbidden")

            # Find validators
            validators: dict[str, list[Callable]] = {}
            for base in self.__class__.__mro__:
                for name, attr in base.__dict__.items():
                    # Handle regular method or classmethod
                    fields = getattr(attr, "__field_validator_fields__", None)
                    if fields is None:
                        underlying = getattr(attr, "__func__", attr)
                        fields = getattr(underlying, "__field_validator_fields__", None)
                    if fields:
                        for f in fields:
                            func_to_call = getattr(self.__class__, name)
                            if func_to_call not in validators.setdefault(f, []):
                                validators[f].append(func_to_call)

            # Process attributes
            for field_name, field_type in annotations.items():
                if field_name in data:
                    val = data[field_name]
                else:
                    default_val = getattr(self.__class__, field_name, ...)
                    if isinstance(default_val, FieldInfo):
                        if default_val.default is not ...:
                            val = default_val.default
                        elif "default_factory" in default_val.kwargs:
                            val = default_val.kwargs["default_factory"]()
                        else:
                            raise PydanticValidationError(f"Missing required field: '{field_name}'")
                    elif default_val is not ...:
                        val = default_val
                    else:
                        raise PydanticValidationError(f"Missing required field: '{field_name}'")

                # Nested model & enum conversion
                val = _resolve_type(field_type, val)

                # Run Annotated AfterValidators
                origin = get_origin(field_type)
                if origin is not None and hasattr(field_type, "__metadata__"):
                    for meta in field_type.__metadata__:
                        if isinstance(meta, AfterValidator):
                            val = meta.func(val)

                # Run field validators
                if field_name in validators:
                    for v_func in validators[field_name]:
                        val = v_func(val)

                # Validate constraints from FieldInfo
                field_def = getattr(self.__class__, field_name, None)
                if isinstance(field_def, FieldInfo):
                    if "min_length" in field_def.kwargs and isinstance(val, (str, bytes, list)):
                        if len(val) < field_def.kwargs["min_length"]:
                            raise PydanticValidationError(
                                f"Field '{field_name}' min_length violation: expected >={field_def.kwargs['min_length']}, got {len(val)}"
                            )
                    if "max_length" in field_def.kwargs and isinstance(val, (str, bytes, list)):
                        if len(val) > field_def.kwargs["max_length"]:
                            raise PydanticValidationError(
                                f"Field '{field_name}' max_length violation: expected <={field_def.kwargs['max_length']}, got {len(val)}"
                            )
                    if "ge" in field_def.kwargs and val is not None:
                        if val < field_def.kwargs["ge"]:
                            raise PydanticValidationError(
                                f"Field '{field_name}' must be >= {field_def.kwargs['ge']}"
                            )
                    if "gt" in field_def.kwargs and val is not None:
                        if val <= field_def.kwargs["gt"]:
                            raise PydanticValidationError(
                                f"Field '{field_name}' must be > {field_def.kwargs['gt']}"
                            )
                    if "le" in field_def.kwargs and val is not None:
                        if val > field_def.kwargs["le"]:
                            raise PydanticValidationError(
                                f"Field '{field_name}' must be <= {field_def.kwargs['le']}"
                            )

                object.__setattr__(self, field_name, val)

            # Freeze check
            if config.get("frozen", False):
                object.__setattr__(self, "_is_frozen", True)

        def __setattr__(self, key: str, value: Any) -> None:
            if getattr(self, "_is_frozen", False):
                raise TypeError(f"Instance of {self.__class__.__name__} is frozen")
            super().__setattr__(key, value)

        def model_dump(self, mode: str = "python") -> dict[str, Any]:
            res = {}
            for k in getattr(self.__class__, "__annotations__", {}):
                v = getattr(self, k, None)
                if isinstance(v, BaseModel):
                    res[k] = v.model_dump(mode=mode)
                elif isinstance(v, list):
                    res[k] = [
                        item.model_dump(mode=mode)
                        if isinstance(item, BaseModel)
                        else (item.value if isinstance(item, Enum) else item)
                        for item in v
                    ]
                elif isinstance(v, Enum):
                    res[k] = v.value
                elif isinstance(v, datetime) and mode == "json":
                    res[k] = v.isoformat()
                else:
                    res[k] = v
            return res

        def model_dump_json(self) -> str:
            def json_encoder(obj: Any) -> Any:
                if isinstance(obj, datetime):
                    return obj.isoformat()
                if isinstance(obj, Enum):
                    return obj.value
                if isinstance(obj, BaseModel):
                    return obj.model_dump(mode="json")
                return str(obj)

            return json.dumps(self.model_dump(mode="json"), default=json_encoder)

        @classmethod
        def model_validate(cls: type[T], obj: Any) -> T:
            if isinstance(obj, dict):
                return cls(**obj)
            if isinstance(obj, cls):
                return obj
            raise ValueError(f"Cannot validate object of type {type(obj)}")

        @classmethod
        def model_validate_json(cls: type[T], json_str: str) -> T:
            data = json.loads(json_str)
            return cls.model_validate(data)

        def __repr__(self) -> str:
            attrs = ", ".join(
                f"{k}={getattr(self, k)!r}" for k in getattr(self.__class__, "__annotations__", {})
            )
            return f"{self.__class__.__name__}({attrs})"

        def __eq__(self, other: Any) -> bool:
            if not isinstance(other, self.__class__):
                return False
            return self.model_dump() == other.model_dump()
