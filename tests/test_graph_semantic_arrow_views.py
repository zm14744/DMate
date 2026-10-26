"""Source-view contracts only; no original corpus, labels, OCR or model calls."""
import base64
import hashlib
import io
import json
import time

import pytest
from PIL import Image, ImageDraw

import graph_semantic_arrow_views as arrow
from dmate_tool_registry import ToolContext, ToolTimeout
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
    image.save(stream, 'PNG', **kwargs)
    return stream.getvalue()


def decoded(value):
    return Image.open(io.BytesIO(base64.b64decode(value.split(',', 1)[1]))).convert('RGB')


def test_small_source_always_gets_four_magnified_overlapping_original_crops():
    image = Image.new('RGB', (582, 522), 'white')
    draw = ImageDraw.Draw(image)
    draw.line((12, 500, 290, 270, 560, 30), fill=(7, 30, 220), width=3)
    draw.polygon(((290, 270), (291, 286), (306, 277)), fill=(230, 0, 30))
    raw = png(image)
    result = arrow.prepare_arrow_views(raw, budget=Budget())
    assert len(result['images']) == len(result['view_descriptions']) == 5
    assert decoded(result['images'][0]).tobytes() == image.tobytes()
    expected = [(0, 0, 326, 293), (256, 0, 582, 293),
                (0, 229, 326, 522), (256, 229, 582, 522)]
    coverage = Image.new('L', image.size)
    for index, box in enumerate(expected, 1):
        metadata, output = result['view_metadata'][index], decoded(result['images'][index])
        crop = image.crop(box)
        assert metadata['source_box'] == list(box)
        assert metadata['source_pixel_sha256'] == hashlib.sha256(crop.tobytes()).hexdigest()
        assert metadata['output_size'] == list(output.size) and max(output.size) == 1280
        assert metadata['resampling'] == 'nearest'
        assert output.tobytes() == crop.resize(output.size, Image.Resampling.NEAREST).tobytes()
        assert metadata['output_png_sha256'] == hashlib.sha256(base64.b64decode(
            result['images'][index].split(',', 1)[1])).hexdigest()
        assert '同一原图' in result['view_descriptions'][index]
        assert '不是新增子图' in result['view_descriptions'][index]
        coverage.paste(255, box)
    assert coverage.getextrema() == (255, 255)
    assert expected[0][2] > expected[1][0] and expected[0][3] > expected[2][1]
    assert hashlib.sha256(raw).hexdigest() == result['image_quality']['source_sha256']
    assert result['tool_audit'][0]['tool'] == 'image.arrow_views'
    assert result['tool_audit'][0]['status'] == 'success'
    assert result['tool_audit'][0]['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert len(json.dumps(result['tool_audit'])) < 2000
    assert 'data:image' not in json.dumps(result['tool_audit'])


@pytest.mark.parametrize('size', [(1, 1), (1, 100), (100, 1), (20, 30), (2000, 1200), (5000, 3000)])
def test_view_capacity_and_nonempty_pixel_boxes(size):
    result = arrow.prepare_arrow_views(png(Image.new('RGB', size, 'white')), budget=Budget())
    assert 1 <= len(result['images']) <= 5
    pixels = 0
    for index, (value, metadata) in enumerate(zip(result['images'], result['view_metadata'])):
        output = decoded(value)
        assert max(output.size) <= (1600 if index == 0 else 1280)
        x0, y0, x1, y1 = metadata['source_box']
        assert 0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1]
        assert output.width <= 6 * (x1-x0) and output.height <= 6 * (y1-y0)
        pixels += output.width * output.height
    assert pixels == result['image_quality']['output_pixels'] <= arrow.MAX_TOTAL_PIXELS


