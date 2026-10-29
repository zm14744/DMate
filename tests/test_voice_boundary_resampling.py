"""Finite audio chunks retain first/last available speech samples and phase."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_resampling_flush_preserves_finite_boundaries_and_chunk_phase():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    program = r'''
const assert=require('node:assert/strict');
const {pcmSampler}=require('./static/voice-input.js');
for(const rate of [8000,16000,32000,44100,48000]){
  const signal=new Float32Array(1001);
  for(let i=0;i<signal.length;i++)signal[i]=.12*Math.sin(i/13);
  signal.fill(.75,0,12);signal.fill(.85,signal.length-12);
  const whole=pcmSampler(rate),expected=[...whole(signal),...whole.flush()];
  assert.equal(expected.length,Math.ceil(signal.length*16000/rate));
  assert.equal(expected[0],Math.round(.75*32767));
  assert(expected.at(-1)>=27851);
  assert.equal(whole.flush().length,0);
  assert.equal(whole(signal).length,0);
  const blocks=pcmSampler(rate),actual=[];
  let offset=0;
  for(const size of [1,7,29,113,512,1024]){
    const chunk=signal.subarray(offset,Math.min(offset+size,signal.length));
    actual.push(...blocks(chunk));offset+=chunk.length;
    if(offset===signal.length)break;
  }
  if(offset<signal.length)actual.push(...blocks(signal.subarray(offset)));
  actual.push(...blocks.flush());
  assert.deepEqual(actual,expected);
}
const one=pcmSampler(16000);
assert.equal(one(Float32Array.of(-.75)).length,0);
assert.deepEqual([...one.flush()],[-24576]);
'''
    subprocess.run([node, '-e', program], cwd=ROOT, capture_output=True, text=True, check=True)
