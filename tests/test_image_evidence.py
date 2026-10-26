"""Pixel-preservation tests, not claims about real-image graph accuracy."""
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageDraw
import pytest

from image_evidence import analyze_document, decode_document_image


def png_bytes(image, **kwargs):
    stream = BytesIO()
    image.save(stream, format='PNG', **kwargs)
    return stream.getvalue()


@pytest.mark.parametrize('mode', ['RGBA', 'LA', 'P'])
def test_transparency_becomes_white_without_changing_opaque_ink(mode):
    if mode == 'RGBA':
        image = Image.new('RGBA', (80, 60), (0, 0, 0, 0))
        ImageDraw.Draw(image).line((10, 30, 70, 30), fill=(0, 0, 0, 255), width=3)
    elif mode == 'LA':
        image = Image.new('LA', (80, 60), (0, 0))
        ImageDraw.Draw(image).line((10, 30, 70, 30), fill=(0, 255), width=3)
    else:
        image = Image.new('P', (80, 60), 0)
        image.putpalette([0, 0, 0, 0, 0, 0] + [0] * 762)
        image.info['transparency'] = 0
        ImageDraw.Draw(image).line((10, 30, 70, 30), fill=1, width=3)
    result = analyze_document(png_bytes(image))
    assert result.original.mode == 'RGB'
    assert result.original.getpixel((0, 0)) == (255, 255, 255)
    assert result.original.getpixel((40, 30)) == (0, 0, 0)
    assert result.ink_mask[30, 15:65].min() == 255
    assert not result.quality['dark_background']


def test_partial_alpha_is_composited_instead_of_discarded():
    image = Image.new('RGBA', (4, 3), (0, 0, 0, 128))
    decoded = decode_document_image(png_bytes(image))
    assert decoded.getpixel((1, 1)) == (127, 127, 127)


def test_exif_orientation_is_applied_before_coordinates_are_established():
    image = Image.new('RGB', (30, 20), 'white')
    image.putpixel((0, 0), (255, 0, 0))
    exif = Image.Exif()
    exif[274] = 6
    result = analyze_document(png_bytes(image, exif=exif))
    assert result.original.size == (20, 30)
    assert result.original.getpixel((19, 0)) == (255, 0, 0)
    assert result.quality['exif_transposed']


def test_input_limit_invalid_bytes_and_explicit_work_coordinates():
    image = Image.new('RGB', (800, 400), 'white')
    with pytest.raises(ValueError, match='pixel limit'):
        decode_document_image(png_bytes(image), max_pixels=1000)
    with pytest.raises(ValueError):
        decode_document_image(b'not an image')
    result = analyze_document(image, max_work_side=200)
    assert result.original.size == (800, 400)
    assert result.work_size == (200, 100)
    assert result.scale_xy == (.25, .25)
    assert result.normalized.size == result.sharpened.size == result.working.size == (200, 100)
    for mask in (result.ink_mask, result.strong_ink, result.uncertain_ink):
        assert mask.shape == (100, 200) and mask.dtype == np.uint8


def test_clean_diagram_is_not_repainted_by_background_processing():
    image = Image.new('RGB', (240, 160), 'white')
    ImageDraw.Draw(image).line((30, 80, 210, 80), fill=(0, 0, 0), width=3)
    before = np.asarray(image).copy()
    result = analyze_document(image)
    assert np.array_equal(np.asarray(result.original), before)
    assert np.array_equal(np.asarray(result.normalized), before)
    assert not result.quality['background_normalized']
    assert result.ink_mask[80, 40:200].min() == 255
    assert not np.any(result.ink_mask[:50])


def test_dark_screen_preserves_bright_connector_and_original_polarity():
    array = np.full((160, 300, 3), 25, np.uint8)
    cv2.line(array, (30, 80), (270, 80), (240, 240, 240), 3)
    result = analyze_document(Image.fromarray(array))
    assert result.quality['dark_background']
    assert result.original.getpixel((0, 0)) == (25, 25, 25)
    assert result.normalized.getpixel((0, 0)) == (255, 255, 255)
    assert result.ink_mask[80, 60:240].min() == 255
    assert not np.any(result.ink_mask[:40])


def test_saturated_dark_blue_background_has_a_neutral_auxiliary_background():
    array = np.full((160, 300, 3), (0, 0, 240), np.uint8)
    cv2.line(array, (30, 80), (270, 80), (255, 255, 255), 3)
    result = analyze_document(Image.fromarray(array))
    assert result.quality['dark_background']
    assert result.normalized.getpixel((0, 0)) == (255, 255, 255)
    assert result.ink_mask[80, 60:240].min() == 255
    assert np.array_equal(np.asarray(result.original), array)


