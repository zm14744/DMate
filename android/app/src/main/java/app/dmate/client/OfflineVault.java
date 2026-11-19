package app.dmate.client;

import java.security.GeneralSecurityException;
import java.util.Arrays;
import java.util.Base64;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import javax.crypto.BadPaddingException;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** UI-independent, bounded protocol for the native offline-vault provider. */
final class OfflineVault {
    static final int MAX_PLAINTEXT_BYTES = 16 * 1024 * 1024;
    static final int MAX_AAD_BYTES = 4096;
    static final int MAX_MESSAGE_CHARS = 4 * ((MAX_PLAINTEXT_BYTES + 16 + 2) / 3)
        + 4 * ((MAX_AAD_BYTES + 2) / 3) + 1024;
    private static final int TAG_BYTES = 16;
    private static final int IV_BYTES = 12;

    interface Keys {
        Map<String, Object> capabilities() throws Failure;
        Map<String, Object> create(String keyId) throws Failure;
        SecretKey get(String keyId) throws Failure;
        void delete(String keyId) throws Failure;
    }

    static final class Failure extends Exception {
        final String code;
        Failure(String code, String message) {
            super(message);
            this.code = code;
        }
    }

    private final Keys keys;

    OfflineVault(Keys keys) { this.keys = keys; }

    static Failure invalid() {
        return new Failure("INVALID_REQUEST", "Invalid offline vault request.");
    }

    static Failure unavailable() {
        return new Failure("KEYSTORE_UNAVAILABLE", "The system key store is unavailable.");
    }

    static String requestId(Map<String, Object> request) throws Failure {
        String id = string(request, "id", 80);
        if (id.isEmpty()) throw invalid();
        for (int i = 0; i < id.length(); i++) {
            char c = id.charAt(i);
            if (c < 0x20 || c > 0x7e) throw invalid();
        }
        return id;
    }

    static Map<String, Object> result(Object... entries) {
        Map<String, Object> value = new LinkedHashMap<>();
        for (int i = 0; i < entries.length; i += 2) value.put((String) entries[i], entries[i + 1]);
        return value;
    }

    Map<String, Object> execute(Map<String, Object> request) throws Failure {
        requestId(request);
        String operation = string(request, "op", 20);
        if ("capabilities".equals(operation)) {
            fields(request, "id", "op");
            return keys.capabilities();
        }
        String keyId = string(request, "keyId", 32);
        if (!keyId.matches("[0-9a-f]{32}")) throw invalid();
        switch (operation) {
            case "create":
                fields(request, "id", "op", "keyId");
                return keys.create(keyId);
            case "delete":
                fields(request, "id", "op", "keyId");
                keys.delete(keyId);
                return result();
            case "encrypt":
                fields(request, "id", "op", "keyId", "plaintext", "aad");
                return encrypt(keyId, request);
            case "decrypt":
                fields(request, "id", "op", "keyId", "ciphertext", "aad", "iv");
                return decrypt(keyId, request);
            default:
                throw invalid();
        }
    }

    private Map<String, Object> encrypt(String keyId, Map<String, Object> request) throws Failure {
        byte[] plaintext = decode(request, "plaintext", MAX_PLAINTEXT_BYTES);
        byte[] aad = null;
        try {
            aad = decode(request, "aad", MAX_AAD_BYTES);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            // AndroidKeyStore generates the IV. Supplying an IV at encryption
            // time is intentionally prohibited by the key's IND-CPA policy.
            cipher.init(Cipher.ENCRYPT_MODE, keys.get(keyId));
            cipher.updateAAD(aad);
            byte[] ciphertext = cipher.doFinal(plaintext);
            byte[] iv = cipher.getIV();
            if (iv == null || iv.length != IV_BYTES || ciphertext.length != plaintext.length + TAG_BYTES) {
                throw unavailable();
            }
            return result("iv", Base64.getEncoder().encodeToString(iv),
                "ciphertext", Base64.getEncoder().encodeToString(ciphertext));
        } catch (GeneralSecurityException | IllegalArgumentException error) {
            throw unavailable();
        } finally {
            Arrays.fill(plaintext, (byte) 0);
            if (aad != null) Arrays.fill(aad, (byte) 0);
        }
    }

    private Map<String, Object> decrypt(String keyId, Map<String, Object> request) throws Failure {
        byte[] ciphertext = decode(request, "ciphertext", MAX_PLAINTEXT_BYTES + TAG_BYTES);
        if (ciphertext.length < TAG_BYTES) throw invalid();
        byte[] aad = decode(request, "aad", MAX_AAD_BYTES);
        byte[] iv = decode(request, "iv", IV_BYTES);
        if (iv.length != IV_BYTES) throw invalid();
        byte[] plaintext = null;
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, keys.get(keyId), new GCMParameterSpec(128, iv));
            cipher.updateAAD(aad);
            plaintext = cipher.doFinal(ciphertext);
            return result("plaintext", Base64.getEncoder().encodeToString(plaintext));
        } catch (BadPaddingException error) {
            throw new Failure("AUTHENTICATION_FAILED", "The encrypted data could not be authenticated.");
        } catch (GeneralSecurityException | IllegalArgumentException error) {
            throw unavailable();
        } finally {
            if (plaintext != null) Arrays.fill(plaintext, (byte) 0);
            Arrays.fill(aad, (byte) 0);
        }
    }

    private static String string(Map<String, Object> request, String name, int maximum) throws Failure {
        Object value = request.get(name);
        if (!(value instanceof String) || ((String) value).length() > maximum) throw invalid();
        return (String) value;
    }

    private static void fields(Map<String, Object> request, String... names) throws Failure {
        Set<String> expected = new HashSet<>(Arrays.asList(names));
        if (!request.keySet().equals(expected)) throw invalid();
    }

    private static byte[] decode(Map<String, Object> request, String name, int maximum) throws Failure {
        String encoded = string(request, name, 4 * ((maximum + 2) / 3));
        try {
            byte[] bytes = Base64.getDecoder().decode(encoded);
            if (bytes.length > maximum || !Base64.getEncoder().encodeToString(bytes).equals(encoded)) {
                Arrays.fill(bytes, (byte) 0);
                throw invalid();
            }
            return bytes;
        } catch (IllegalArgumentException error) {
            throw invalid();
        }
    }
}
