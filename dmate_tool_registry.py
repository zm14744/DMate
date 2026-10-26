"""Allowlisted local tools with JSON contracts and source-bound audit records.

Handlers are trusted application functions, never model-supplied code. The
deadline is cooperative: CPU tools must bound their inputs and call
``context.check_deadline()`` in loops. A tool requiring a hard deadline must
use its own terminable worker. No thread is abandoned and called cancelled.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


ROLES = frozenset({
    'page_vertices', 'body_text', 'connections', 'attributes',
    'structure_review', 'solver',
})
MAX_JSON_BYTES = 4_000_000
MAX_JSON_NODES = 400_000
MAX_JSON_DEPTH = 32
_NAME = re.compile(r'^[a-z][a-z0-9_.]{0,63}$')
_SHA256 = re.compile(r'^[0-9a-fA-F]{64}$')


class _JsonCapacity(ValueError):
    pass


class ToolFailure(Exception):
    """An expected, public error code. Never put private input in its value."""

    def __init__(self, code: str):
        if not isinstance(code, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', code):
            raise ValueError('invalid_tool_error_code')
        self.code = code
        super().__init__(code)


class ToolTimeout(ToolFailure):
    def __init__(self):
        super().__init__('tool_timeout')


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    description: str
    input_schema: dict
    output_schema: dict
    allowed_roles: frozenset[str]
    source_required: bool = True
    timeout_seconds: float = 5.0


@dataclass(frozen=True)
class ToolContext:
    """Private job material; only source_sha256 enters the audit envelope.

    ``data`` may contain DocumentEvidence and immutable graph snapshots. It is
    not serialized to the model or the audit. Read-only handlers must copy a
    graph before deriving an analysis view; a top-level mapping is protected
    here but arbitrary objects such as PIL images cannot be deeply frozen.
    """

    source_sha256: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    audit: list[dict] = field(default_factory=list, compare=False)
    deadline_monotonic: float | None = None
    _clock: Callable[[], float] = field(default=time.monotonic, repr=False, compare=False)

    def check_deadline(self):
        if self.deadline_monotonic is not None and self._clock() >= self.deadline_monotonic:
            raise ToolTimeout()


def _json_bytes(value: Any) -> bytes:
    """Bound and normalize JSON without invoking custom object serializers."""
    count = 0

    def visit(item, depth):
        nonlocal count
        count += 1
        if count > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise _JsonCapacity('json_capacity')
        kind = type(item)
        if kind is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError('json_key')
                visit(key, depth+1)
                visit(child, depth+1)
        elif kind is list:
            for child in item:
                visit(child, depth+1)
        elif kind is str:
            if len(item) > MAX_JSON_BYTES:
                raise _JsonCapacity('json_capacity')
        elif kind is int:
            if item.bit_length() > 4096:
                raise ValueError('json_number_capacity')
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError('json_non_finite')
        elif kind not in (bool, type(None)):
            raise ValueError('non_json_value')

    visit(value, 0)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False,
                     sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(raw) > MAX_JSON_BYTES:
        raise _JsonCapacity('json_capacity')
    return raw


def _validator(schema):
    raw = _json_bytes(schema)
    clean = json.loads(raw)
    if type(clean) is not dict:
        raise ValueError('schema_must_be_object')

    def check_local(item):
        if isinstance(item, dict):
            for key, value in item.items():
                # Local JSON-pointer definitions are sufficient for all tools.
                # Never let schema validation retrieve a URI or a local file.
                if key in ('$id', '$dynamicRef', '$dynamicAnchor', '$anchor'):
                    raise ValueError('unsupported_schema_reference')
                if key == '$ref' and (not isinstance(value, str) or
                                      not (value == '#' or value.startswith('#/'))):
                    raise ValueError('external_schema_reference')
                if key == '$schema' and value not in (
                    'https://json-schema.org/draft/2020-12/schema',
                    'https://json-schema.org/draft/2020-12/schema#',
                ):
                    raise ValueError('unsupported_schema_draft')
                check_local(value)
        elif isinstance(item, list):
            for value in item:
                check_local(value)

    check_local(clean)
    Draft202012Validator.check_schema(clean)
    return clean, Draft202012Validator(clean)


def _context(value):
    if isinstance(value, ToolContext):
        result = value
    elif isinstance(value, Mapping):
        result = ToolContext(
            source_sha256=value.get('source_sha256'), data=value.get('data', {}),
            audit=value.get('audit', []), deadline_monotonic=value.get('deadline_monotonic'),
        )
    elif value is None:
        result = ToolContext()
    else:
        raise ValueError('invalid_tool_context')
    if not isinstance(result.data, Mapping) or type(result.audit) is not list:
        raise ValueError('invalid_tool_context')
    if result.source_sha256 is not None and (
        type(result.source_sha256) is not str or not _SHA256.fullmatch(result.source_sha256)
    ):
        raise ValueError('invalid_source_sha256')
    deadline = result.deadline_monotonic
    if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
        raise ValueError('invalid_tool_deadline')
    return replace(result, source_sha256=(result.source_sha256.lower()
                   if result.source_sha256 else None), data=MappingProxyType(dict(result.data)))


class ToolRegistry:
    """Register only application-owned functions; every call returns an envelope."""

    def __init__(self, *, clock=None):
        self._clock = clock or time.monotonic
        self._tools = {}

    def register(self, spec: ToolSpec | dict, handler: Callable):
        if isinstance(spec, dict):
            spec = ToolSpec(**spec)
        if not isinstance(spec, ToolSpec) or not callable(handler):
            raise ValueError('invalid_tool_registration')
        if not isinstance(spec.name, str) or not _NAME.fullmatch(spec.name):
            raise ValueError('invalid_tool_name')
        if spec.name in self._tools:
            raise ValueError('duplicate_tool_name')
        if (not isinstance(spec.version, str) or not 1 <= len(spec.version) <= 64 or
                not isinstance(spec.description, str) or not 1 <= len(spec.description) <= 2000):
            raise ValueError('invalid_tool_metadata')
        if isinstance(spec.allowed_roles, str):
            raise ValueError('invalid_tool_roles')
        roles = frozenset(spec.allowed_roles)
        if not roles or not roles <= ROLES:
            raise ValueError('invalid_tool_roles')
        if (type(spec.source_required) is not bool or
                type(spec.timeout_seconds) not in (int, float) or
                not math.isfinite(spec.timeout_seconds) or not 0 < spec.timeout_seconds <= 120):
            raise ValueError('invalid_tool_limits')
        try:
            input_schema, input_validator = _validator(spec.input_schema)
            output_schema, output_validator = _validator(spec.output_schema)
        except (SchemaError, TypeError, RecursionError) as exc:
            raise ValueError('invalid_tool_schema') from exc
        registered = replace(spec, allowed_roles=roles, input_schema=input_schema,
                             output_schema=output_schema)
        self._tools[registered.name] = (registered, handler, input_validator, output_validator)
        return self

    def describe(self, *, role: str | None = None):
        if role is not None and role not in ROLES:
            return []
        return [dict(name=spec.name, version=spec.version, description=spec.description,
                     input_schema=copy.deepcopy(spec.input_schema),
                     output_schema=copy.deepcopy(spec.output_schema),
                     allowed_roles=sorted(spec.allowed_roles), source_required=spec.source_required,
                     timeout_seconds=spec.timeout_seconds, timeout_mode='cooperative')
                for spec, _, _, _ in self._tools.values()
                if role is None or role in spec.allowed_roles]

    def call(self, name, arguments, *, role, context=None):
        started = self._clock()
        spec = None
        ctx = None
        input_digest = result_digest = None
        result = None
        error_code = None
        status = 'failed'
        handler_started = handler_finished = False
        entry = self._tools.get(name) if isinstance(name, str) else None
        if entry:
            spec, handler, input_validator, output_validator = entry
        try:
            ctx = _context(context)
            if entry is None:
                raise ToolFailure('unknown_tool')
            if not isinstance(role, str) or role not in ROLES or role not in spec.allowed_roles:
                status = 'denied'
                raise ToolFailure('role_not_allowed')
            if spec.source_required and ctx.source_sha256 is None:
                raise ToolFailure('source_required')
            if type(arguments) is not dict:
                raise ToolFailure('invalid_arguments')
            try:
                raw = _json_bytes(arguments)
                input_digest = hashlib.sha256(raw).hexdigest()
                clean_arguments = json.loads(raw)
                input_validator.validate(clean_arguments)
            except _JsonCapacity:
                raise ToolFailure('arguments_capacity_exceeded') from None
            except (ValidationError, ValueError, TypeError, RecursionError):
                raise ToolFailure('invalid_arguments') from None
            deadline = started+spec.timeout_seconds
            if ctx.deadline_monotonic is not None:
                deadline = min(deadline, ctx.deadline_monotonic)
            execution = replace(ctx, deadline_monotonic=deadline, _clock=self._clock)
            execution.check_deadline()
            handler_started = True
            proposed = handler(clean_arguments, context=execution)
            handler_finished = True
            execution.check_deadline()
            try:
                raw_result = _json_bytes(proposed)
                result_digest = hashlib.sha256(raw_result).hexdigest()
                clean_result = json.loads(raw_result)
                output_validator.validate(clean_result)
            except _JsonCapacity:
                raise ToolFailure('result_capacity_exceeded') from None
            except (ValidationError, ValueError, TypeError, RecursionError):
                raise ToolFailure('invalid_output') from None
            execution.check_deadline()
            result = clean_result
            status = 'success'
        except ToolTimeout:
            status, error_code = 'timeout', 'tool_timeout'
        except ToolFailure as exc:
            error_code = exc.code
        except (TypeError, ValueError) as exc:
            # Do not copy exception messages, provider credentials, images or
            # argument values into audit records or a model-visible error.
            error_code = 'invalid_context' if not handler_started else 'tool_failed'
        except Exception:
            error_code = 'tool_failed'
        event = {
            'call_id': uuid.uuid4().hex,
            'tool': spec.name if spec else 'unregistered',
            'tool_version': spec.version if spec else None,
            'role': role if isinstance(role, str) and role in ROLES else None,
            'source_sha256': ctx.source_sha256 if ctx else None,
            'input_digest': input_digest, 'result_digest': result_digest,
            'elapsed_seconds': round(max(0., self._clock()-started), 6),
            'status': status, 'error_code': error_code,
            'timeout_mode': 'cooperative',
            'handler_started': handler_started, 'handler_finished': handler_finished,
        }
        if ctx is not None:
            ctx.audit.append(copy.deepcopy(event))
        return {'ok': status == 'success', 'tool': event['tool'],
                'version': event['tool_version'], 'status': status,
                'result': result, 'error': {'code': error_code} if error_code else None,
                'audit': event}


__all__ = ['ROLES', 'ToolSpec', 'ToolContext', 'ToolRegistry', 'ToolFailure', 'ToolTimeout']
