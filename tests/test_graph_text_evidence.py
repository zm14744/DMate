"""Conflicting mathematical characters need image review, never polishing."""
import copy
import json
from unittest.mock import patch

import pytest

from graph_text_evidence import critical_sequence, reconcile_text, text_hints
from ocr_correction import apply_evidence_edits, correct_text


def hints(text='求 x² = 3。'):
    return text_hints({'text_evidence':{'image_size':[100,100],
                                      'body':[{'content':text,'box':[0,0,100,10],'score':.9}]}})


def test_original_coordinates_and_local_failure_are_explicit():
    value=text_hints({'text_evidence':{'image_size':[4000,2000],
        'body':[{'content':'3','box':[1000,400,2000,500]}]},
        'resource_metrics':[{'stage':'text','status':'memory_limit'}]})
    assert value['items'][0]['bbox']==[250,200,500,250]
    assert value['local_status']=='memory_limit'


def test_second_body_review_is_required_even_when_first_claims_empty():
    text,complete,audit=reconcile_text({'body_text':'','body_complete':True},{},text_hints({}),[])
    assert text=='' and not complete and 'second_text_review_missing' in audit['issues']


def test_digit_conflict_cannot_be_silently_chosen():
    first={'body_text':'求 x² = 2。','body_complete':True}
    second={'text_review':{'text':first['body_text'],'complete':True,
                          'regions':[{'id':'t1','role':'body','text':first['body_text']}]}}
    _,complete,audit=reconcile_text(first,second,hints(),[])
    assert not complete and 'unexplained_critical_text_conflict:t1' in audit['issues']
    second['text_review']['regions'][0]['reason']='原图个位数字明确是2'
    _,complete,audit=reconcile_text(first,second,hints(),[])
    assert complete and audit['conflicts']==[{'source':'t1','resolved':True}]


def test_second_visual_change_requires_reason_and_body_span():
    first={'body_text':'求 x² = 3。','body_complete':False}
    second={'text_review':{'text':'求 x² = 2。','complete':True,'regions':[]}}
    _,complete,audit=reconcile_text(first,second,text_hints({}),[])
    assert not complete and 'unexplained_visual_text_change' in audit['issues']
    second['text_review']['reason']='完整原图再次核对数字2'
    _,complete,_=reconcile_text(first,second,text_hints({}),[])
    assert complete


def test_every_local_region_needs_a_final_role():
    second={'text_review':{'text':'','complete':True,'regions':[]}}
    _,complete,audit=reconcile_text({'body_text':''},second,hints('a'),[{'id':'final'}])
    assert not complete and 'unreviewed_text_region:t1' in audit['issues']
    second['text_review']['regions']=[{'id':'t1','role':'graph_label','reason':'位于节点旁', 'graph_id':'old'}]
    _,complete,audit=reconcile_text({'body_text':''},second,hints('a'),[{'id':'final'}])
    assert not complete and 'text_label_without_final_panel:t1' in audit['issues']
    second['text_review']['regions'][0]['graph_id']='final'
    _,complete,_=reconcile_text({'body_text':''},second,hints('a'),[{'id':'final','bbox':[0,0,1,1]}])
    assert complete


def test_body_fragment_must_occur_in_final_transcription():
    second={'text_review':{'text':'求度数','complete':True,
                          'regions':[{'id':'t1','role':'body','text':'求顶点度数'}]}}
    _,complete,audit=reconcile_text({'body_text':'求度数'},second,hints('求顶点度数'),[])
    assert not complete and 'body_fragment_not_in_transcription:t1' in audit['issues']


@pytest.mark.parametrize('old,new',[('²','³'),('α','β'),('3.5','35'),('≤','<'),('x₁','x₂'),
    ('一','二'),('奇','偶'),('大于','小于'),('不小于','小于'),('至少','至多'),('且','或'),
    ('有向','无向'),('A̅','A'),('x⃗','x'),('ℝ','ℤ'),('𝒙','𝒚'),('３．５','３５')])
def test_polishing_cannot_change_unicode_math_or_decimal_separator(old,new):
    text='值'+old
    assert critical_sequence(old)!=critical_sequence(new)
    assert apply_evidence_edits(text,[{'start':1,'end':len(text),'original':old,'replacement':new}])==text


