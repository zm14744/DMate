package app.dmate.client;

import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyInfo;
import android.security.keystore.KeyProperties;
import java.security.KeyStore;
import java.util.Map;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;

/** Keys never leave AndroidKeyStore; only plaintext/ciphertext cross the bridge. */
final class OfflineVaultKeystore implements OfflineVault.Keys {
    private static final String PROVIDER = "AndroidKeyStore";
    private static final String PREFIX = "app.dmate.offline-vault.v1.";
    // Activity recreation can temporarily leave two bridge instances alive.
    // Serialize create-if-absent with delete across all instances in this process.
    private static final Object KEY_LOCK = new Object();

    private KeyStore open() throws Exception {
        KeyStore store = KeyStore.getInstance(PROVIDER);
        store.load(null);
        return store;
    }

    @Override
    public Map<String, Object> capabilities() throws OfflineVault.Failure {
        try {
            open();
            return OfflineVault.result("version", 1, "provider", "android-keystore",
                "protection", "os-keystore", "hardwareBacked", null,
                "unlockedDeviceRequired", Build.VERSION.SDK_INT >= 35);
        } catch (Exception error) {
            throw OfflineVault.unavailable();
        }
    }

    @Override
    public Map<String, Object> create(String keyId) throws OfflineVault.Failure {
        synchronized (KEY_LOCK) {
            try {
                KeyStore store = open();
                String alias = PREFIX + keyId;
                if (store.containsAlias(alias)) {
                    throw new OfflineVault.Failure("KEY_EXISTS", "The offline vault key already exists.");
                }
                KeyGenParameterSpec.Builder policy = new KeyGenParameterSpec.Builder(alias,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setKeySize(256)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .setUserAuthenticationRequired(false);
                // Android's documented lock-removal/biometric bugs affect this
                // option on 12–14. On 15+, require the existing device lock to be
                // open without adding a DMate password or biometric prompt.
                if (Build.VERSION.SDK_INT >= 35) policy.setUnlockedDeviceRequired(true);
                KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, PROVIDER);
                generator.init(policy.build());
                SecretKey key = generator.generateKey();
                try {
                    KeyInfo info = (KeyInfo) SecretKeyFactory.getInstance(key.getAlgorithm(), PROVIDER)
                        .getKeySpec(key, KeyInfo.class);
                    boolean hardware;
                    if (Build.VERSION.SDK_INT >= 31) {
                        int level = info.getSecurityLevel();
                        hardware = level == KeyProperties.SECURITY_LEVEL_TRUSTED_ENVIRONMENT
                            || level == KeyProperties.SECURITY_LEVEL_STRONGBOX;
                    } else {
                        hardware = insideHardware(info);
                    }
                    return OfflineVault.result("keyId", keyId, "hardwareBacked", hardware);
                } catch (Exception error) {
                    // Creation did not complete from the caller's perspective.
                    // Never strand a key whose protection could not be queried.
                    store.deleteEntry(alias);
                    throw error;
                }
            } catch (OfflineVault.Failure error) {
                throw error;
            } catch (Exception error) {
                throw OfflineVault.unavailable();
            }
        }
    }

    @SuppressWarnings("deprecation")
    private static boolean insideHardware(KeyInfo info) { return info.isInsideSecureHardware(); }

    @Override
    public SecretKey get(String keyId) throws OfflineVault.Failure {
        synchronized (KEY_LOCK) {
            try {
                KeyStore.Entry entry = open().getEntry(PREFIX + keyId, null);
                if (entry == null) throw new OfflineVault.Failure("KEY_MISSING", "The offline vault key is missing.");
                if (!(entry instanceof KeyStore.SecretKeyEntry)) throw OfflineVault.unavailable();
                return ((KeyStore.SecretKeyEntry) entry).getSecretKey();
            } catch (OfflineVault.Failure error) {
                throw error;
            } catch (Exception error) {
                throw OfflineVault.unavailable();
            }
        }
    }

    @Override
    public void delete(String keyId) throws OfflineVault.Failure {
        synchronized (KEY_LOCK) {
            try {
                open().deleteEntry(PREFIX + keyId);
            } catch (Exception error) {
                throw OfflineVault.unavailable();
            }
        }
    }
}