@pytest.mark.parametrize('color', [(255, 230, 0), (0, 100, 255), (240, 40, 20), (40, 190, 80)])
def test_colored_thin_strokes_survive_without_colored_background_noise(color):
    image = Image.new('RGB', (300, 160), 'white')
    ImageDraw.Draw(image).line((30, 80, 270, 80), fill=color, width=2)
    result = analyze_document(image)
    assert result.ink_mask[80, 60:240].min() == 255
    assert result.quality['color_ink_fraction'] > 0
    assert not np.any(result.ink_mask[:40])


def test_smooth_shadow_is_not_promoted_to_a_large_foreground_region():
    gradient = np.tile(np.linspace(95, 230, 320, dtype=np.uint8), (180, 1))
    array = np.repeat(gradient[:, :, None], 3, axis=2)
    cv2.line(array, (30, 90), (290, 90), (20, 20, 20), 3)
    result = analyze_document(Image.fromarray(array))
    assert result.quality['background_normalized']
    assert result.ink_mask[90, 45:275].min() == 255
    assert (result.ink_mask[:50] > 0).mean() < .01
    assert (result.ink_mask[130:] > 0).mean() < .01
    assert np.array_equal(np.asarray(result.original), array)


def test_possible_show_through_is_retained_as_uncertain_not_erased():
    array = np.full((180, 320, 3), 170, np.uint8)
    cv2.line(array, (30, 60), (290, 60), (130, 130, 130), 2)
    cv2.line(array, (30, 120), (290, 120), (25, 25, 25), 3)
    result = analyze_document(Image.fromarray(array))
    assert result.ink_mask[120, 45:275].min() == 255
    assert result.ink_mask[60, 45:275].max() == 0
    assert result.uncertain_ink[60, 45:275].min() == 255
    assert np.array_equal(np.asarray(result.original), array)


def test_all_faint_diagram_remains_available_with_explicit_uncertainty():
    image = Image.new('RGB', (240, 160), 'white')
    ImageDraw.Draw(image).line((20, 80, 220, 80), fill=(230, 230, 230), width=2)
    result = analyze_document(image)
    assert result.quality['low_contrast_only']
    assert result.ink_mask[80, 40:200].min() == 255
    assert result.uncertain_ink[80, 40:200].min() == 255


def test_connected_faint_texture_cannot_promote_the_whole_background_to_ink():
    yy, xx = np.indices((200, 320))
    squares = ((yy // 7 + xx // 7) % 2).astype(np.uint8)
    array = np.repeat((255 - squares * 55)[:, :, None], 3, axis=2)
    cv2.line(array, (30, 100), (290, 100), (0, 0, 0), 1)
    result = analyze_document(Image.fromarray(array))
    assert result.quality['weak_flood_limited']
    assert result.ink_mask[100, 45:275].min() == 255
    assert (result.ink_mask[:50] > 0).mean() < .01
    assert (result.uncertain_ink[:50] > 0).mean() > .05


def test_parallel_white_corridor_and_loop_hole_are_not_closed_in_ink_mask():
    array = np.full((180, 320, 3), 255, np.uint8)
    cv2.line(array, (30, 50), (170, 50), (0, 0, 0), 1)
    cv2.line(array, (30, 54), (170, 54), (0, 0, 0), 1)
    cv2.circle(array, (240, 100), 25, (0, 0, 0), 2)
    result = analyze_document(Image.fromarray(array))
    assert result.ink_mask[50, 45:155].min() == 255
    assert result.ink_mask[54, 45:155].min() == 255
    assert not np.any(result.ink_mask[51:54, 45:155])
    assert result.ink_mask[100, 240] == 0
    assert result.ink_mask[100, 265] == 255


def test_blur_assistance_never_overwrites_original_or_becomes_mask_source():
    array = np.full((180, 320, 3), 255, np.uint8)
    cv2.line(array, (30, 90), (290, 90), (0, 0, 0), 3)
    blurred = cv2.GaussianBlur(array, (0, 0), 2.)
    result = analyze_document(Image.fromarray(blurred))
    assert result.quality['possible_blur']
    assert np.array_equal(np.asarray(result.original), blurred)
    assert not np.array_equal(np.asarray(result.sharpened), np.asarray(result.normalized))
    assert result.quality['mask_source'] == 'working_image_local_contrast_not_sharpened'
    assert not np.any(result.ink_mask[:40])
