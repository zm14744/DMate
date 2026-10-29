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


def test_sample_values_match_uniform_grid_reference_at_all_supported_capture_rates():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    program = r'''
const assert=require('node:assert/strict');
const {pcmSampler}=require('./static/voice-input.js');
const quantize=value=>Math.round(Math.max(-1,Math.min(1,value))*(value<0?32768:32767));
for(const rate of [8000,11025,16000,22050,32000,44100,48000,96000,192000]){
  for(const length of [1,2,17,1025,65537]){
    const signal=Float32Array.from({length},(_,i)=>1.2*Math.sin(i/17));
    signal[0]=-.83;signal[length-1]=.91;
    const expected=[];
    for(let n=0;n*rate/16000<signal.length;n++){
      const at=n*(rate/16000),left=Math.floor(at),fraction=at-left;
      expected.push(quantize(signal[left]*(1-fraction)+signal[Math.min(left+1,length-1)]*fraction));
    }
    const sampler=pcmSampler(rate),actual=[];
    let index=0,block=1;
    while(index<length){
      const end=Math.min(length,index+block);
      actual.push(...sampler(signal.subarray(index,end)));
      index=end;block=(block*13)%1024+1;
    }
    actual.push(...sampler.flush());
    assert.deepEqual(actual,expected,`PCM changed at ${rate}Hz/${length} samples`);
  }
}
'''
    subprocess.run([node, '-e', program], cwd=ROOT, capture_output=True, text=True, check=True)


def test_bulk_wav_encoding_is_byte_exact_with_padding_partial_views_and_endian_fallback():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    program = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {wavBlob}=require('./static/voice-input.js');
function reference(chunks,count){
  const buffer=new ArrayBuffer(44+count*2),view=new DataView(buffer);
  const word=(offset,text)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));};
  word(0,'RIFF');view.setUint32(4,36+count*2,true);word(8,'WAVE');word(12,'fmt ');
  view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);
  view.setUint32(24,16000,true);view.setUint32(28,32000,true);
  view.setUint16(32,2,true);view.setUint16(34,16,true);word(36,'data');view.setUint32(40,count*2,true);
  let offset=44;
  for(const chunk of chunks)for(const sample of chunk){view.setInt16(offset,sample,true);offset+=2;}
  return new Uint8Array(buffer);
}
(async()=>{
  const backing=Int16Array.from({length:960000},(_,i)=>((i*71)%65536)-32768);
  // Offset views catch accidental copying of data before/after each chunk.
  const chunks=[new Int16Array(2400),backing.subarray(11,4095),new Int16Array(0),
    backing.subarray(4095,backing.length-19),new Int16Array(4000)];
  const count=chunks.reduce((n,c)=>n+c.length,0),expected=reference(chunks,count);
  const blob=wavBlob(chunks,count);
  assert.equal(blob.type,'audio/wav');
  assert.deepEqual(new Uint8Array(await blob.arrayBuffer()),expected);
  const sandbox={Blob,module:{exports:{}}};
  const source=fs.readFileSync('./static/voice-input.js','utf8')
    .replace(/const LITTLE_ENDIAN =[^;]+;/,'const LITTLE_ENDIAN = false;');
  vm.runInNewContext(source,sandbox);
  const other=sandbox.module.exports.wavBlob(chunks,count);
  assert.deepEqual(new Uint8Array(await other.arrayBuffer()),expected);
  const pcm=new Int16Array(await blob.arrayBuffer(),44);
  assert(pcm.subarray(0,2400).every(value=>value===0));
  assert(pcm.subarray(pcm.length-4000).every(value=>value===0));
  assert.equal(pcm[2400],backing[11]);
  assert.equal(pcm[pcm.length-4001],backing[backing.length-20]);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    subprocess.run([node, '-e', program], cwd=ROOT, capture_output=True, text=True, check=True)
