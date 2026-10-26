"""Bounded, located OCR hints and explicit second-image text reconciliation."""
from __future__ import annotations
import math
import re
import unicodedata

MAX_HINTS = 128
MAX_HINT_CHARACTERS = 24000

# Logical polarity, quantifiers and mathematical objects are content, even
# when written as Chinese words rather than mathematical operators. The one
# ideographic variant below is an equivalent glyph, not a semantic rewrite.
_SEMANTIC_VARIANTS = str.maketrans({'奌': '点'})
_SEMANTIC_TERMS = (
    '不小于','不大于','大于','小于','等于','不等于','不等','至少','至多','最多','最少','不超过',
    '大','小','长','短','有向','无向','强连通','弱连通','连通','顶点','端点','边','弧',
    '入度','出度','度数','度','权值','权','重数','重边','平行','自环','环','路径','通路','回路',
    '邻接','关联','独立','孤立','完全','简单','二部','树','森林','欧拉','哈密顿',
    '充分','必要','互斥','包含','属于','相等','不同','相同','相交','交集','并集','补集','子集',
    '对称','反对称','传递','自反','反自反','单射','满射','双射','单调','递增','递减',
    '素数','质数','合数','整除','正','负','奇','偶','且','或','并','与','非','不','无','有',
    '所有','任意','任一','每','存在','唯一','仅','恰','全','真','假','两',
)
_SEMANTIC_PATTERN = re.compile('|'.join(re.escape(x) for x in sorted(_SEMANTIC_TERMS,key=len,reverse=True)))


def _han(char):
    value=ord(char)
    return (0x3400<=value<=0x9fff or 0xf900<=value<=0xfaff
            or 0x20000<=value<=0x323af)


def critical_sequence(text):
    """Protect numeric/Latin/Greek/math content without NFKC flattening x²."""
    result = []
    normalized=unicodedata.normalize('NFC', str(text))
    for char in normalized:
        category = unicodedata.category(char)
        # NFKC is only used to classify punctuation, never to rewrite or
        # compare mathematical letters, exponents, fractions or subscripts.
        punctuation=unicodedata.normalize('NFKC',char)
        if (char.isnumeric() or category.startswith(('N','M','S','P'))
                or (category.startswith('L') and not _han(char))
                or punctuation in '+-*/=<>^_{}[]()\\$|:.,;%!′″'):
            result.append(char)
    terms=_SEMANTIC_PATTERN.findall(normalized.translate(_SEMANTIC_VARIANTS))
    return ''.join(result)+'\0'+'\0'.join(terms)


def content_signature(text):
    """All wording is substantive; only equivalent glyphs/spacing normalize.

An expanding mathematical-keyword list can never protect all Chinese meaning.
Use this whole-text guard for actual edits and visual disagreement, while the
critical sequence remains a useful additional mathematical diagnostic.
    """
    text=unicodedata.normalize('NFC',str(text)).translate(_SEMANTIC_VARIANTS)
    return re.sub(r'\s+',' ',text).strip()


def _label_in_panel(hint, graph):
    bounds=hint.get('bbox'); panel=graph.get('bbox')
    if not isinstance(bounds,list) or len(bounds)!=4 or not isinstance(panel,list) or len(panel)!=4:
        return False
    try:
        a,b,c,d=[float(v)/1000 for v in bounds]
        x1,y1,x2,y2=map(float,panel)
        if not all(math.isfinite(v) for v in (a,b,c,d,x1,y1,x2,y2)) or not (a<c and b<d):
            return False
        # OCR boxes can straddle a node/diagram boundary by a few pixels.
        margin=.015
        overlap=max(0,min(c,x2+margin)-max(a,x1-margin))*max(0,min(d,y2+margin)-max(b,y1-margin))
        return overlap/((c-a)*(d-b))>=.50
    except (ValueError,TypeError,OverflowError):
        return False


def _compact(text):
    return ''.join(unicodedata.normalize('NFC', text).split())


