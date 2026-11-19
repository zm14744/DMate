package app.dmate.client;

import java.util.LinkedHashSet;
import java.util.Locale;

/** File metadata shared by the system picker and the ZIP save bridge. */
final class BackupFiles {
    static final int MAX_ZIP_BYTES = 100 * 1024 * 1024;

    private BackupFiles() {}

    static boolean isZip(byte[] bytes) {
        return bytes != null && bytes.length >= 22 && bytes.length <= MAX_ZIP_BYTES
            && bytes[0] == 'P' && bytes[1] == 'K'
            && ((bytes[2] == 3 && bytes[3] == 4) || (bytes[2] == 5 && bytes[3] == 6));
    }

    static String zipFilename(String supplied) {
        String name = (supplied == null ? "" : supplied.trim())
            .replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_");
        if (name.toLowerCase(Locale.ROOT).endsWith(".zip")) name = name.substring(0, name.length() - 4);
        if (name.length() > 120) name = name.substring(0, 120);
        if (name.isEmpty() || name.matches("[. ]+")) name = "DMate";
        return name + ".zip";
    }

    static String[] acceptMimeTypes(String[] accepted) {
        LinkedHashSet<String> types = new LinkedHashSet<>();
        if (accepted != null) for (String entry : accepted) {
            if (entry == null) continue;
            for (String item : entry.split(",")) {
                String type = item.trim().toLowerCase(Locale.ROOT);
                if (type.isEmpty()) continue;
                switch (type) {
                    case ".zip": type = "application/zip"; break;
                    case ".png": type = "image/png"; break;
                    case ".jpg": case ".jpeg": type = "image/jpeg"; break;
                    case ".gif": type = "image/gif"; break;
                    case ".webp": type = "image/webp"; break;
                    case ".svg": type = "image/svg+xml"; break;
                    case ".bmp": type = "image/bmp"; break;
                    case ".heic": type = "image/heic"; break;
                    case ".heif": type = "image/heif"; break;
                    case ".avif": type = "image/avif"; break;
                    case ".pdf": type = "application/pdf"; break;
                    case ".json": type = "application/json"; break;
                    case ".txt": type = "text/plain"; break;
                    default:
                        if (!type.matches("(?:[a-z0-9!#$&^_.+-]+|\\*)/(?:[a-z0-9!#$&^_.+-]+|\\*)")) type = "*/*";
                }
                types.add(type);
            }
        }
        if (types.isEmpty() || types.contains("*/*")) return new String[] {"*/*"};
        return types.toArray(new String[0]);
    }

    static boolean imagesOnly(String[] types) {
        if (types == null || types.length == 0) return false;
        for (String type : types) if (!type.startsWith("image/")) return false;
        return true;
    }
}
