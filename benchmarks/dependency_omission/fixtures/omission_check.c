#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define VALUE_SIZE 512

struct spec {
    char mode[VALUE_SIZE];
    char expected[VALUE_SIZE];
    char target[VALUE_SIZE];
    char pointer[VALUE_SIZE];
};

static void mark(const char *path) {
    printf("CLICK_BENCH_DEP=%s\n", path);
    fflush(stdout);
}

static int read_text(const char *path, char *output, size_t size) {
    FILE *handle;
    size_t count;
    mark(path);
    handle = fopen(path, "rb");
    if (handle == NULL) {
        return 0;
    }
    count = fread(output, 1, size - 1, handle);
    if (ferror(handle)) {
        fclose(handle);
        return 0;
    }
    output[count] = '\0';
    fclose(handle);
    return 1;
}

static void set_value(struct spec *value, const char *key, const char *content) {
    char *destination = NULL;
    if (strcmp(key, "mode") == 0) destination = value->mode;
    else if (strcmp(key, "expected") == 0) destination = value->expected;
    else if (strcmp(key, "target") == 0) destination = value->target;
    else if (strcmp(key, "pointer") == 0) destination = value->pointer;
    if (destination != NULL) {
        snprintf(destination, VALUE_SIZE, "%s", content);
    }
}

static int parse_spec(struct spec *value) {
    char content[2048];
    char *line;
    memset(value, 0, sizeof(*value));
    if (!read_text("case.spec", content, sizeof(content))) {
        return 0;
    }
    line = strtok(content, "\r\n");
    while (line != NULL) {
        char *separator = strchr(line, '=');
        if (separator != NULL) {
            *separator = '\0';
            set_value(value, line, separator + 1);
        }
        line = strtok(NULL, "\r\n");
    }
    return 1;
}

static int directory_is_expected(const char *path) {
    DIR *directory;
    struct dirent *entry;
    int count = 0;
    int expected = 0;
    char normalized[VALUE_SIZE];
    size_t length;
    mark(path);
    snprintf(normalized, sizeof(normalized), "%s", path);
    length = strlen(normalized);
    if (length > 0 && normalized[length - 1] == '/') normalized[length - 1] = '\0';
    directory = opendir(normalized);
    if (directory == NULL) return 0;
    while ((entry = readdir(directory)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) continue;
        count += 1;
        if (strcmp(entry->d_name, "expected.txt") == 0) expected += 1;
    }
    closedir(directory);
    return count == 1 && expected == 1;
}

static int child(const char *path, const char *expected) {
    char content[VALUE_SIZE];
    return read_text(path, content, sizeof(content)) && strcmp(content, expected) == 0 ? 0 : 1;
}

static int run_parent(const char *executable) {
    struct spec value;
    char content[VALUE_SIZE];
    if (!parse_spec(&value)) return 1;
    if (!read_text("stable.txt", content, sizeof(content)) || strcmp(content, "stable-control") != 0) return 1;
    if (strcmp(value.mode, "direct-file") == 0) {
        return child(value.target, value.expected);
    }
    if (strcmp(value.mode, "nested-pointer") == 0) {
        char target[VALUE_SIZE];
        if (!read_text(value.pointer, target, sizeof(target))) return 1;
        return child(target, value.expected);
    }
    if (strcmp(value.mode, "directory-membership") == 0) {
        return directory_is_expected(value.target) ? 0 : 1;
    }
    if (strcmp(value.mode, "missing-file") == 0) {
        FILE *handle;
        mark(value.target);
        handle = fopen(value.target, "rb");
        if (handle == NULL) return 0;
        fclose(handle);
        return 1;
    }
    if (strcmp(value.mode, "child-process") == 0) {
        char command[2048];
        int status;
        snprintf(command, sizeof(command), "\"%s\" --child \"%s\" \"%s\"", executable, value.target, value.expected);
        status = system(command);
        printf("CLICK_BENCH_CHILD=1\n");
        return status == 0 ? 0 : 1;
    }
    return 1;
}

int main(int argc, char **argv) {
    if (argc == 4 && strcmp(argv[1], "--child") == 0) {
        return child(argv[2], argv[3]);
    }
    return run_parent(argv[0]);
}
