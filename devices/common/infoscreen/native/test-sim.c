#define E5_SIM_TEST
#include "sim-status.c"
#include <stdio.h>

static Json *fixture;
static char *reader(int card, const char *cmd, GError **error) {
    (void)card;
    Json *value = jget(fixture, cmd);
    if (!value || json_object_is_type(value, json_type_null)) {
        g_set_error_literal(error, domain(), 1, "fixture unavailable");
        return NULL;
    }
    return g_strdup(json_object_get_string(value));
}
int main(void) {
    (void)query;
    (void)stop;
    char line[16384];
    while (fgets(line, sizeof(line), stdin)) {
        fixture = json_tokener_parse(line);
        Json *row = collect(0, reader);
        json_object_object_del(row, "updated");
        puts(encode(row));
        json_object_put(row);
        json_object_put(fixture);
    }
    return 0;
}
