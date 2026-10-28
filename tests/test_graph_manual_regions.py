"""Manual-first upload and bounded region text OCR, without any vision AI."""
import hashlib
import io
import json

import pytest
from PIL import Image, ImageDraw

from graph_region import RegionError, crop_region, validate_polygon
from test_ocr_application_contract import application


def raw_image():
    image = Image.new("RGB", (400, 240), "white")
    paint = ImageDraw.Draw(image)
    paint.rectangle((80, 48, 310, 180), fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_polygon_roi_masks_non_selected_pixels_even_inside_its_bounding_rectangle():
    polygon = [[.14, .18], [.8, .18], [.77, .8], [.35, .62]]
    cropped = crop_region(raw_image(), polygon)
    image = Image.open(io.BytesIO(cropped)).convert("RGB")
    assert image.size[0] < 400 and image.size[1] < 240
    assert image.getpixel((0, 0)) == (255, 255, 255)
    assert image.getpixel((image.width // 2, image.height // 3)) == (0, 0, 0)
    assert cropped.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("shape", [
    None, [], [[0, 0]], [[.1, .1], [.9, .9]], [[0, 0], [1.1, .5], [0, 1]],
    [[0, 0], [True, .5], [0, 1]], [[.3, .3], [.4, .4], [.5, .5]],
    [[0, 0], [1, 0], [1, float("nan")]],
])
def test_roi_bad_shape_fails_before_image_or_ocr(shape):
    with pytest.raises(RegionError):
        validate_polygon(shape)


def test_manual_upload_has_no_auto_graph_or_text_calls_and_region_only_calls_paddle(application, monkeypatch):
    module, client, _ = application
    raw = raw_image()
    forbidden = lambda *a, **k: pytest.fail("No graph AI may run in manual drawing mode")
    monkeypatch.setattr(module, "_run_graph_ocr_route", forbidden)
    monkeypatch.setattr(module, "analyze_image_structure", forbidden)
    intercepted = []
    def fake_text(image_bytes):
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        intercepted.append((image.width, image.height, image.getpixel((0, 0))))
        return {"text": "求图 G 的顶点数。", "text_count": 1}
    monkeypatch.setattr(module, "recognize_image", fake_text)
    assert client.get("/graph/session").status_code == 200
    starting = client.post("/ocr", data={
        "image": (io.BytesIO(raw), "manual.png"),
        "request_id": "manual-roi-1", "workflow": "manual_graph"
    })
    assert starting.status_code == 200, starting.get_json()
    result = starting.get_json()
    assert result["manual_mode"] is True
    assert result["document"]["graphs"][0]["edges"] == []
    assert intercepted == []
    polygon = [[.15, .18], [.77, .18], [.77, .76], [.15, .76]]
    selected = client.post("/graph/text-region", data={
        "image": (io.BytesIO(raw), "manual.png"), "request_id": "manual-roi-1",
        "polygon": json.dumps(polygon)
    })
    assert selected.status_code == 200, selected.get_json()
    assert selected.get_json()["text"] == "求图 G 的顶点数。"
    assert selected.get_json()["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert len(intercepted) == 1 and intercepted[0][2] == (255, 255, 255)
    cross_source = client.post("/graph/text-region", data={
        "image": (io.BytesIO(Image.new("RGB", (20,20), "white").tobytes()), "different.png"),
        "request_id": "manual-roi-1", "polygon": json.dumps(polygon)
    })
    assert cross_source.status_code == 409
    assert len(intercepted) == 1


def test_text_crop_erases_all_graph_frames_before_ocr():
    from PIL import Image
    import io
    from graph_region import crop_region
    photo=Image.new('RGB',(100,100),'black');data=io.BytesIO();photo.save(data,format='PNG')
    selected=crop_region(data.getvalue(),[[0,0],[1,0],[1,1],[0,1]],
                         exclusions=[[[.2,.2],[.8,.2],[.8,.8],[.2,.8]]])
    with Image.open(io.BytesIO(selected)) as result:
        assert result.getpixel((50,50)) == (255,255,255)
        assert result.getpixel((5,5)) == (0,0,0)
