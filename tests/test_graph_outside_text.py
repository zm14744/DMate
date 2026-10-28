"""Exercise the actual cached text callback used by the image editor."""
import subprocess
from pathlib import Path


def test_cached_text_updates_locally_and_excludes_every_intersecting_frame():
    source=Path(__file__).resolve().parents[1]/'static/script.js'
    code=r'''
const assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync(process.argv[1],'utf8');
const start=source.indexOf('onRecognizeOutside: async exclusions => {');
const end=source.indexOf('onRecognizeText: async polygon => {',start);
let task={result:{text_regions:{image_size:[100,100],body:[
 {box:[0,0,20,10],content:'题干'},
 {box:[40,40,60,60],content:'图内标签'},
 {box:[15,40,45,50],content:'跨边界文字'},
 {box:[80,80,99,99],content:'第二问'}
]}}};
global.fetch=()=>{throw new Error('Cached updates must not call the server');};
const fn=eval('('+source.slice(start,end).replace('onRecognizeOutside: ','').trim().replace(/,$/,'')+')');
(async()=>{
 const frame=[[.3,.3],[.7,.3],[.7,.7],[.3,.7]];
 assert.equal(await fn([frame]),'题干\n第二问');
 assert.equal(await fn([]),'题干\n图内标签\n跨边界文字\n第二问');
 const second=[[.75,.75],[1,.75],[1,1],[.75,1]];
 assert.equal(await fn([frame,second]),'题干');
 const evidence=task.result.text_regions;let requests=0;
 task={id:'task',sourceSha256:'a'.repeat(64),file:new Blob(['image']),result:{}};
 global.parseResponseJson=async response=>response.json();
 global.fetch=async(url,options)=>{
   requests++;assert.equal(options.body.get('exclusions'),'[]');
   await new Promise(r=>setTimeout(r,5));
   return {ok:true,json:async()=>({request_id:'task',source_sha256:'a'.repeat(64),text_regions:evidence})};
 };
 const results=await Promise.all([fn([frame]),fn([frame,second])]);
 assert.deepEqual(results,['题干\n第二问','题干']);
 assert.equal(requests,1);
 assert.equal(await fn([frame]),'题干\n第二问');assert.equal(requests,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result=subprocess.run(['node','-e',code,str(source)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
