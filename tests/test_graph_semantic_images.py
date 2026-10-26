"""Source-only semantic views; no OCR, graph algorithms, or network calls."""
import base64
import hashlib
import io
import json
import time

import numpy as np
import pytest
from PIL import Image, ImageDraw

import graph_semantic_images as semantic
from dmate_tool_registry import MAX_JSON_BYTES, ROLES, ToolContext, ToolTimeout
from image_evidence import decode_document_image


class Budget:
    def __init__(self):
        self.deadline = time.monotonic() + 60
        self.error = None

    def check(self):
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        if time.monotonic() >= self.deadline:
            raise TimeoutError('task_deadline')


def png(image, **kwargs):
    stream = io.BytesIO()
    image.save(stream, format='PNG', **kwargs)
    return stream.getvalue()


def decoded(url):
    prefix, encoded = url.split(',', 1)
    assert prefix == 'data:image/png;base64'
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        return image.convert('RGB')


def assert_bounded(result):
    assert 1 <= len(result['images']) <= 5
    assert len(result['images']) == len(result['view_descriptions'])
    for url in result['images']:
        image = decoded(url)
        assert max(image.size) <= 1600
        assert image.width * image.height <= 2_600_000
    assert len(result['local_text_hint']) <= 3000


def test_clean_small_source_has_one_exact_colour_view_and_safe_audit():
    image = Image.new('RGB', (220, 140), 'white')
    draw = ImageDraw.Draw(image)
    draw.line((20, 30, 180, 110), fill=(240, 5, 15), width=4)
    draw.text((25, 50), 'A  8', fill=(10, 40, 220))
    raw = png(image)
    before = hashlib.sha256(raw).hexdigest()
    result = semantic.prepare_semantic_images(raw, budget=Budget())
    assert_bounded(result)
    assert len(result['images']) == 1
    assert decoded(result['images'][0]).tobytes() == image.tobytes()
    assert result['image_quality']['source_sha256'] == before
    assert hashlib.sha256(raw).hexdigest() == before
    audit = result['tool_audit']
    assert len(audit) == 1 and audit[0]['tool'] == 'image.semantic_views'
    assert audit[0]['status'] == 'success' and audit[0]['source_sha256'] == before
    assert 'data:image' not in json.dumps(audit)


def test_large_views_are_overlapping_original_crops_in_fixed_order():
    image = Image.new('RGB', (1900, 1200), 'white')
    draw = ImageDraw.Draw(image)
    for box, colour in [((0, 0, 949, 599), 'red'), ((950, 0, 1899, 599), 'green'),
                        ((0, 600, 949, 1199), 'blue'), ((950, 600, 1899, 1199), 'yellow')]:
        draw.rectangle(box, fill=colour)
    draw.text((940, 590), 'middle 8', fill='black')
    raw = png(image)
    result = semantic.prepare_semantic_images(raw, budget=Budget(), layout=[{'fake_graph_count': 88}])
    assert_bounded(result)
    assert len(result['images']) == 5
    expected = [(0, 0, 1064, 672), (836, 0, 1900, 672),
                (0, 528, 1064, 1200), (836, 528, 1900, 1200)]
    for i, (label, box) in enumerate(zip(('左上', '右上', '左下', '右下'), expected), 1):
        crop = decoded(result['images'][i])
        assert crop.size == image.crop(box).size
        assert crop.tobytes() == image.crop(box).tobytes()
        assert label in result['view_descriptions'][i]
        assert '不能作为新增子图' in result['view_descriptions'][i]
    assert result['image_quality']['normalization_view_included'] is False


@pytest.mark.parametrize('size,count', [((1800, 1000), 1), ((1801, 1000), 5), ((1700, 1600), 5)])
def test_large_image_thresholds_and_boundaries(size, count):
    result = semantic.prepare_semantic_images(png(Image.new('RGB', size, 'white')), budget=Budget())
    assert_bounded(result)
    assert len(result['images']) == count


def test_photo_views_can_exceed_registry_json_bytes_without_losing_crops():
    pixels = np.random.default_rng(7).integers(0, 256, size=(1500, 1900, 3), dtype=np.uint8)
    raw = png(Image.fromarray(pixels))
    result = semantic.prepare_semantic_images(raw, budget=Budget())
    assert_bounded(result)
    assert sum(len(value) for value in result['images']) > MAX_JSON_BYTES
    assert len(result['images']) == 5
    assert result['tool_audit'][0]['status'] == 'success'
    assert len(json.dumps(result['tool_audit'])) < 2000


def test_shadow_normalization_is_only_auxiliary_and_original_stays_first():
    ramp = np.linspace(110, 255, 300).astype(np.uint8)
    image = Image.fromarray(np.repeat(np.tile(ramp, (180, 1))[..., None], 3, axis=2))
    ImageDraw.Draw(image).text((30, 70), 'Question 9', fill=(210, 0, 25))
    result = semantic.prepare_semantic_images(png(image), budget=Budget())
    assert_bounded(result)
    assert len(result['images']) == 2
    assert decoded(result['images'][0]).tobytes() == image.tobytes()
    assert result['image_quality']['normalization_view_included'] is True
    assert '光照归一化辅助' in result['view_descriptions'][1]
    assert decoded(result['images'][1]).tobytes() != image.tobytes()


