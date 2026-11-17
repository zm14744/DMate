"""Exercise the Android launch policy and both native document-start scripts.

This uses the pure Java lifetime helper, without an emulator, and executes the
actual emitted scripts in Node contexts for permitted/foreign frame origins.
The platform builds still compile MainActivity/Tauri against their own SDKs.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA = shutil.which('java') or next((str(path) for path in [
    Path('/usr/lib/jvm/default-java/bin/java'),
    Path('/usr/lib/jvm/java-21-openjdk-amd64/bin/java'),
] if path.is_file()), None)
NODE = shutil.which('node')


@unittest.skipUnless(JAVA and NODE, 'Java and Node are required for native guest-lifetime checks')
class NativeGuestSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='dmate-native-guest-')
        cls.addClassCleanup(cls.directory.cleanup)
        helper = ROOT / 'android/app/src/main/java/app/dmate/client/GuestSession.java'
        test = ROOT / 'scripts/native/GuestSessionTest.java'
        subprocess.run([JAVA, '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-d', cls.directory.name,
                        str(helper), str(test)], check=True, capture_output=True, text=True)

    @classmethod
    def invoke(cls, *args):
        return subprocess.check_output([JAVA, '-cp', cls.directory.name,
                                        'app.dmate.client.GuestSessionTest', *args], text=True)

    def test_android_window_and_process_lifetimes(self):
        self.assertIn('PASS Android guest launch', self.invoke())

    def test_native_scripts_only_mark_the_trusted_top_level_document(self):
        marker = 'test-launch-token-1234567890'
        desktop = (ROOT / 'desktop/src-tauri/src/guest-session.js').read_text().replace(
            '__DMATE_GUEST_SESSION_TOKEN__', marker)
        code = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const scripts = JSON.parse(require('node:fs').readFileSync(0,'utf8'));
for (const [name, script] of Object.entries(scripts)) {
  for (const [href, top, allowed] of [
    ['https://dmate.zeabur.app/',true,true],
    ['https://dmate.zeabur.app/offline',true,true],
    ['https://dmate.zeabur.app:443/',true,true],
    ['https://dmate.zeabur.app/',false,false],
    ['https://foreign.example/',true,false],
    ['http://dmate.zeabur.app/',true,false],
    ['https://dmate.zeabur.app:444/',true,false],
    ['https://other.dmate.zeabur.app/',true,false],
    ['https://user@dmate.zeabur.app/',true,false],
  ]) {
    const window = {}; window.top = top ? window : {};
    const forbidden = new Proxy({}, {get() { throw new Error('Native markers must not read or erase browser storage'); }});
    const context = vm.createContext({window, location:{href}, URL, sessionStorage:forbidden, localStorage:forbidden});
    vm.runInContext(script, context);
    assert.equal(window.__DMATE_NATIVE_GUEST_SESSION__, allowed ? 'test-launch-token-1234567890' : undefined, name+' '+href);
    if (allowed) {
      vm.runInContext(script, context);
      assert.equal(window.__DMATE_NATIVE_GUEST_SESSION__, 'test-launch-token-1234567890', name+' marker survives page reinjection');
    }
  }
}
console.log('PASS native origin/frame guards and reload-stable markers without storage mutation');
'''
        result = subprocess.run([NODE, '-e', code], input=json.dumps({'android': self.invoke('script'), 'desktop': desktop}),
                                check=True, capture_output=True, text=True)
        self.assertIn('PASS native origin/frame guards', result.stdout)


if __name__ == '__main__':
    unittest.main()
