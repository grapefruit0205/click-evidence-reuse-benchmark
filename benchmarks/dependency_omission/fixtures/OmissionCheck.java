import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class OmissionCheck {
    private static void mark(String path) {
        System.out.println("CLICK_BENCH_DEP=" + path);
        System.out.flush();
    }

    private static String readText(String path) {
        mark(path);
        try {
            return Files.readString(Path.of(path.replaceFirst("/$", "")));
        } catch (IOException error) {
            return null;
        }
    }

    private static Map<String, String> parseSpec() {
        String value = readText("case.spec");
        Map<String, String> result = new HashMap<>();
        if (value == null) {
            return result;
        }
        for (String line : value.split("\\R")) {
            int separator = line.indexOf('=');
            if (separator > 0) {
                result.put(line.substring(0, separator), line.substring(separator + 1));
            }
        }
        return result;
    }

    private static int child(String path, String expected) {
        return expected.equals(readText(path)) ? 0 : 1;
    }

    private static int run() throws Exception {
        Map<String, String> spec = parseSpec();
        if (!"stable-control".equals(readText("stable.txt"))) {
            return 1;
        }
        String mode = spec.get("mode");
        String expected = spec.getOrDefault("expected", "");
        if ("direct-file".equals(mode)) {
            return expected.equals(readText(spec.get("target"))) ? 0 : 1;
        }
        if ("nested-pointer".equals(mode)) {
            String target = readText(spec.get("pointer"));
            return target != null && expected.equals(readText(target)) ? 0 : 1;
        }
        if ("directory-membership".equals(mode)) {
            String target = spec.get("target");
            mark(target);
            try (var entries = Files.list(Path.of(target.replaceFirst("/$", "")))) {
                List<String> names = entries.map(path -> path.getFileName().toString()).sorted().toList();
                return names.equals(List.of("expected.txt")) ? 0 : 1;
            } catch (IOException error) {
                return 1;
            }
        }
        if ("missing-file".equals(mode)) {
            String target = spec.get("target");
            mark(target);
            return Files.exists(Path.of(target)) ? 1 : 0;
        }
        if ("child-process".equals(mode)) {
            String java = Path.of(System.getProperty("java.home"), "bin", "java").toString();
            Process child = new ProcessBuilder(
                    java,
                    "-cp",
                    System.getProperty("java.class.path"),
                    "OmissionCheck",
                    "--child",
                    spec.get("target"),
                    expected)
                    .inheritIO()
                    .start();
            int status = child.waitFor();
            System.out.println("CLICK_BENCH_CHILD=1");
            return status;
        }
        return 1;
    }

    public static void main(String[] args) throws Exception {
        int status;
        if (args.length == 3 && "--child".equals(args[0])) {
            status = child(args[1], args[2]);
        } else {
            status = run();
        }
        if (status != 0) {
            System.exit(status);
        }
    }
}
