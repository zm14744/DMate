import copy
import hashlib
import json

import pytest

from dmate_tool_registry import MAX_JSON_BYTES, MAX_JSON_NODES, ToolContext, ToolRegistry, ToolSpec


SHA = 'a'*64
SCHEMA = {'type': 'object', 'properties': {'value': {'type': 'integer'}},
          'required': ['value'], 'additionalProperties': False}


def spec(**updates):
    data = dict(name='test.identity', version='1', description='Contract test tool.',
                input_schema=copy.deepcopy(SCHEMA), output_schema=copy.deepcopy(SCHEMA),
                allowed_roles=('solver',), source_required=True, timeout_seconds=1.)
    data.update(updates)
    return ToolSpec(**data)


def identity(arguments, *, context):
    context.check_deadline()
    return arguments


def context(**updates):
    data = dict(source_sha256=SHA, data={}, audit=[])
    data.update(updates)
    return ToolContext(**data)


def test_audit_contains_source_role_version_and_canonical_digests_only():
    registry = ToolRegistry().register(spec(), identity)
    ctx = context(data={'raw_image': b'private bytes', 'credentials': 'private-secret'})
    result = registry.call('test.identity', {'value': 3}, role='solver', context=ctx)
    assert result['ok'] and result['result'] == {'value': 3}
    digest = hashlib.sha256(b'{"value":3}').hexdigest()
    event = result['audit']
    assert event['source_sha256'] == SHA
    assert event['role'] == 'solver' and event['tool_version'] == '1'
    assert event['input_digest'] == event['result_digest'] == digest
    assert event['elapsed_seconds'] >= 0 and event['status'] == 'success'
    assert ctx.audit == [event]
    assert 'private' not in json.dumps(result)
    event['status'] = 'caller_mutation'
    assert ctx.audit[0]['status'] == 'success'


@pytest.mark.parametrize('name,role,expected', [
    ('not.registered', 'solver', 'unknown_tool'),
    ('test.identity', 'body_text', 'role_not_allowed'),
    ('test.identity', 'invented_role', 'role_not_allowed'),
    ('test.identity', ['solver'], 'role_not_allowed'),
])
def test_only_registered_tools_and_allowed_roles_execute(name, role, expected):
    calls = []
    registry = ToolRegistry().register(spec(), lambda a, **kw: calls.append(a))
    result = registry.call(name, {'value': 1}, role=role, context=context())
    assert not result['ok'] and result['error']['code'] == expected
    assert not calls


@pytest.mark.parametrize('value', [None, '', 'not-a-sha', 'a'*63])
def test_missing_or_invalid_source_never_runs(value):
    calls = []
    registry = ToolRegistry().register(spec(), lambda a, **kw: calls.append(a))
    result = registry.call('test.identity', {'value': 1}, role='solver', context=context(source_sha256=value))
    assert not result['ok'] and not calls


@pytest.mark.parametrize('arguments', [
    {'value': True}, {'value': '1'}, {'value': 1, 'extra': 'not accepted'},
    {'value': float('nan')}, {'value': object()}, {'value': 1 << 4097}, [],
])
def test_invalid_json_and_schema_inputs_fail_without_running(arguments):
    calls = []
    registry = ToolRegistry().register(spec(), lambda a, **kw: calls.append(a))
    result = registry.call('test.identity', arguments, role='solver', context=context())
    assert result['error']['code'] == 'invalid_arguments'
    assert not calls


def test_output_validation_and_handler_error_do_not_erase_successes_or_leak_errors():
    registry = ToolRegistry().register(spec(), identity)
    registry.register(spec(name='test.bad_output'), lambda a, **kw: {'value': 'private-secret'})

    def fail(a, *, context):
        raise RuntimeError('Bearer private-secret data:image/png;base64,PRIVATE')

    registry.register(spec(name='test.fail'), fail)
    ctx = context()
    first = registry.call('test.identity', {'value': 9}, role='solver', context=ctx)
    second = registry.call('test.bad_output', {'value': 9}, role='solver', context=ctx)
    third = registry.call('test.fail', {'value': 9}, role='solver', context=ctx)
    assert first['result'] == {'value': 9}
    assert second['error']['code'] == 'invalid_output' and second['result'] is None
    assert second['audit']['result_digest'] is not None
    assert third['error']['code'] == 'tool_failed' and third['result'] is None
    assert len(ctx.audit) == 3 and ctx.audit[0]['status'] == 'success'
    assert 'private-secret' not in json.dumps([second, third, ctx.audit])
    assert 'base64' not in json.dumps([second, third, ctx.audit])


