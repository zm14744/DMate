"""Test-only pinned CDN mirror using the execution runtime's existing TLS trust.

Does not modify Chromium trust, disable certificate checks, or intercept /ocr.
The cache contains public JS dependencies only, never user images or responses.
"""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import requests

PACKAGES = ('mathjax@3.2.2/', 'marked@15.0.12/', 'dompurify@3.2.6/',
            'html2canvas@1.4.1/', 'jspdf@2.5.2/')
MAX_BYTES = 8 * 1024 * 1024


def allowed_asset(url):
    value = urlsplit(url)
    return (value.scheme == 'https' and value.netloc == 'cdn.jsdelivr.net'
            and any(value.path.startswith('/npm/' + p) for p in PACKAGES)
            and value.path.endswith('.js') and not value.query)


def verified_asset(url, folder):
    if not allowed_asset(url):
        raise ValueError('Unpinned CDN asset')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()
    payload, metadata = folder / (key + '.js'), folder / (key + '.json')
    if payload.exists() and metadata.exists():
        data, record = payload.read_bytes(), json.loads(metadata.read_text())
        if (record.get('url') != url or record.get('tls_verified') is not True
                or record.get('sha256') != hashlib.sha256(data).hexdigest()):
            raise ValueError('CDN cache integrity mismatch')
        return data, record
    # Default Requests verification is kept enabled, including the platform's
    # existing REQUESTS_CA_BUNDLE. No persistent trust settings are changed.
    with requests.get(url, timeout=(8, 30), stream=True) as response:
        response.raise_for_status()
        if not allowed_asset(response.url):
            raise ValueError('Unpinned CDN redirect')
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('CDN asset budget exceeded')
            chunks.append(chunk)
        data = b''.join(chunks)
        content_type = response.headers.get('Content-Type', '')
        if 'javascript' not in content_type:
            raise ValueError('CDN returned non-JavaScript content')
    record = {'url': url, 'tls_verified': True,
              'sha256': hashlib.sha256(data).hexdigest(), 'content_type': content_type}
    payload.write_bytes(data)
    metadata.write_text(json.dumps(record, indent=2))
    return data, record


def install_verified_cdn_routes(context, folder):
    def serve(route):
        if not allowed_asset(route.request.url):
            route.continue_()
            return
        data, metadata = verified_asset(route.request.url, folder)
        route.fulfill(status=200, body=data, content_type=metadata['content_type'],
                      headers={'Access-Control-Allow-Origin': '*'})
    context.route('https://cdn.jsdelivr.net/npm/**', serve)