def test_alpha_and_exif_share_canonical_white_background_decode():
    image = Image.new('RGBA', (70, 40), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((5, 4, 20, 15), fill=(190, 4, 14, 255))
    exif = Image.Exif()
    exif[274] = 6
    raw = png(image, exif=exif)
    result = arrow.prepare_arrow_views(raw, budget=Budget())
    original = decode_document_image(raw)
    assert result['image_quality']['original_size'] == [40, 70]
    assert decoded(result['images'][0]).tobytes() == original.tobytes()
    assert original.getpixel((0, 0)) == (255, 255, 255)
    for metadata in result['view_metadata']:
        crop = original.crop(metadata['source_box'])
        assert metadata['source_pixel_sha256'] == hashlib.sha256(crop.tobytes()).hexdigest()


@pytest.mark.parametrize('error', [RuntimeError('private-image-text'), ToolTimeout()])
def test_failed_local_view_keeps_original_with_explicit_failed_audit(monkeypatch, error):
    real = arrow._resize
    def fail(image, side, *, enlarge):
        if enlarge:
            raise error
        return real(image, side, enlarge=enlarge)
    monkeypatch.setattr(arrow, '_resize', fail)
    image = Image.new('RGB', (90, 50), 'red')
    result = arrow.prepare_arrow_views(png(image), budget=Budget())
    assert len(result['images']) == 1 and decoded(result['images'][0]).tobytes() == image.tobytes()
    assert result['image_quality']['preprocessing_status'] == 'fallback_original'
    assert result['tool_audit'][0]['status'] in ('failed', 'timeout')
    assert 'private-image-text' not in json.dumps(result)


def test_cancel_before_decode_and_during_crop_propagates(monkeypatch):
    budget = Budget()
    error = RuntimeError('cancelled')
    budget.error = error
    with pytest.raises(RuntimeError) as caught:
        arrow.prepare_arrow_views(b'not-image', budget=budget)
    assert caught.value is error
    real = arrow._resize
    def cancel(image, side, *, enlarge):
        result = real(image, side, enlarge=enlarge)
        if enlarge:
            budget.error = error
        return result
    monkeypatch.setattr(arrow, '_resize', cancel)
    with pytest.raises(RuntimeError) as caught:
        arrow.prepare_arrow_views(png(Image.new('RGB', (30, 20))), budget=budget)
    assert caught.value is error


def test_task_deadline_during_views_is_not_a_successful_fallback(monkeypatch):
    budget, real = Budget(), arrow._resize
    def expire(image, side, *, enlarge):
        result = real(image, side, enlarge=enlarge)
        if enlarge:
            budget.deadline = time.monotonic() - 1
        return result
    monkeypatch.setattr(arrow, '_resize', expire)
    with pytest.raises(TimeoutError, match='task_deadline'):
        arrow.prepare_arrow_views(png(Image.new('RGB', (30, 20))), budget=budget)


def test_source_identity_and_shared_decoder_pixel_limit_are_enforced():
    budget = Budget()
    budget.source_sha256 = '0' * 64
    with pytest.raises(ValueError, match='source_identity'):
        arrow.prepare_arrow_views(png(Image.new('RGB', (10, 10))), budget=budget)
    with pytest.raises(ValueError, match='pixel limit'):
        arrow.prepare_arrow_views(png(Image.new('RGB', (4100, 4000))), budget=Budget())


def test_tool_accepts_no_model_crop_and_cannot_be_called_by_other_roles():
    registry = arrow._build_registry()
    context = ToolContext(source_sha256='a' * 64)
    invalid = registry.call('image.arrow_views', {'box': [0, 0, 4, 4]}, role='semantic_review', context=context)
    assert invalid['error']['code'] == 'invalid_arguments'
    denied = registry.call('image.arrow_views', {}, role='connections', context=context)
    assert denied['status'] == 'denied'
    assert registry.describe(role='semantic_extract') == []


def test_panel_hint_adds_padding_but_keeps_full_original_and_source_pixels():
    image = Image.new('RGB', (1000, 800), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((200, 160, 600, 640), fill='blue')
    draw.line((190, 160, 610, 650), fill='red', width=5)
    raw = png(image)
    overview = arrow.prepare_arrow_views(raw, budget=Budget())
    before = json.dumps(overview)
    result = arrow.prepare_panel_views(raw, graph={'bbox': [200, 200, 600, 800]},
                                       overview_views=overview, budget=Budget())
    assert len(result['images']) == 2
    assert result['images'][0] == overview['images'][0]
    assert decoded(result['images'][0]).tobytes() == image.tobytes()
    metadata = result['view_metadata'][1]
    assert metadata['source_box'] == [152, 102, 648, 698]
    crop, output = image.crop(metadata['source_box']), decoded(result['images'][1])
    assert max(output.size) == 1600
    assert output.tobytes() == crop.resize(output.size, Image.Resampling.NEAREST).tobytes()
    assert metadata['source_pixel_sha256'] == hashlib.sha256(crop.tobytes()).hexdigest()
    assert result['image_quality']['panel_view_status'] == 'cropped'
    assert result['tool_audit'][-1]['tool'] == 'image.panel_views'
    assert result['tool_audit'][-1]['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert '框不准' in result['view_descriptions'][1]
    assert json.dumps(overview) == before


@pytest.mark.parametrize('bbox', [None, [], [0, 0, 0, 10], [10, 0, 0, 10],
                                 [-1, 0, 10, 10], [0, 0, 1001, 10],
                                 [0, False, 10, 10], [0, 0, float('nan'), 10]])
def test_missing_or_invalid_panel_hint_keeps_all_existing_views(monkeypatch, bbox):
    raw = png(Image.new('RGB', (80, 60), 'blue'))
    overview = arrow.prepare_arrow_views(raw, budget=Budget())
    monkeypatch.setattr(arrow, 'decode_document_image', lambda raw: pytest.fail('invalid hints need no new decode'))
    result = arrow.prepare_panel_views(raw, graph={'bbox': bbox}, overview_views=overview, budget=Budget())
    assert result['images'] == overview['images'] and len(result['images']) == 5
    assert result['view_descriptions'] == overview['view_descriptions']
    assert result['tool_audit'] == overview['tool_audit']
    assert result['image_quality']['panel_view_status'] == 'no_panel_hint'
    assert 'panel_view_status' not in overview['image_quality']


def test_separate_panels_are_cropped_from_same_full_source_with_clipped_padding():
    image = Image.new('RGB', (200, 100), 'red')
    ImageDraw.Draw(image).rectangle((100, 0, 199, 99), fill='blue')
    raw = png(image)
    overview = arrow.prepare_arrow_views(raw, budget=Budget())
    results = [arrow.prepare_panel_views(raw, graph={'bbox': box}, overview_views=overview, budget=Budget())
               for box in ([0, 0, 400, 1000], [600, 0, 1000, 1000])]
    for result, colour in zip(results, ((255, 0, 0), (0, 0, 255))):
        assert result['images'][0] == overview['images'][0]
        output = decoded(result['images'][1])
        assert output.getpixel((output.width//2, output.height//2)) == colour
        assert max(output.size) <= 1600
        x0, y0, x1, y1 = result['view_metadata'][1]['source_box']
        assert output.width <= 6*(x1-x0) and output.height <= 6*(y1-y0)
    assert results[0]['view_metadata'][1]['source_box'][0] == 0
    assert results[1]['view_metadata'][1]['source_box'][2] == image.width


def test_panel_tool_failure_retains_overviews_and_cancel_does_not(monkeypatch):
    raw = png(Image.new('RGB', (50, 30), 'white'))
    overview = arrow.prepare_arrow_views(raw, budget=Budget())
    def fail(raw):
        raise RuntimeError('private-source-content')
    monkeypatch.setattr(arrow, 'decode_document_image', fail)
    result = arrow.prepare_panel_views(raw, graph={'bbox': [0, 0, 1000, 1000]},
                                       overview_views=overview, budget=Budget())
    assert result['images'] == overview['images']
    assert result['image_quality']['panel_view_status'] == 'fallback_original'
    assert result['tool_audit'][-1]['status'] == 'failed'
    assert 'private-source-content' not in json.dumps(result)
    budget, error = Budget(), RuntimeError('cancelled')
    def cancel(raw):
        image = decode_document_image(raw)
        budget.error = error
        return image
    monkeypatch.setattr(arrow, 'decode_document_image', cancel)
    with pytest.raises(RuntimeError) as caught:
        arrow.prepare_panel_views(raw, graph={'bbox': [0, 0, 1000, 1000]},
                                  overview_views=overview, budget=budget)
    assert caught.value is error
