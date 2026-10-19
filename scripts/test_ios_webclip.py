#!/usr/bin/env python3
"""Smoke-test the public iPhone/iPad .mobileconfig WebClip response.

Run after scripts/generate_icons.py. Imports only the isolated Flask route,
so no OpenCV, model service, secrets or database connection is needed.
"""
import ast
import io
import os
import plistlib
import uuid
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
source = ast.parse((ROOT / "app.py").read_text("utf-8"))
f = next(node for node in source.body
         if isinstance(node, ast.FunctionDef)
         and node.name == "ios_ipados_webclip_profile")
f.decorator_list = []
isolated = ast.Module(body=[f], type_ignores=[])

class MockResponse:
    def __init__(self, body):
        self.data = body
        self.headers = {}

context = {
    "os": os,
    "app": type("App", (), {"static_folder": str(ROOT / "static")})(),
    "make_response": MockResponse
}
exec(compile(isolated, "ios_webclip_endpoint", "exec"), context)
response = context["ios_ipados_webclip_profile"]()
assert response.headers["Content-Type"] == "application/x-apple-aspen-config"
assert response.headers["Content-Disposition"].endswith('.mobileconfig"')
config = plistlib.loads(response.data)
assert config["PayloadType"] == "Configuration"
assert config["PayloadDisplayName"] == "DMate"
assert len(config["PayloadContent"]) == 1
webclip = config["PayloadContent"][0]
assert webclip["PayloadType"] == "com.apple.webClip.managed"
assert webclip["Label"] == "DMate"
assert webclip["URL"] == "https://dmate.zeabur.app/"
assert "FullScreen" not in webclip, "Do not promise managed-only fullscreen functionality"
assert not any(key in webclip for key in ("VPN", "Certificate", "PayloadCertificateFileName"))
Image.open(io.BytesIO(webclip["Icon"])).verify()
with Image.open(io.BytesIO(webclip["Icon"])) as icon:
    assert icon.format == "PNG"
    assert icon.size == (180, 180), f"Unexpected icon size: {icon.size}"
for payload in [config, webclip]:
    assert len(uuid.UUID(payload["PayloadUUID"]).bytes) == 16
print("PASS: iPhone/iPad .mobileconfig has one valid Web Clip, native PNG icon and correct MIME.")
