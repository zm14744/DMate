"""A real text response must distinguish unsafe edits from unavailable service."""
import json
from unittest.mock import patch

from ocr_correction import correct_text


def test_rejected_math_edit_is_identified_without_changing_the_question():
    content=json.dumps({'edits':[{'start':1,'end':2,'original':'₅','replacement':'₃'}]})
    with patch('ai.DEEPSEEK_API_KEY','offline'), patch('ai._request_text_completion',return_value={
            'ok':True,'content':content,'choice':{'finish_reason':'stop'}}) as call:
        text,audit=correct_text('v₅到自身')
    assert text=='v₅到自身' and audit['status']=='rejected_edits'
    assert audit['provider']=='deepseek' and audit['response_received'] is True
    assert audit['edit_decisions']==[{'index':0,'accepted':False,'start':1,'end':2,
        'original':'₅','replacement':'₃','reason':'change_not_proven_equivalent'}]
    assert len(audit['content_sha256'])==64 and 'content' not in audit
    assert call.call_count==1 and call.call_args.kwargs['retries']==0


def test_malformed_provider_content_is_never_copied_into_the_audit():
    raw='unexpected provider diagnostic '*1000
    with patch('ai.DEEPSEEK_API_KEY','offline'), patch('ai._request_text_completion',return_value={
            'ok':True,'content':raw}):
        text,audit=correct_text('求度数')
    assert text=='求度数' and audit['status']=='invalid_schema'
    assert raw not in json.dumps(audit) and audit['response_received'] is True


def test_unavailable_transport_is_separate_from_rejected_edit():
    with patch('ai.DEEPSEEK_API_KEY','offline'), patch('ai._request_text_completion',return_value={
            'ok':False,'error':'private upstream message'}):
        text,audit=correct_text('求度数')
    assert text=='求度数' and audit['status']=='failed'
    assert audit['response_received'] is False and 'edit_decisions' not in audit
    assert 'private upstream message' not in json.dumps(audit)