def test_exif_and_transparency_use_shared_canonical_decode():
    image = Image.new('RGBA', (50, 30), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((5, 4, 12, 10), fill=(250, 0, 0, 255))
    exif = Image.Exif()
    exif[274] = 6
    raw = png(image, exif=exif)
    result = semantic.prepare_semantic_images(raw, budget=Budget())
    first = decoded(result['images'][0])
    assert first.size == (30, 50)
    assert first.tobytes() == decode_document_image(raw).tobytes()
    assert first.getpixel((0, 0)) == (255, 255, 255)
    assert result['image_quality']['exif_transposed'] is True
    assert result['image_quality']['transparency_present'] is True


def test_local_ocr_is_bounded_optional_untrusted_text_without_coordinates():
    raw = png(Image.new('RGB', (30, 30), 'white'))
    text_result = {'text': '候选正文', 'text_evidence': {
        'graph_labels': [{'content': '边标候选', 'box': [1, 2, 3, 4]}],
        'uncertain': [{'content': '候选字' * 3000}],
    }}
    result = semantic.prepare_semantic_images(raw, budget=Budget(), text_result=text_result)
    assert '可能漏字或错字' in result['local_text_hint']
    assert '候选正文' in result['local_text_hint'] and '边标候选' in result['local_text_hint']
    assert len(result['local_text_hint']) == 3000
    assert '[1, 2, 3, 4]' not in result['local_text_hint']
    assert '候选正文' not in json.dumps(result['tool_audit'], ensure_ascii=False)
    absent = semantic.prepare_semantic_images(raw, budget=Budget(), text_result={'text_evidence': None})
    assert absent['local_text_hint'] == ''
    assert absent['tool_audit'][0]['status'] == 'success'


@pytest.mark.parametrize('error', [RuntimeError('private-response-and-url'), ToolTimeout()])
def test_tool_failure_falls_back_to_original_without_error_text(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(semantic, 'analyze_document', fail)
    raw = png(Image.new('RGB', (80, 50), 'red'))
    result = semantic.prepare_semantic_images(raw, budget=Budget(), text_result={'text': 'hint'})
    assert len(result['images']) == 1
    assert decoded(result['images'][0]).getpixel((0, 0)) == (255, 0, 0)
    assert result['image_quality']['preprocessing_status'] == 'fallback_original'
    assert result['tool_audit'][0]['status'] in ('failed', 'timeout')
    assert 'private-response-and-url' not in json.dumps(result)
    assert 'hint' in result['local_text_hint']


def test_cancel_before_decode_propagates(monkeypatch):
    budget = Budget()
    error = RuntimeError('cancelled')
    budget.error = error
    monkeypatch.setattr(semantic, 'decode_document_image', lambda raw: pytest.fail('decode after cancel'))
    with pytest.raises(RuntimeError) as caught:
        semantic.prepare_semantic_images(b'not-an-image', budget=budget)
    assert caught.value is error


def test_cancel_during_tool_is_not_swallowed_even_when_callback_resets(monkeypatch):
    budget = Budget()
    error = RuntimeError('cancelled')
    actual = semantic.analyze_document
    def cancel(*args, **kwargs):
        document = actual(*args, **kwargs)
        budget.error = error
        return document
    monkeypatch.setattr(semantic, 'analyze_document', cancel)
    with pytest.raises(RuntimeError) as caught:
        semantic.prepare_semantic_images(png(Image.new('RGB', (20, 20), 'white')), budget=budget)
    assert caught.value is error


def test_task_deadline_during_tool_does_not_return_fallback(monkeypatch):
    budget = Budget()
    actual = semantic.analyze_document
    def expire(*args, **kwargs):
        document = actual(*args, **kwargs)
        budget.deadline = time.monotonic() - 1
        return document
    monkeypatch.setattr(semantic, 'analyze_document', expire)
    with pytest.raises(TimeoutError, match='task_deadline'):
        semantic.prepare_semantic_images(png(Image.new('RGB', (20, 20), 'white')), budget=budget)


@pytest.mark.parametrize('raw', [b'', b'not-an-image'])
def test_invalid_source_is_fatal(raw):
    with pytest.raises(ValueError):
        semantic.prepare_semantic_images(raw, budget=Budget())


def test_source_pixel_limit_stays_enforced():
    raw = png(Image.new('RGB', (4100, 4000), 'white'))
    with pytest.raises(ValueError, match='pixel limit'):
        semantic.prepare_semantic_images(raw, budget=Budget())


def test_registered_tool_only_has_semantic_roles_and_no_caller_crop_protocol():
    roles = {'semantic_extract', 'semantic_review', 'semantic_repair'}
    assert roles <= ROLES
    registry = semantic._build_registry()
    for role in roles:
        available = registry.describe(role=role)
        assert [row['name'] for row in available] == ['image.semantic_views']
    context = ToolContext(source_sha256='a' * 64)
    invalid = registry.call('image.semantic_views', {'bbox': [0, 0, 1, 1]},
                            role='semantic_extract', context=context)
    assert invalid['error']['code'] == 'invalid_arguments'
    denied = registry.call('image.semantic_views', {}, role='connections', context=context)
    assert denied['status'] == 'denied'
