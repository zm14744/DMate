"""Run Android's production bundled-offline routing policy on the JDK.

This does not execute an Android WebView, ConnectivityManager callbacks or a
device keystore. APK compilation and airplane-mode checks still need the Android
SDK and a device/emulator. The emitted document-start marker is also executed
in Node VM contexts to verify origin and frame restrictions.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "android/app/src/main/java/app/dmate/client"
JAVA = shutil.which("java")
NODE = shutil.which("node")


@unittest.skipUnless(JAVA, "Java is required for Android offline-routing policy checks")
class AndroidOfflineNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="dmate-android-offline-route-")
        cls.addClassCleanup(cls.directory.cleanup)
        subprocess.run([
            JAVA, "-m", "jdk.compiler/com.sun.tools.javac.Main", "-source", "17", "-target", "17",
            "-d", cls.directory.name, str(SOURCE / "OfflineBundle.java"), str(SOURCE / "OfflineVault.java"),
            str(SOURCE / "OfflineVaultProtocol.java"), str(ROOT / "scripts/native/OfflineNavigationTest.java"),
        ], check=True, capture_output=True, text=True)

    @classmethod
    def invoke(cls, *args):
        return subprocess.check_output([
            JAVA, "-cp", cls.directory.name, "app.dmate.client.OfflineNavigationTest", *args,
        ], text=True)

    def test_bundled_routing_and_automatic_offline_policy(self):
        result = self.invoke()
        self.assertIn("PASS Android bundled offline policy", result)
        print(result.strip())

    @unittest.skipUnless(NODE, "Node is required for native document-start marker checks")
    def test_native_availability_marker_is_restricted_to_the_trusted_top_frame(self):
        code = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const script = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
for (const [href, mainFrame, allowed] of [
  ['https://dmate.zeabur.app/', true, true],
  ['https://dmate.zeabur.app/offline?native_offline=1', true, true],
  ['https://dmate.zeabur.app:443/offline', true, true],
  ['https://dmate.zeabur.app/', false, false],
  ['https://other.example/offline', true, false],
  ['https://dmate.zeabur.app.evil.test/offline', true, false],
  ['http://dmate.zeabur.app/offline', true, false],
  ['https://dmate.zeabur.app:444/offline', true, false],
  ['https://user@dmate.zeabur.app/offline', true, false],
]) {
  const window = {}; window.top = mainFrame ? window : {};
  const storage = new Proxy({}, {get() { throw Error('The availability marker must never read browser storage'); }});
  const sandbox = vm.createContext({window, location: {href}, URL, localStorage:storage, sessionStorage:storage});
  vm.runInContext(script, sandbox);
  assert.equal(window.__DMATE_NATIVE_OFFLINE_AVAILABLE__, allowed ? true : undefined, href);
  vm.runInContext(script, sandbox);
  assert.equal(window.__DMATE_NATIVE_OFFLINE_AVAILABLE__, allowed ? true : undefined, href + ' reinjection');
  if (allowed) {
    const property = Object.getOwnPropertyDescriptor(window, '__DMATE_NATIVE_OFFLINE_AVAILABLE__');
    assert.equal(property.configurable, false);
    assert.equal(property.writable, false);
  }
}
console.log('PASS Android native offline availability marker: trusted origin, top frame, stable readonly marker');
'''
        completed = subprocess.run([NODE, "-e", code], input=json.dumps(self.invoke("marker")),
                                   check=True, capture_output=True, text=True)
        self.assertIn("PASS Android native offline availability marker", completed.stdout)
        print(completed.stdout.strip())


if __name__ == "__main__":
    unittest.main()
