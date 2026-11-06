"""Generate the iOS/iPadOS DMate Home Screen Web Clip profile."""

from pathlib import Path
import plistlib
import uuid


def build_ios_webclip_profile(icon_path):
    """Return an Apple configuration profile containing one full-screen Web Clip."""
    icon_path = Path(icon_path)
    icon_png = icon_path.read_bytes()
    if not icon_png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("DMate Web Clip icon must be a PNG file")

    namespace = uuid.NAMESPACE_DNS
    profile = {
        "PayloadType": "Configuration",
        "PayloadVersion": 1,
        "PayloadIdentifier": "app.dmate.zeabur.webclip.profile",
        "PayloadUUID": str(uuid.uuid5(
            namespace, "dmate.zeabur.app/webclip/profile/fullscreen-v2"
        )).upper(),
        "PayloadDisplayName": "DMate",
        "PayloadDescription": (
            "在 iPhone 或 iPad 主屏幕添加 DMate 全屏网页入口。"
            "此配置仅添加网页图标，不包含设备管理、证书、VPN 或限制。"
            "\n\nAdd DMate — Discrete Mathematics Tutor to the iPhone or iPad Home Screen "
            "as a full-screen web app. This profile only adds a web shortcut; "
            "it contains no device management, certificates, VPN settings or restrictions."
        ),
        "PayloadOrganization": "DMate",
        "PayloadContent": [
            {
                "PayloadType": "com.apple.webClip.managed",
                "PayloadVersion": 1,
                "PayloadIdentifier": "app.dmate.zeabur.webclip",
                "PayloadUUID": str(uuid.uuid5(
                    namespace, "dmate.zeabur.app/webclip"
                )).upper(),
                "Label": "DMate",
                "URL": "https://dmate.zeabur.app/",
                "Icon": icon_png,
                "FullScreen": True,
                "IsRemovable": True,
                "Precomposed": True,
            }
        ],
    }
    return plistlib.dumps(profile, fmt=plistlib.FMT_XML, sort_keys=False)
