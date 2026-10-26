import hashlib
import json

import pytest

from browser_assets import allowed_asset, verified_asset


def test_only_pinned_public_javascript_can_use_test_mirror():
    assert allowed_asset('https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js')
    assert not allowed_asset('https://cdn.jsdelivr.net/npm/marked@latest/lib/marked.umd.js')
    assert not allowed_asset('https://cdn.jsdelivr.net.evil.test/npm/marked@15.0.12/lib/marked.umd.js')
    assert not allowed_asset('http://cdn.jsdelivr.net/npm/marked@15.0.12/lib/marked.umd.js')
    assert not allowed_asset('http://127.0.0.1:8080/ocr')


def test_modified_cached_asset_is_rejected(tmp_path):
    url = 'https://cdn.jsdelivr.net/npm/marked@15.0.12/lib/marked.umd.js'
    key = hashlib.sha256(url.encode()).hexdigest()
    (tmp_path/(key+'.js')).write_bytes(b'changed')
    (tmp_path/(key+'.json')).write_text(json.dumps({'url': url, 'tls_verified': True,
                                                  'sha256': hashlib.sha256(b'original').hexdigest()}))
    with pytest.raises(ValueError, match='integrity mismatch'):
        verified_asset(url, tmp_path)