def test_partial_word_edit_cannot_change_mathematical_meaning():
    assert apply_evidence_edits('至少三个',[{'start':1,'end':2,'original':'少','replacement':'多'}])=='至少三个'


@pytest.mark.parametrize('old,new',[("G'",'G'),('a·b','ab'),('℃','℉'),('三分之二','三乘以二'),
    ('三点五','三五'),('p蕴含q','p等价q'),('最短路径','短路径')])
def test_unlisted_words_and_math_symbols_cannot_be_guessed_from_context(old,new):
    assert apply_evidence_edits(old,[{'start':0,'end':len(old),'original':old,'replacement':new}])==old
    second={'text_review':{'text':new,'complete':True,'regions':[]}}
    _,complete,audit=reconcile_text({'body_text':old},second,text_hints({}),[])
    assert not complete and 'unexplained_visual_text_change' in audit['issues']


def test_composed_edits_are_rechecked_as_a_whole():
    text='a  b'
    edits=[{'start':0,'end':2,'original':'a ','replacement':'a'},
           {'start':2,'end':4,'original':' b','replacement':'b'}]
    assert apply_evidence_edits(text,edits)==text


def test_independent_chinese_edits_cannot_create_a_new_relation():
    text='判断甲乙关系'
    edits=[{'start':2,'end':3,'original':'甲','replacement':'互'},
           {'start':3,'end':4,'original':'乙','replacement':'斥'}]
    assert apply_evidence_edits(text,edits)==text


def test_question_above_graph_cannot_disappear_as_a_graph_label():
    local=text_hints({'text_evidence':{'image_size':[1000,1000],
        'body':[{'content':'求顶点度数','box':[50,20,800,60]}]}})
    second={'text_review':{'text':'','complete':True,'regions':[
        {'id':'t1','role':'graph_label','graph_id':'G','reason':'属于图中标签'}]}}
    _,complete,audit=reconcile_text({'body_text':''},second,local,[{'id':'G','bbox':[.2,.4,.8,.9]}])
    assert not complete and 'text_label_without_spatial_support:t1' in audit['issues']


def test_unlocated_text_cannot_be_certified_as_graph_label():
    local=text_hints({'text':'a'})
    second={'text_review':{'text':'','complete':True,'regions':[
        {'id':'t1','role':'graph_label','graph_id':'G','reason':'图内字母'}]}}
    _,complete,audit=reconcile_text({'body_text':''},second,local,[{'id':'G','bbox':[0,0,1,1]}])
    assert not complete and 'text_label_without_spatial_support:t1' in audit['issues']


def test_deepseek_actual_content_field_is_used():
    response={'ok':True,'content':json.dumps({'edits':[{'start':2,'end':3,'original':'奌','replacement':'点'}]}),
              'choice':{'finish_reason':'stop'}}
    with patch('ai.DEEPSEEK_API_KEY','test-only'),patch('ai._request_text_completion',return_value=response) as api:
        text,audit=correct_text('求顶奌v1')
    assert text=='求顶点v1' and audit['status']=='ok' and audit['accepted_edits']==1
    assert api.call_args.kwargs['retries']==0


@pytest.mark.parametrize('content',['{}','not json','{"edits":null}'])
def test_invalid_deepseek_schema_is_not_success(content):
    with patch('ai.DEEPSEEK_API_KEY','test-only'),patch('ai._request_text_completion',return_value={'ok':True,'content':content}):
        text,audit=correct_text('求度数')
    assert text=='求度数' and audit['status']=='invalid_schema'


def test_valid_zero_edits_and_rejected_math_edits_are_distinct():
    with patch('ai.DEEPSEEK_API_KEY','test-only'),patch('ai._request_text_completion',return_value={'ok':True,'content':'{"edits":[]}'}):
        assert correct_text('x²')[1]['status']=='ok'
    content=json.dumps({'edits':[{'start':1,'end':2,'original':'²','replacement':'³'}]})
    with patch('ai.DEEPSEEK_API_KEY','test-only'),patch('ai._request_text_completion',return_value={'ok':True,'content':content}):
        text,audit=correct_text('x²')
    assert text=='x²' and audit['status']=='rejected_edits'
