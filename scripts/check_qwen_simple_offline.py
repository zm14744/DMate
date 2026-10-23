"""Check <=3 saved stage captures and original-pixel crops, with network blocked.

This does not replay a model, score accuracy, upload /ocr, or launch a browser.
Keep the output outside the public checkout because crops are private originals.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageOps
from graph_qwen_coordinates import decode_inventory
from graph_qwen_simple import _node_ambiguities, review_job, select_crop
from graph_relation import recover_relations


def check_case(case, corpus, captures, output):
    started = time.monotonic()
    raw = (corpus/case['image']).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != case['sha256']:
        raise ValueError('original_image_hash_mismatch')
    data = json.loads((captures/(case['id']+'-ocr-response.json')).read_text())
    audit = data['diagnostics']['stage_audit']
    source = next(e['graphs'] for e in audit if e['stage'] == 'EDGE.merged')
    # Explicit test conversion of captured INTERNAL coordinates. This is not
    # a newly observed Qwen original_1000 response and must not be called one.
    native = copy.deepcopy(source)
    for g in native:
        g['bbox'] = [v*1000 for v in g['bbox']]
        for v in g['vertices']:
            v['x'] *= 1000
            v['y'] *= 1000
        for e in g['edges']:
            e['path'] = [[x*1000, y*1000] for x, y in e['path']]
    decoded = decode_inventory({'coordinate_space': 'original_1000', 'graphs': native})
    errors = []
    for before, after in zip(source, decoded):
        assert len(before['vertices']) == len(after['vertices'])
        assert len(before['edges']) == len(after['edges'])
        for a, b in zip(before['vertices'], after['vertices']):
            assert a['id'] == b['id'] and a['label'] == b['label']
            errors += [abs(a[k]-b[k]) for k in ('x', 'y')]
        for a, b in zip(before['edges'], after['edges']):
            for key in ('id', 'from', 'to', 'direction', 'weight', 'edge_label', 'style'):
                assert a.get(key) == b.get(key), key
            assert len(a['path']) == len(b['path'])
            errors += [abs(x-y) for p, q in zip(a['path'], b['path']) for x, y in zip(p, q)]
    assert max(errors, default=0) < 1e-12
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert('RGB')
    node_issues = [issue for g in decoded for issue in _node_ambiguities(g, image.size)]
    panels = next(e['panels'] for e in audit if e['stage'] == 'TRACE')
    related = [recover_relations(g, panels.get(g['id'], [])) for g in decoded]
    plan = select_crop(image.size, decoded, related)
    crop_summary = None
    if plan:
        g = decoded[plan['graph_index']]
        job = review_job(g, related[plan['graph_index']]['_candidates'], plan['rect'], image.size)
        crop = image.crop(plan['rect'])
        path = output/(case['id']+'-original-crop.png')
        crop.save(path)
        reopened = Image.open(path).convert('RGB')
        assert reopened.tobytes() == crop.tobytes()
        assert max(crop.size) <= 1280
        crop_summary = {**plan, 'size': list(crop.size), 'pixel_identical': True,
                        'candidate_ids': [e['id'] for e in job['candidates']],
                        'full_inventory_in_crop': job['full_inventory_in_crop']}
        (output/(case['id']+'-review-job.json')).write_text(json.dumps(job, ensure_ascii=False, indent=2))
    return {'id': case['id'], 'original_sha256': digest, 'original_size': list(image.size),
            'graphs': len(decoded), 'edge_instances_preserved': sum(len(g['edges']) for g in decoded),
            'max_coordinate_round_trip_error': max(errors, default=0), 'node_ambiguities': node_issues,
            'crop': crop_summary, 'offline_seconds': round(time.monotonic()-started, 3),
            'new_model_calls': 0, 'new_model_tokens': 0, 'ocr_upload_performed': False,
            'playwright_performed': False, 'whole_structure_correct': None, 'edge_metrics': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cases', 'corpus', 'captures', 'output'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    if not isinstance(cases, list) or not 1 <= len(cases) <= 3:
        raise ValueError('offline_check_is_limited_to_three_cases')
    checkout = Path(__file__).resolve().parents[1]
    if args.output.resolve().is_relative_to(checkout):
        raise ValueError('private_crops_must_stay_outside_checkout')
    args.output.mkdir(parents=True, exist_ok=True)
    with patch('requests.sessions.Session.request', side_effect=AssertionError('Network forbidden during offline check')):
        rows = [check_case(c, args.corpus, args.captures, args.output) for c in cases]
    report = {'mode': 'offline_coordinate_identity_and_crop_check_not_accuracy', 'cases': rows,
              'new_model_calls': 0, 'new_model_tokens': 0, 'accuracy_scored': False}
    (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
