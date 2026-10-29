"""Native permission boundary contracts; Android device testing is separate.

The repository's Android compiler/device are not available in Python CI.
These checks guard the production grant surface and callback lifecycle while
the browser voice tests exercise capture/cancellation and ASR separately.
"""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
JAVA = (ROOT / 'android/app/src/main/java/app/dmate/client/MainActivity.java').read_text()
ANDROID = '{http://schemas.android.com/apk/res/android}'


def method(signature):
    start = JAVA.index(signature)
    opening = JAVA.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (JAVA[end] == '{') - (JAVA[end] == '}')
        end += 1
    return JAVA[opening + 1:end - 1]



class AndroidVoicePermissionTest(unittest.TestCase):
    def test_only_microphone_permission_added_and_hardware_remains_optional(self):
        manifest = ET.parse(ROOT / 'android/app/src/main/AndroidManifest.xml').getroot()
        names = {row.get(ANDROID + 'name') for row in manifest.findall('uses-permission')}
        assert 'android.permission.RECORD_AUDIO' in names
        assert 'android.permission.CAMERA' not in names
        assert 'android.permission.ACCESS_FINE_LOCATION' not in names
        microphone = [row for row in manifest.findall('uses-feature')
                      if row.get(ANDROID + 'name') == 'android.hardware.microphone']
        assert len(microphone) == 1 and microphone[0].get(ANDROID + 'required') == 'false'


    def test_grant_surface_is_exact_audio_not_provider_resource_list(self):
        grant = method('private void grantMicrophone(')
        assert 'request.grant(new String[] { PermissionRequest.RESOURCE_AUDIO_CAPTURE })' in grant
        assert 'request.grant(request.getResources())' not in JAVA
        assert 'checkSelfPermission(Manifest.permission.RECORD_AUDIO)' in grant
        assert grant.index('isTrustedMicrophoneRequest(request)') < grant.index('request.grant(')
        request = method('private void requestMicrophone(')
        assert 'resources.length != 1' in request
        assert '!PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resources[0])' in request
        assert 'denyMicrophone(request)' in request
        assert 'requestPermissions(new String[] { Manifest.permission.RECORD_AUDIO }, MICROPHONE_PERMISSION_REQUEST)' in request


    def test_origin_boundary_checks_current_page_https_host_and_same_port(self):
        origin = method('private boolean isTrustedMicrophoneOrigin(')
        assert '"https".equalsIgnoreCase(origin.getScheme())' in origin
        assert 'HOME_HOST.equalsIgnoreCase(origin.getHost())' in origin
        assert 'origin.getUserInfo() != null' in origin
        assert 'Uri.parse(HOME_URL)' in origin
        assert 'actualPort == expectedPort' in origin
        checked = method('private boolean isTrustedMicrophoneRequest(')
        assert '!isFinishing() && !isDestroyed()' in checked
        assert 'isTrustedMicrophoneOrigin(request.getOrigin())' in checked
        assert 'isTrustedMicrophoneOrigin(Uri.parse(webView.getUrl()))' in checked


    def test_android_permission_response_rechecks_request_and_retains_gallery_branch(self):
        result = method('public void onRequestPermissionsResult(')
        assert result.index('MICROPHONE_PERMISSION_REQUEST') < result.index('LEGACY_SAVE_PERMISSION_REQUEST')
        microphone = result.split('if (requestCode != LEGACY_SAVE_PERMISSION_REQUEST)', 1)[0]
        assert 'microphonePermissionInFlight = false' in microphone
        assert 'PermissionRequest request = pendingMicrophoneRequest' in microphone
        assert 'pendingMicrophoneRequest = null' in microphone
        assert 'if (request == null) return' in microphone
        assert 'permissions.length == 1 && Manifest.permission.RECORD_AUDIO.equals(permissions[0])' in microphone
        assert 'grantResults.length == 1 && grantResults[0] == PackageManager.PERMISSION_GRANTED' in microphone
        assert 'grantMicrophone(request)' in microphone
        assert 'denyMicrophone(request)' in microphone
        assert 'saveImageAsync(save)' in result


    def test_cancel_navigation_and_destroy_cannot_attach_late_grant_to_new_request(self):
        cancelled = method('public void onPermissionRequestCanceled(')
        assert 'if (pendingMicrophoneRequest == request) pendingMicrophoneRequest = null' in cancelled
        for signature in ('public void onPageStarted(', 'private boolean handleNavigation(', 'protected void onDestroy('):
            assert 'cancelPendingMicrophoneRequest()' in method(signature)
        clear = method('private void cancelPendingMicrophoneRequest(')
        assert clear.index('pendingMicrophoneRequest = null') < clear.index('denyMicrophone(request)')
        assert 'microphonePermissionInFlight = false' not in clear
        request = method('private void requestMicrophone(')
        assert 'pendingMicrophoneRequest != null' in request and 'microphonePermissionInFlight' in request
        assert request.index('microphonePermissionInFlight = true') < request.index('requestPermissions(')
