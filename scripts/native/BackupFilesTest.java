package app.dmate.client;

import java.util.Arrays;

public final class BackupFilesTest {
    private static void check(boolean result, String message) {
        if (!result) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        String[] zip = BackupFiles.acceptMimeTypes(new String[] {".zip,application/zip", "application/x-zip-compressed"});
        check(Arrays.equals(zip, new String[] {"application/zip", "application/x-zip-compressed"}), "ZIP input must not open an image-only picker");
        check(!BackupFiles.imagesOnly(zip), "ZIP chooser must use the file label");
        String[] images = BackupFiles.acceptMimeTypes(new String[] {"image/*", ".png", ".JPG"});
        check(BackupFiles.imagesOnly(images), "Existing image selection must remain supported");
        check(Arrays.equals(BackupFiles.acceptMimeTypes(new String[] {""}), new String[] {"*/*"}), "Unrestricted HTML inputs must accept files");
        check(Arrays.equals(BackupFiles.acceptMimeTypes(new String[] {".unknown"}), new String[] {"*/*"}), "Unknown extensions must not make files inaccessible");
        check(BackupFiles.zipFilename("DMate-2026.zip").equals("DMate-2026.zip"), "Keep the requested ZIP filename");
        check(!BackupFiles.zipFilename("../backup/概念.zip").contains("/"), "The save name must not contain a path");
        check(BackupFiles.zipFilename("").equals("DMate.zip"), "Supply a useful empty-name fallback");
        check(BackupFiles.zipFilename("x".repeat(200)).length() <= 124, "Bound system save dialog filenames");
        byte[] emptyZip = new byte[22]; emptyZip[0] = 'P'; emptyZip[1] = 'K'; emptyZip[2] = 5; emptyZip[3] = 6;
        check(BackupFiles.isZip(emptyZip), "An empty standard ZIP archive is valid");
        byte[] archive = emptyZip.clone(); archive[2] = 3; archive[3] = 4;
        check(BackupFiles.isZip(archive), "A regular ZIP archive is valid");
        check(!BackupFiles.isZip(new byte[] {(byte)0x89, 'P', 'N', 'G'}), "The ZIP bridge must reject PNG data");
        check(!BackupFiles.isZip(null), "Missing file bytes must be rejected");
        System.out.println("PASS Android ZIP file metadata, chooser types and image selection compatibility");
    }
}
