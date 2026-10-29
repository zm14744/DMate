"""Compose up to four individually confirmed images without merging identities.

The aggregate is application-held request data, never a new signed image
confirmation. Every original token is checked again before releasing a reply.
"""
from __future__ import annotations

import copy
import hashlib
import json

from graph_confirmation import (ConfirmationError, MAX_BYTES, document_digest,
                                resolve_confirmed_context)

MAX_IMAGES = 4
MAX_TEXT_CHARS = 24000


def batch_question_text(contexts, field='question_text'):
    """Public client/server anchor rule, retaining the caller's image order."""
    return '\n\n'.join('【图片 ' + str(index) + '】\n' + context[field]
                         for index, context in enumerate(contexts, 1))


def resolve_confirmed_batch(owner, payload):
    if not isinstance(payload, list) or not 1 <= len(payload) <= MAX_IMAGES:
        raise ConfirmationError('invalid_confirmation_batch', '请一次发送1至4张已保存的图片。')
    contexts, identities = [], set()
    for item in payload:
        context = resolve_confirmed_context(owner, item)
        if context is None:
            raise ConfirmationError('confirmation_required', '请先逐张保存图片的题目结构。', status=409)
        identity = context['request_id']
        if identity in identities:
            raise ConfirmationError('duplicate_confirmation_image', '同一张图片不能在本次发送中重复出现。')
        identities.add(identity)
        contexts.append(context)

    document = {'body_text': '', 'graphs': []}
    sources, bodies, legends, captions = [], [], [], []
    for index, context in enumerate(contexts, 1):
        source_document = context['document']
        bodies.append('【图片 ' + str(index) + '】\n' + source_document['body_text'])
        id_map = {g['id']: 'image' + str(index) + '_graph' + str(number)
                  for number, g in enumerate(source_document['graphs'], 1)}
        for source_number, source_graph in enumerate(source_document['graphs'], 1):
            graph = copy.deepcopy(source_graph)
            graph['id'] = id_map[source_graph['id']]
            graph['name'] = '图片' + str(index) + ' · ' + str(source_graph.get('name') or source_graph['id'])
            # These are server-created source scopes, not client-selected math.
            graph.update(source_image_number=index, source_graph_number=source_number,
                         source_graph_id=source_graph['id'],
                         source_graph_name=source_graph.get('name') or source_graph['id'])
            document['graphs'].append(graph)
        for key, destination in (('legends', legends), ('captions', captions)):
            for row in source_document.get('text_context', {}).get(key, []):
                text = '图片' + str(index) + '：' + row['text']
                if len(text) > 2000:
                    raise ConfirmationError('confirmation_batch_too_large', '这些图片的图例内容过长，请分批发送。')
                destination.append({'text': text, 'graph_ids': [id_map[gid] for gid in row['graph_ids']]})
        sources.append({'image_number': index, 'request_id': context['request_id'],
                        'source_sha256': context['source_sha256'],
                        'document_sha256': context['document_sha256'],
                        'revision': context['revision'], 'graph_ids': id_map})
    document['body_text'] = '\n\n'.join(bodies)
    if legends or captions:
        document['text_context'] = {'legends': legends, 'captions': captions}
    question, rendered = (batch_question_text(contexts, field)
                          for field in ('question_text', 'rendered_question_text'))
    if (len(document['graphs']) > 64 or any(len(text) > MAX_TEXT_CHARS
            for text in (document['body_text'], question, rendered))
            or len(legends) > 32 or len(captions) > 32):
        raise ConfirmationError('confirmation_batch_too_large', '这些图片的题目内容过长，请分批发送。')
    serialized_sources = json.dumps(sources, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False)
    source_digest = hashlib.sha256(('dmate.confirmed-batch/1\n' + serialized_sources).encode()).hexdigest()
    context = {'profile': 'confirmed-batch/1', 'document': document,
               'source_sha256': source_digest, 'document_sha256': document_digest(document),
               'question_text': question, 'rendered_question_text': rendered,
               'revision': [item['revision'] for item in contexts],
               'confirmed_sources': sources}
    if len(json.dumps(context, ensure_ascii=False, allow_nan=False).encode()) > MAX_BYTES:
        raise ConfirmationError('confirmation_batch_too_large', '这些图片的题目结构过大，请分批发送。')
    return context
