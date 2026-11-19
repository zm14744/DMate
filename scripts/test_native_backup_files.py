"""Run Android file-picker/ZIP metadata policy without requiring an emulator."""
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


@unittest.skipUnless(JAVA, 'Java is required for the Android file policy checks')
class NativeBackupFilesTests(unittest.TestCase):
    def test_zip_save_metadata_and_picker_types(self):
        with tempfile.TemporaryDirectory(prefix='dmate-backup-files-') as directory:
            helper = ROOT / 'android/app/src/main/java/app/dmate/client/BackupFiles.java'
            test = ROOT / 'scripts/native/BackupFilesTest.java'
            subprocess.run([JAVA, '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-d', directory,
                            str(helper), str(test)], check=True, capture_output=True, text=True)
            result = subprocess.run([JAVA, '-cp', directory, 'app.dmate.client.BackupFilesTest'],
                                    check=True, capture_output=True, text=True)
            self.assertIn('PASS Android ZIP', result.stdout)


if __name__ == '__main__':
    unittest.main()