def text_hints(text_result):
    result = text_result if isinstance(text_result, dict) else {}
    evidence = result.get('text_evidence') or {}
    if not isinstance(evidence, dict):
        evidence = {}
    size = evidence.get('image_size')
    located = (isinstance(size, (list, tuple)) and len(size) == 2
               and all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in size))
    rows, issues, seen, characters = [], [], set(), 0
    for role in ('body', 'graph_labels', 'noise', 'uncertain'):
        items = evidence.get(role, [])
        if not isinstance(items, list):
            issues.append('invalid_local_text_records')
            continue
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get('content'), str):
                issues.append('invalid_local_text_record')
                continue
            content = item['content']
            if not content.strip():
                continue
            bounds = item.get('box')
            bbox = None
            if located and isinstance(bounds, (list, tuple)) and len(bounds) == 4:
                try:
                    a, b, c, d = [float(v) for v in bounds]
                    if 0 <= a < c <= size[0] and 0 <= b < d <= size[1]:
                        bbox = [round(a/size[0]*1000, 2), round(b/size[1]*1000, 2),
                                round(c/size[0]*1000, 2), round(d/size[1]*1000, 2)]
                except (TypeError, ValueError, OverflowError):
                    pass
            key = (content, tuple(bbox) if bbox else None)
            if key in seen:
                continue
            seen.add(key)
            if len(rows) >= MAX_HINTS or len(content) > 512 or characters+len(content) > MAX_HINT_CHARACTERS:
                issues.append('local_text_hint_capacity_limited')
                continue
            row = {'id': 't'+str(len(rows)+1), 'text': content, 'paddle_role': role}
            if bbox is not None:
                row['bbox'] = bbox
            score = item.get('score')
            if type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1:
                row['score'] = round(score, 4)
            rows.append(row)
            characters += len(content)
    # Legacy adapters may have text but no boxes. Keep it explicitly unlocated.
    fallback = result.get('text')
    if not rows and isinstance(fallback, str) and fallback.strip():
        if len(fallback) <= 12000:
            rows.append({'id': 't1', 'text': fallback, 'paddle_role': 'unlocated'})
        else:
            issues.append('local_text_hint_capacity_limited')
    stages = result.get('resource_metrics') or []
    statuses = [x.get('status') for x in stages if isinstance(x, dict) and x.get('stage') == 'text']
    return {'items': rows, 'issues': list(dict.fromkeys(issues)),
            'local_status': statuses[-1] if statuses else 'unobserved'}


def reconcile_text(first, second, hints, graphs):
    """Image review can resolve a conflict; ordinary text polishing cannot."""
    first_text = first.get('body_text') if isinstance(first.get('body_text'), str) else ''
    review = second.get('text_review')
    issues = list(hints.get('issues', []))
    audit = {'local_status': hints.get('local_status', 'unobserved'),
             'first_body_complete': first.get('body_complete') is True,
             'second_pass_reviewed': False, 'conflicts': [], 'region_decisions': []}
    if not isinstance(review, dict):
        issues.append('second_text_review_missing')
        return first_text[:12000], False, {**audit, 'issues': issues}
    text, decisions = review.get('text'), review.get('regions')
    if not isinstance(text, str) or len(text) > 12000 or not isinstance(decisions, list):
        issues.append('invalid_second_text_review')
        return first_text[:12000], False, {**audit, 'issues': issues}
    if review.get('complete') is not True:
        issues.append('body_review_incomplete')
    audit['second_pass_reviewed'] = True
    if content_signature(first_text) != content_signature(text):
        audit['conflicts'].append({'source': 'first_visual_body', 'resolved': bool(review.get('reason'))})
        if not isinstance(review.get('reason'), str) or not review['reason'].strip():
            issues.append('unexplained_visual_text_change')
    expected = {row['id']: row for row in hints['items']}
    graph_by_id = {g['id']:g for g in graphs}
    seen = set()
    if len(decisions) > MAX_HINTS:
        issues.append('text_review_capacity_exceeded')
        decisions = decisions[:MAX_HINTS]
    for item in decisions:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str):
            issues.append('invalid_text_region_review')
            continue
        rid = item['id']
        if rid not in expected or rid in seen:
            issues.append('unknown_or_duplicate_text_region:'+rid[:48])
            continue
        seen.add(rid)
        role = item.get('role')
        reason = item.get('reason')
        explained = isinstance(reason, str) and bool(reason.strip()) and len(reason) <= 400
        decision = {'id': rid, 'role': role}
        if role == 'body':
            observed = item.get('text')
            if not isinstance(observed, str) or not observed.strip() or len(observed) > 12000:
                issues.append('invalid_body_fragment:'+rid)
            else:
                decision['text'] = observed
                if _compact(observed) not in _compact(text):
                    issues.append('body_fragment_not_in_transcription:'+rid)
                if content_signature(observed) != content_signature(expected[rid]['text']):
                    audit['conflicts'].append({'source': rid, 'resolved': explained})
                    if not explained:
                        issues.append('unexplained_critical_text_conflict:'+rid)
        elif role in ('graph_label', 'noise'):
            if not explained:
                issues.append('unexplained_text_exclusion:'+rid)
            if role == 'graph_label':
                target=graph_by_id.get(item.get('graph_id'))
                if target is None:
                    issues.append('text_label_without_final_panel:'+rid)
                elif not _label_in_panel(expected[rid],target):
                    issues.append('text_label_without_spatial_support:'+rid)
            decision['graph_id'] = item.get('graph_id')
        else:
            issues.append('uncertain_text_region:'+rid)
        if explained:
            decision['reason'] = reason
        audit['region_decisions'].append(decision)
    issues.extend('unreviewed_text_region:'+rid for rid in expected.keys()-seen)
    audit['issues'] = list(dict.fromkeys(issues))
    return text, not issues, audit
