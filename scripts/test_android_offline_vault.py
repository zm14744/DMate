"""Run the production Android vault protocol/GCM core on the JDK.

These tests use a memory key provider to exercise the real parser, origin policy,
AES-GCM and error/size handling. AndroidKeyStore hardware and WebView lifecycle
still require the Android build and a device/emulator; this is not such a test.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA = shutil.which("java")
SOURCE = ROOT / "android/app/src/main/java/app/dmate/client"

JAVA_TEST = r'''
package app.dmate.client;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import java.util.HashSet;
import javax.crypto.SecretKey;
import javax.crypto.KeyGenerator;
import javax.crypto.spec.SecretKeySpec;

public final class OfflineVaultTest {
    private static final String FIRST = "0123456789abcdef0123456789abcdef";
    private static final String SECOND = "abcdef0123456789abcdef0123456789";
    private static int checks;

    private static final class MemoryKeys implements OfflineVault.Keys {
        final Map<String, SecretKey> data = new HashMap<>();
        int creates;
        public Map<String, Object> capabilities() {
            return OfflineVault.result("version", 1, "provider", "test", "protection", "memory");
        }
        public Map<String, Object> create(String id) throws OfflineVault.Failure {
            if (data.containsKey(id)) throw new OfflineVault.Failure("KEY_EXISTS", "exists");
            try {
                KeyGenerator generator = KeyGenerator.getInstance("AES"); generator.init(256);
                data.put(id, generator.generateKey()); creates++;
                return OfflineVault.result("keyId", id, "hardwareBacked", false);
            } catch (Exception error) { throw OfflineVault.unavailable(); }
        }
        public SecretKey get(String id) throws OfflineVault.Failure {
            if (!data.containsKey(id)) throw new OfflineVault.Failure("KEY_MISSING", "missing");
            return data.get(id);
        }
        public void delete(String id) { data.remove(id); }
    }

    interface Check { void run() throws Exception; }
    static void equal(Object actual, Object expected) {
        checks++;
        if (!java.util.Objects.equals(actual, expected)) throw new AssertionError(actual + " != " + expected);
    }
    static void failure(String code, Check action) throws Exception {
        try { action.run(); throw new AssertionError("Expected " + code); }
        catch (OfflineVault.Failure error) { equal(error.code, code); }
    }
    static String b64(byte[] bytes) { return Base64.getEncoder().encodeToString(bytes); }
    static String b64(String text) { return b64(text.getBytes(StandardCharsets.UTF_8)); }
    static byte[] unhex(String hex) {
        byte[] bytes = new byte[hex.length() / 2];
        for (int i = 0; i < bytes.length; i++) bytes[i] = (byte) Integer.parseInt(hex.substring(i*2, i*2+2), 16);
        return bytes;
    }
    static Map<String,Object> request(String op, String key, Object... fields) {
        Map<String,Object> value = OfflineVault.result("id", "test-request", "op", op, "keyId", key);
        for (int i = 0; i < fields.length; i += 2) value.put((String) fields[i], fields[i+1]);
        return value;
    }
    static Map<String,Object> encrypt(OfflineVault vault, String value, String aad) throws Exception {
        return vault.execute(request("encrypt", FIRST, "plaintext", value, "aad", aad));
    }
    static Map<String,Object> decryptRequest(Map<String,Object> encrypted, String key, String aad) {
        return request("decrypt", key, "iv", encrypted.get("iv"), "ciphertext", encrypted.get("ciphertext"), "aad", aad);
    }

    static void crypto() throws Exception {
        MemoryKeys keys = new MemoryKeys(); OfflineVault vault = new OfflineVault(keys);
        vault.execute(request("create", FIRST));
        String value = b64("集合、图论、\u0000binary\nprivate note"), aad = b64("vault/store/record/version");
        Map<String,Object> encrypted = encrypt(vault, value, aad);
        equal(vault.execute(decryptRequest(encrypted, FIRST, aad)).get("plaintext"), value);
        equal(Base64.getDecoder().decode((String) encrypted.get("iv")).length, 12);
        equal(Base64.getDecoder().decode((String) encrypted.get("ciphertext")).length,
            Base64.getDecoder().decode(value).length + 16);
        HashSet<Object> nonces = new HashSet<>();
        for (int i = 0; i < 100; i++) nonces.add(encrypt(vault, value, aad).get("iv"));
        equal(nonces.size(), 100);
        Map<String,Object> empty = encrypt(vault, "", "");
        equal(vault.execute(decryptRequest(empty, FIRST, "")).get("plaintext"), "");
        failure("AUTHENTICATION_FAILED", () -> vault.execute(decryptRequest(encrypted, FIRST, b64("wrong record"))));
        Map<String,Object> changed = decryptRequest(encrypted, FIRST, aad);
        byte[] cipher = Base64.getDecoder().decode((String) changed.get("ciphertext")); cipher[0] ^= 1;
        changed.put("ciphertext", b64(cipher));
        failure("AUTHENTICATION_FAILED", () -> vault.execute(changed));
        Map<String,Object> changedIv = decryptRequest(encrypted, FIRST, aad);
        byte[] iv = Base64.getDecoder().decode((String) changedIv.get("iv")); iv[11] ^= 1;
        changedIv.put("iv", b64(iv));
        failure("AUTHENTICATION_FAILED", () -> vault.execute(changedIv));
        failure("KEY_EXISTS", () -> vault.execute(request("create", FIRST)));
        equal(vault.execute(decryptRequest(encrypted, FIRST, aad)).get("plaintext"), value);
        failure("KEY_MISSING", () -> vault.execute(decryptRequest(encrypted, SECOND, aad)));
        equal(keys.creates, 1);
        vault.execute(request("create", SECOND));
        failure("AUTHENTICATION_FAILED", () -> vault.execute(decryptRequest(encrypted, SECOND, aad)));
        vault.execute(request("delete", FIRST));
        failure("KEY_MISSING", () -> vault.execute(decryptRequest(encrypted, FIRST, aad)));
        equal(keys.creates, 2);

        // Published AES-256-GCM all-zero key/IV, empty-message vector.
        keys.data.put(FIRST, new SecretKeySpec(new byte[32], "AES"));
        equal(vault.execute(request("decrypt", FIRST, "iv", b64(new byte[12]), "aad", "",
            "ciphertext", b64(unhex("530f8afbc74536b9a963b4f1c4cb738b")))).get("plaintext"), "");
    }

    static void protocol() throws Exception {
        OfflineVault vault = new OfflineVault(new MemoryKeys());
        Map<String,Object> cap = OfflineVaultProtocol.parse(" { \"id\":\"abc\", \"op\":\"capabilities\" } \n");
        equal(vault.execute(cap).get("version"), 1);
        equal(OfflineVaultProtocol.leadingId("{\"id\":\"quoted\\\"id\",\"op\":\"capabilities\"}"), "quoted\"id");
        equal(OfflineVaultProtocol.leadingId("{\"op\":\"capabilities\",\"id\":\"last\"}"), "");
        for (String invalid : new String[] {
            "{\"id\":\"a\",\"id\":\"b\",\"op\":\"capabilities\"}",
            "{\"id\":8,\"op\":\"capabilities\"}",
            "{\"id\":null,\"op\":\"capabilities\"}",
            "{\"id\":{},\"op\":\"capabilities\"}",
            "{\"id\":[],\"op\":\"capabilities\"}",
            "{'id':'a','op':'capabilities'}", "{\"id\":\"a\",}",
            "{\"id\":\"a\",\"op\":\"capabilities\"} trailing",
            "{\"id\":\"bad\\x\",\"op\":\"capabilities\"}",
            "{\"id\":\"\\u００６１\",\"op\":\"capabilities\"}",
            "{\"id\":\"bad\nline\",\"op\":\"capabilities\"}"
        }) failure("INVALID_REQUEST", () -> OfflineVaultProtocol.parse(invalid));
        for (String invalid : new String[] {
            "{\"id\":\"\",\"op\":\"capabilities\"}",
            "{\"id\":\"a\",\"op\":\"capabilities\",\"extra\":\"1\"}",
            "{\"id\":\"a\",\"op\":\"unknown\"}",
            "{\"id\":\"非ASCII\",\"op\":\"capabilities\"}",
            "{\"id\":\"a\",\"op\":\"create\",\"keyId\":\"../../other-key\"}",
            "{\"id\":\"a\",\"op\":\"create\",\"keyId\":\"0123456789ABCDEF0123456789ABCDEF\"}"
        }) failure("INVALID_REQUEST", () -> vault.execute(OfflineVaultProtocol.parse(invalid)));
        vault.execute(request("create", FIRST));
        for (String invalid : new String[] {"Zg", "Zh==", " Zg==", "Zg==\n", "Zg--", "!@#$"}) {
            failure("INVALID_REQUEST", () -> encrypt(vault, invalid, ""));
        }
        Map<String,Object> fixedIv = request("encrypt", FIRST, "plaintext", "", "aad", "", "iv", b64(new byte[12]));
        failure("INVALID_REQUEST", () -> vault.execute(fixedIv));
        failure("INVALID_REQUEST", () -> vault.execute(request("decrypt", FIRST, "iv", b64(new byte[11]),
            "ciphertext", b64(new byte[16]), "aad", "")));
        failure("INVALID_REQUEST", () -> vault.execute(request("decrypt", FIRST, "iv", b64(new byte[12]),
            "ciphertext", b64(new byte[15]), "aad", "")));
        failure("INVALID_REQUEST", () -> encrypt(vault, "", b64(new byte[OfflineVault.MAX_AAD_BYTES + 1])));
        byte[] maximum = new byte[OfflineVault.MAX_PLAINTEXT_BYTES]; maximum[maximum.length-1] = 7;
        String encoded = b64(maximum);
        Map<String,Object> encrypted = encrypt(vault, encoded, "");
        equal(vault.execute(decryptRequest(encrypted, FIRST, "")).get("plaintext"), encoded);
        failure("INVALID_REQUEST", () -> encrypt(vault, b64(new byte[OfflineVault.MAX_PLAINTEXT_BYTES + 1]), ""));
    }

    static void origins() {
        for (String value : new String[] {
            "https://dmate.zeabur.app/offline", "https://dmate.zeabur.app:443/offline?version=1#notes",
            "https://dmate.zeabur.app/static/offline.html"
        }) equal(OfflineVaultProtocol.trustedPage(value), true);
        for (String value : new String[] {
            null, "", "http://dmate.zeabur.app/offline", "https://dmate.zeabur.app:444/offline",
            "https://user@dmate.zeabur.app/offline", "https://dmate.zeabur.app.evil.test/offline",
            "https://other.dmate.zeabur.app/offline", "https://dmate.zeabur.app/", "file:///offline",
            "https://dmate.zeabur.app/offline/", "https://dmate.zeabur.app/static/../offline",
            "https://dmate.zeabur.app/off%6cine", "https://dmate.zeabur.app./offline"
        }) equal(OfflineVaultProtocol.trustedPage(value), false);
    }

    public static void main(String[] args) throws Exception {
        crypto(); protocol(); origins();
        System.out.println("PASS Android vault core: " + checks + " crypto/protocol/origin assertions");
    }
}
'''


@unittest.skipUnless(JAVA, "Java is required for the Android vault core test")
class AndroidOfflineVaultTests(unittest.TestCase):
    def test_crypto_protocol_and_origin_boundaries(self):
        with tempfile.TemporaryDirectory(prefix="dmate-android-vault-") as directory:
            test = Path(directory) / "OfflineVaultTest.java"
            test.write_text(JAVA_TEST)
            subprocess.run([
                JAVA, "-m", "jdk.compiler/com.sun.tools.javac.Main", "-source", "17", "-target", "17", "-d", directory,
                str(SOURCE / "OfflineVault.java"), str(SOURCE / "OfflineVaultProtocol.java"), str(test),
            ], check=True, capture_output=True, text=True)
            completed = subprocess.run([
                JAVA, "-Xmx512m", "-cp", directory, "app.dmate.client.OfflineVaultTest",
            ], check=True, capture_output=True, text=True)
            self.assertIn("PASS Android vault core", completed.stdout)
            print(completed.stdout.strip())


if __name__ == "__main__":
    unittest.main()
