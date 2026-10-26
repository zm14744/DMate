"""A software budget and an empty health log cannot certify a target container."""
import pytest

from scripts.benchmark_ocr_resources import measured_cgroup_limits, health_succeeded


@pytest.mark.parametrize('memory,cpu,valid',[
    (str(4*1024**3),'200000 100000',True),
    (str(8*1024**3),'200000 100000',False),
    ('max','200000 100000',False),
    (str(4*1024**3),'800000 100000',False),
    (str(4*1024**3),'max 100000',False),
    (str(4*1024**3),'200000 0',False),
])
def test_actual_cgroup_values_are_required_even_when_app_budget_is_four_gib(tmp_path,memory,cpu,valid):
    (tmp_path/'memory.max').write_text(memory)
    (tmp_path/'cpu.max').write_text(cpu)
    assert measured_cgroup_limits(tmp_path)['valid'] is valid


def test_missing_cgroup_information_cannot_certify(tmp_path):
    assert measured_cgroup_limits(tmp_path)['valid'] is False


def test_empty_or_exception_health_observation_is_a_failure():
    assert not health_succeeded([])
    assert not health_succeeded([{'ok':True},{'ok':False,'error_type':'RuntimeError'}])
    assert health_succeeded([{'ok':True},{'ok':True}])
