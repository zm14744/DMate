"""Readable source crops must retain every panel and original coordinate map."""
from PIL import Image, ImageDraw
import pytest

from graph_review_views import build_review_sheet, MAX_REVIEW_PIXELS


def test_small_question_subscripts_are_enlarged_from_pixels_without_ocr_repainting():
    image = Image.new('RGB', (480, 360), 'white')
    draw = ImageDraw.Draw(image)
    draw.line((200, 60, 350, 200), fill='black', width=2)
    # A small distinct mark occupies the question's actual pixel rectangle.
    draw.rectangle((70, 310, 73, 314), fill='blue')
    hints = {'items': [{'id': 't1', 'text': 'THIS OCR TEXT IS DELIBERATELY WRONG',
                        'paddle_role': 'body', 'bbox': [100, 830, 900, 900]}]}
    graph = {'id': 'G', 'bbox': [.35, .10, .85, .65]}
    before = image.tobytes()
    sheet, panels, texts, notes = build_review_sheet(image, [graph], hints=hints)
    assert image.tobytes() == before and not notes
    assert len(panels) == 1 and panels[0]['graph_id'] == 'G'
    assert len(texts) == 1 and texts[0]['hint_ids'] == ['t1']
    tile = texts[0]
    a, b, c, d = tile['sheet_bbox']
    source = image.crop(tile['original_pixel_bbox'])
    assert d-b > source.height
    assert sheet.crop((a, b, c, d)).tobytes() == source.resize((c-a, d-b), Image.Resampling.LANCZOS).tobytes()
    assert max(sheet.size) <= 2200 and sheet.width*sheet.height <= MAX_REVIEW_PIXELS


def test_overlapping_ocr_alternatives_share_pixels_and_preserve_both_ids():
    image = Image.new('RGB', (400, 300), 'white')
    graph = {'id': 'G', 'bbox': [.2, .1, .8, .5]}
    hints = {'items': [
        {'id': 't1', 'bbox': [100, 800, 900, 860], 'paddle_role': 'body'},
        {'id': 't2', 'bbox': [105, 801, 899, 861], 'paddle_role': 'uncertain'},
        {'id': 't3', 'bbox': [400, 200, 450, 250], 'paddle_role': 'graph_labels'}]}
    _, _, texts, notes = build_review_sheet(image, [graph], hints=hints)
    assert not notes and len(texts) == 1
    assert set(texts[0]['hint_ids']) == {'t1', 't2'}


def test_every_panel_survives_a_dense_page_and_mappings_stay_inside_sheet():
    image = Image.new('RGB', (3000, 4000), 'white')
    graphs = [{'id': f'G{i}', 'bbox': [.05+(i%3)*.32, .02+(i//3)*.24,
                                     .30+(i%3)*.32, .22+(i//3)*.24]} for i in range(12)]
    sheet, panels, texts, notes = build_review_sheet(image, graphs)
    assert {t['graph_id'] for t in panels} == {g['id'] for g in graphs}
    assert not texts and not notes
    assert max(sheet.size) <= 2200 and sheet.width*sheet.height <= MAX_REVIEW_PIXELS
    for tile in panels:
        a, b, c, d = tile['sheet_bbox']
        assert 0 <= a < c <= sheet.width and 0 <= b < d <= sheet.height
        a, b, c, d = tile['original_pixel_bbox']
        assert 0 <= a < c <= image.width and 0 <= b < d <= image.height


@pytest.mark.parametrize('bounds', [[0, 0, 0, 1], [0, 0, 1, 2], [0, 0, float('nan'), 1]])
def test_invalid_crop_never_silently_uses_another_region(bounds):
    with pytest.raises(ValueError, match='invalid_panel_review_bounds'):
        build_review_sheet(Image.new('RGB', (100, 100)), [{'id': 'G', 'bbox': bounds}])
