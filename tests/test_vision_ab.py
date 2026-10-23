"""Provider/protocol/scoring mechanisms. No real-image accuracy claims."""
import base64
import copy
import io
import json
from unittest.mock import patch

from PIL import Image
import pytest
from graph_ab_metrics import compare_graphs
from graph_staged import Budget,recognize_staged
from vision_provider import VisionProvider,VisionError,GLM_MODEL
from scripts.benchmark_graph_vision import execute,summarize,load_corpus,write_reports

URL='data:image/png;base64,'+base64.b64encode(b'original bytes for serializer test').decode()


def graph(edges=None,**extra):
    return {'id':'G1','name':'G1','directed':False,'weighted':False,'multigraph':True,
            'node_complete':True,'vertices':[{'id':'a','label':'a','x':.1,'y':.5},
                                           {'id':'b','label':'b','x':.9,'y':.5}],
            'edges':edges if edges is not None else [edge()],**extra}


def edge(**extra):
    return {'id':'e1','from':'a','to':'b','direction':'undirected','weight':None,
            'edge_label':None,'style':'solid','path':[[.1,.5],[.9,.5]],**extra}


def response(value,model=None):
    return 200,'',{'model':model,'choices':[{'message':{'content':json.dumps(value)},'finish_reason':'stop'}]}


@pytest.mark.parametrize('thinking',[False,True])
def test_provider_native_parameters_and_equivalent_image_bytes(thinking):
    qwen=VisionProvider('qwen',thinking=thinking).payload('same prompt',[URL])
    glm=VisionProvider('glm',thinking=thinking).payload('same prompt',[URL])
    assert qwen['enable_thinking'] is thinking and 'thinking' not in qwen
    assert glm['thinking']=={'type':'enabled' if thinking else 'disabled'}
    assert 'enable_thinking' not in glm and 'temperature' not in glm
    assert glm['do_sample'] is False and glm['model']==GLM_MODEL
    image=glm['messages'][0]['content'][1]['image_url']
    assert set(image)=={'url'} and base64.b64decode(image['url'])==base64.b64decode(URL.split(',')[1])
    assert qwen['messages'][0]['content'][1]['image_url']['url']==URL
    assert qwen['messages'][0]['content'][0]==glm['messages'][0]['content'][0]
    assert ('response_format' in qwen) is (not thinking)
    assert ('response_format' in glm) is (not thinking)