def test_arguments_and_registered_schemas_cannot_be_modified_from_outside():
    original_spec = spec()
    registry = ToolRegistry().register(original_spec, identity)
    original_spec.input_schema['properties']['value']['type'] = 'string'
    description = registry.describe(role='solver')
    description[0]['input_schema']['properties']['value']['type'] = 'string'
    arguments = {'value': 4}
    result = registry.call('test.identity', arguments, role='solver', context=context())
    assert result['ok'] and arguments == {'value': 4}
    result['result']['value'] = 10
    assert arguments['value'] == 4
    with pytest.raises(ValueError, match='duplicate_tool_name'):
        registry.register(spec(), identity)


@pytest.mark.parametrize('reference', ['https://example.invalid/schema', 'file:///private/key', '../secret.json'])
def test_external_schema_references_are_rejected_at_registration(reference):
    with pytest.raises(ValueError, match='external_schema_reference'):
        ToolRegistry().register(spec(input_schema={'$ref': reference}), identity)


def test_local_json_pointer_schema_and_mapping_context_work():
    schema = {'type': 'object', 'properties': {'value': {'$ref': '#/$defs/count'}},
              'required': ['value'], 'additionalProperties': False,
              '$defs': {'count': {'type': 'integer', 'minimum': 0}}}
    registry = ToolRegistry().register(spec(input_schema=schema), identity)
    audit = []
    result = registry.call('test.identity', {'value': 3}, role='solver',
                           context={'source_sha256': SHA.upper(), 'data': {}, 'audit': audit})
    assert result['ok'] and audit[0]['source_sha256'] == SHA


def test_cooperative_deadline_stops_at_explicit_check_without_background_thread():
    clock = [10.]
    registry = ToolRegistry(clock=lambda: clock[0])
    progress = []

    def work(arguments, *, context):
        progress.append('started')
        clock[0] += 2
        context.check_deadline()
        progress.append('must_not_happen')
        return arguments

    registry.register(spec(), work)
    result = registry.call('test.identity', {'value': 1}, role='solver', context=context())
    assert result['status'] == 'timeout' and result['result'] is None
    assert progress == ['started']
    assert result['audit']['timeout_mode'] == 'cooperative'
    assert result['audit']['handler_started'] and not result['audit']['handler_finished']


def test_overdue_uncooperative_handler_is_reported_after_completion_not_fake_killed():
    clock = [10.]

    def work(arguments, *, context):
        clock[0] += 2
        return arguments

    registry = ToolRegistry(clock=lambda: clock[0]).register(spec(), work)
    result = registry.call('test.identity', {'value': 1}, role='solver', context=context())
    assert result['status'] == 'timeout'
    assert result['audit']['handler_finished'] is True
    assert result['audit']['elapsed_seconds'] == 2
    assert result['result'] is None


def test_job_deadline_can_be_stricter_than_tool_deadline_and_prevents_execution():
    calls = []
    registry = ToolRegistry(clock=lambda: 10.).register(spec(), lambda a, **kw: calls.append(a))
    result = registry.call('test.identity', {'value': 1}, role='solver',
                           context=context(deadline_monotonic=9.))
    assert result['status'] == 'timeout' and not calls
    assert not result['audit']['handler_started']


def test_large_bounded_image_tool_metadata_is_not_limited_to_half_a_megabyte():
    schema = {'type': 'object', 'properties': {'value': {'type': 'string'}},
              'required': ['value'], 'additionalProperties': False}
    registry = ToolRegistry().register(spec(input_schema=schema, output_schema=schema), identity)
    result = registry.call('test.identity', {'value': 'x'*600_000}, role='solver', context=context())
    assert result['ok'] and len(result['result']['value']) == 600_000


def test_capacity_failures_are_explicit_and_do_not_run_or_return_partial_output():
    calls = []
    registry = ToolRegistry().register(spec(), lambda a, **kw: calls.append(a))
    result = registry.call('test.identity', {'value': 'x'*(MAX_JSON_BYTES+1)}, role='solver', context=context())
    assert result['error']['code'] == 'arguments_capacity_exceeded' and not calls
    registry.register(spec(name='test.large_result', output_schema={'type': 'array'}),
                      lambda a, **kw: [0]*MAX_JSON_NODES)
    result = registry.call('test.large_result', {'value': 1}, role='solver', context=context())
    assert result['error']['code'] == 'result_capacity_exceeded'
    assert result['result'] is None and result['audit']['status'] == 'failed'
