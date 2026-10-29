"""Exercise the real sources available at Docker's model-cache build layer.

The complete repository can import successfully even when the earlier Docker
COPY layer is incomplete. Probe that isolated layer without site-packages,
models, a Docker daemon, or network downloads.
"""
from pathlib import Path
import json
import os
import re
import shlex
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def staged_cache_sources(tmp_path):
    stage = tmp_path / 'app'
    stage.mkdir()
    docker = re.sub(r'\\\r?\n', ' ', (ROOT / 'Dockerfile').read_text())
    found_cache_step = False
    for line in docker.splitlines():
        instruction = line.strip()
        if instruction.startswith('RUN ') and 'python scripts/prepare_ocr_model_cache.py' in instruction:
            found_cache_step = True
            break
        if not instruction.startswith('COPY '):
            continue
        fields = shlex.split(instruction)[1:]
        sources, destination = fields[:-1], fields[-1]
        for source in sources:
            original = ROOT / source
            assert original.is_file(), 'Unexpected non-file in the pre-cache COPY layer: ' + source
            target = stage / destination
            if destination.endswith('/') or destination == '.' or len(sources) > 1:
                target = target / original.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
    assert found_cache_step, 'Dockerfile no longer runs the expected model cache preparation'
    return stage


def probe_configuration(stage, cache_dir):
    code = '''
import json, runpy, sys
module = runpy.run_path(sys.argv[1], run_name='dmate_docker_cache_probe')
cache, selection = module['configure_build_cache'](sys.argv[2])
assert selection['status'] == 'ready'
assert cache.is_dir()
assert not any(name.split('.')[0] in ('paddle', 'paddlex', 'paddleocr') for name in sys.modules)
print(json.dumps({'status': selection['status']}))
'''
    return subprocess.run(
        [sys.executable, '-I', '-S', '-B', '-c', code,
         str(stage / 'scripts/prepare_ocr_model_cache.py'), str(cache_dir)],
        cwd=stage, env={'PATH': os.defpath}, capture_output=True, text=True,
        timeout=15,
    )


def test_production_cache_layer_has_all_runtime_imports(tmp_path):
    stage = staged_cache_sources(tmp_path)
    result = probe_configuration(stage, tmp_path / 'model-cache')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'status': 'ready'}


def test_missing_upload_limits_reproduces_the_pre_cache_build_failure(tmp_path):
    stage = staged_cache_sources(tmp_path)
    (stage / 'image_upload_limits.py').unlink(missing_ok=True)
    result = probe_configuration(stage, tmp_path / 'model-cache')
    assert result.returncode != 0
    assert "ModuleNotFoundError: No module named 'image_upload_limits'" in result.stderr