def test_rate_limit_retry_is_bounded_counted_and_does_not_log_keys(monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','secret-test-value')
    calls=[];delays=[]
    def request(*args,**kwargs):
        calls.append(1)
        return (429,'secret-test-value',{'error_code':'1302'}) if len(calls)==1 else response({'graphs':[]},GLM_MODEL)
    provider=VisionProvider('glm',retries=1,capture=True,transport=request,sleep=delays.append)
    budget=Budget();assert provider('JSON only',[URL],budget)=={'graphs':[]}
    assert len(calls)==2 and budget.remaining==5 and delays==[1.]
    assert provider.observations[0]['http_status']==429
    assert provider.observations[0]['error_code']=='1302'
    assert provider.observations[1]['returned_model']==GLM_MODEL
    assert 'secret-test-value' not in json.dumps(provider.observations)


def test_retry_cannot_exceed_shared_stage_request_budget(monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','test-key');calls=[]
    def request(*args,**kwargs):calls.append(1);return 429,'',None
    provider=VisionProvider('glm',retries=2,transport=request,sleep=lambda _:None)
    budget=Budget(calls=1)
    with pytest.raises(TimeoutError):provider('JSON only',[URL],budget)
    assert len(calls)==1 and len(budget.metrics)==1


def test_missing_glm_key_never_attempts_a_request(monkeypatch):
    monkeypatch.delenv('ZHIPU_API_KEY',raising=False)
    provider=VisionProvider('glm',transport=lambda *a,**k:pytest.fail('Unexpected request'))
    budget=Budget()
    with pytest.raises(VisionError,match='missing_key'):provider('JSON',[URL],budget)
    assert budget.remaining==7 and not budget.metrics


def test_configuring_glm_cannot_change_production_default(monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','configured-glm')
    from graph_staged import _call
    with patch('ai.API_KEY','qwen-test'),patch('ai.VISION_ENABLED',True),patch(
            'ai._request_qwen_completion',return_value=response({'graphs':[]})) as request:
        _call('JSON only',[URL],Budget())
    assert request.call_args.args[0]['model']=='qwen3-vl-plus'


@pytest.mark.parametrize('name',['glm','qwen'])
def test_both_providers_execute_the_same_node_edge_trace_review_pipeline(name,monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','glm-test')
    original=io.BytesIO();Image.new('RGB',(160,100),'white').save(original,format='PNG')
    seen=[]
    def request(payload,*args,**kwargs):
        prompt=payload['messages'][0]['content'][0]['text'];seen.append(prompt)
        assert payload['model']==('glm-4.6v-flash' if name=='glm' else 'qwen3-vl-plus')
        if 'NODE 阶段' in prompt:return response({'graphs':[graph([])]})
        jobs=json.loads(prompt[prompt.index('{"requests":'):])['requests']
        if 'EDGE 阶段' in prompt:
            return response({'reads':[{'graph_id':'G1','vertex':v,'complete':True,'edges':[edge()]}
                                      for j in jobs for v in j['focus_vertices']]})
        return response({'graphs':[{'graph_id':'G1','inventory_complete':True,
                                    'decisions':[{'id':c['id'],'visible':True,'direction':'undirected'}
                                                 for j in jobs for c in j['candidates']]}]})
    provider=VisionProvider(name,transport=request,capture=True)
    supplied_budget=Budget(seconds=300,call_seconds=90)
    with patch('ai.API_KEY','qwen-test'),patch('ai.VISION_ENABLED',True),patch(
            'graph_line_tracer.attach_line_evidence',side_effect=lambda raw,result:result) as trace:
        result=recognize_staged(original.getvalue(),provider=provider,budget=supplied_budget)
    assert len(seen)==3 and trace.call_count==1 and len(result['graphs'][0]['edges'])==1
    assert result['calls_remaining']==4 and supplied_budget.remaining==4 and len(provider.observations)==3
    assert any(d.startswith('vision_adapter:glm-') for d in result['diagnostics']) is (name=='glm')
    from graph_staged import EDGE_PROMPT
    assert seen[1].startswith(EDGE_PROMPT) is (name=='qwen')


def test_parallel_instances_are_not_deduplicated_in_precision_recall():
    want=graph([edge(id=f'e{i}') for i in range(3)])
    got=graph([edge(id=f'r{i}') for i in range(2)])
    score=compare_graphs([want],[got])
    assert score['edge_tp']==2 and score['missing_edges']==1 and score['extra_edges']==0
    assert score['edge_set']=={'precision':1.,'recall':2/3,'f1':.8}
    assert score['parallel_count_accuracy']==0 and not score['whole_structure_correct']


@pytest.mark.parametrize('calls',[3,4])
def test_native_missing_review_decisions_use_only_available_second_pass(calls,monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','glm-unit-test')
    original=io.BytesIO();Image.new('RGB',(160,100),'white').save(original,format='PNG')
    review_calls=[]
    def request(payload,*args,**kwargs):
        prompt=payload['messages'][0]['content'][0]['text']
        if 'NODE 阶段' in prompt:return response({'graphs':[graph([])]})
        if 'EDGE 阶段' in prompt:
            return response({'edges':[edge(id='r1',graph_id='G1')],
                'reads':[{'graph_id':'G1','vertex':v,'complete':True,'edge_ids':['r1']} for v in ('a','b')]})
        review_calls.append(prompt)
        if len(review_calls)==1:return response({'decisions':[],'completed_graph_ids':[]})
        assert '上轮遗漏候选' in prompt
        return response({'decisions':[{'graph_id':'G1','id':'e1','visible':False,
                                      'direction':'undirected','style':'unknown','path':[]}]})
    provider=VisionProvider('glm',model='glm-4.6v',transport=request,capture=True)
    with patch('graph_line_tracer.attach_line_evidence',side_effect=lambda raw,result:result):
        result=recognize_staged(original.getvalue(),provider=provider,
                                budget=Budget(seconds=300,calls=calls,call_seconds=90))
    assert len(provider.observations)==calls and result['calls_remaining']==0
    assert 'glm_review_missing_candidates:1' in result['diagnostics']
    assert len(result['graphs'][0]['edges'])==(1 if calls==3 else 0)


def test_wrong_direction_and_weight_have_separate_instance_metrics():
    want=graph([edge(direction='forward',weight=6),edge(id='e2',direction='forward',weight=8)],directed=True,weighted=True)
    got=graph([edge(direction='forward',weight=9),edge(id='e2',direction='forward',**{'from':'b','to':'a'},weight=8)],directed=True,weighted=True)
    score=compare_graphs([want],[got])
    assert score['edge_tp']==1 and score['direction_accuracy']==.5 and score['direction_recall']==.5
    assert score['weight_match_accuracy']==0 and score['parallel_count_accuracy']==1
    assert not score['whole_structure_correct']


def test_matching_labels_do_not_hide_a_missing_isolated_vertex():
    want=graph();want['vertices'].append({'id':'c','label':'c'})
    score=compare_graphs([want],[graph()])
    assert score['missing_vertices']==1 and not score['whole_structure_correct']


def test_unlabelled_vertices_match_original_positions_not_isomorphism():
    want=graph()
    for vertex in want['vertices']:vertex['label']=None
    got=copy.deepcopy(want);got['vertices'][1]['x']=.5
    score=compare_graphs([want],[got])
    assert score['vertex_tp']==1 and score['edge_tp']==0
    assert compare_graphs([want],[got],reference_status='partial')['status']=='unverified_reference'


def test_operational_failure_is_not_a_zero_accuracy_graph(monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','test')
    raw=io.BytesIO();Image.new('RGB',(20,20)).save(raw,format='PNG')
    with patch('vision_provider._glm_request',return_value=(429,'',{'error_code':'1302'})),patch('vision_provider.time.sleep'):
        record=execute(raw.getvalue(),'glm','raw',False,retries=0)
    assert record['status']=='http_error' and record['actual_request_count']==1
    assert 'metrics' not in record and record['http_429_count']==1


def test_paired_reporting_never_compares_different_success_subsets(tmp_path):
    good=compare_graphs([graph()],[graph()])
    rows=[{'case_id':'one','sha256':'x','experiment':'raw','thinking':False,'repeat':1,'provider':p,
           'model':p,'status':'success','actual_request_count':1,'metrics':good} for p in ('glm','qwen')]
    rows.append({**rows[0],'case_id':'two','status':'http_error','metrics':{}})
    rows.append({**rows[1],'case_id':'two'})
    summary,paired=summarize(rows)
    assert paired[0]['paired_completed_count']==1
    assert all(s['count']==1 for s in paired[0]['scores'].values())
    write_reports(tmp_path,rows,{})
    assert (tmp_path/'details.csv').exists() and len(json.loads((tmp_path/'comparison.json').read_text())['records'])==4


def test_corpus_rejects_result_screenshots_and_deduplicates_original_bytes(tmp_path):
    import hashlib
    raw=b'original';(tmp_path/'original.png').write_bytes(raw)
    row={'id':'one','image':'original.png','sha256':hashlib.sha256(raw).hexdigest(),'source_kind':'conversation_original'}
    path=tmp_path/'manifest.json';path.write_text(json.dumps({'cases':[row,{**row,'id':'two'}]}))
    _,cases,duplicates=load_corpus(path)
    assert len(cases)==1 and duplicates==[{'id':'two','duplicate_of':'one'}]
    row['source_kind']='ocr_result_screenshot';path.write_text(json.dumps({'cases':[row]}))
    with pytest.raises(ValueError,match='question originals'):load_corpus(path)


def test_actual_usage_reporting_never_estimates_failed_request_tokens():
    from scripts.benchmark_graph_vision import operational_totals
    rows=[{'status':'success','seconds':10,'requests':[
        {'status':'http_error','http_status':429,'seconds':1},
        {'status':200,'http_status':200,'seconds':9,'usage':{'prompt_tokens':100,'completion_tokens':30,'total_tokens':130}}]}]
    result=operational_totals(rows)
    assert result['total_tokens']==130 and result['usage_reported_requests']==1
    assert result['attempted_requests']==2 and result['request_success_rate']==.5
    assert result['http_success_rate']==.5
    assert result['mean_request_seconds']==5
    invalid=operational_totals([{'requests':[{'status':'invalid_output','http_status':200}]}])
    assert invalid['http_success_rate']==1 and invalid['request_success_rate']==0
    assert operational_totals([{'requests':[{'status':'transport_failed'}]}])['total_tokens'] is None


def test_paid_glm_is_explicit_and_flash_cannot_masquerade_as_paid(monkeypatch):
    from vision_provider import GLM_PAID_MODEL
    assert VisionProvider('glm').model=='glm-4.6v-flash'
    assert VisionProvider('glm',model=GLM_PAID_MODEL).payload('JSON',[URL])['model']=='glm-4.6v'
    monkeypatch.setenv('ZHIPU_API_KEY','test')
    provider=VisionProvider('glm',model=GLM_PAID_MODEL,transport=lambda *a,**k:response({'graphs':[]},GLM_MODEL))
    with pytest.raises(VisionError,match='model_mismatch'):provider('JSON',[URL],Budget())
    with pytest.raises(ValueError):VisionProvider('qwen',model=GLM_PAID_MODEL)


@pytest.mark.parametrize('raw,valid',[
    ('\n{"graphs":[]}\n``',True),
    ('```json\n{"graphs":[]}\n```',True),
    ('{"graphs":[{"edges":[]} ]\n``',False),
    ('Explanation {"graphs":[]}\n``',False),
])
def test_only_outer_formatting_is_normalized_never_inner_json(raw,valid,monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','test')
    provider=VisionProvider('glm',transport=lambda *a,**k:(200,'',{
        'choices':[{'message':{'content':raw},'finish_reason':'stop'}]}))
    if valid:assert provider('JSON',[URL],Budget())=={'graphs':[]}
    else:
        with pytest.raises(VisionError,match='invalid_output'):provider('JSON',[URL],Budget())


def test_long_benchmark_budget_does_not_change_production_defaults():
    assert Budget().take()==45
    longer=Budget(seconds=300,calls=1,call_seconds=90)
    assert longer.take()==90
    with pytest.raises(TimeoutError):longer.take()
