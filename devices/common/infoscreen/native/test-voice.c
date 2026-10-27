/* Real SCO lease/cancellation code, with only the peer and pactl substituted. */
#define main production_voice_main
#include "voice.c"
#undef main
#include <assert.h>

static bool expired;
static gboolean expire(gpointer data) {
    (void)data;
    expired = true;
    return G_SOURCE_REMOVE;
}
static gboolean cancel_lease(gpointer data) {
    bt_release(data);
    return G_SOURCE_REMOVE;
}
static void pending(App *a) {
    guint timer = g_timeout_add_seconds(6, expire, NULL);
    expired = false;
    while (a->bt_working && !expired)
        g_main_context_iteration(NULL, TRUE);
    assert(!expired);
    g_source_remove(timer);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    if (!strcmp(argv[1], "command-timeout")) {
        const char *args[] = {"e5-test-slow-command", NULL};
        GError *error = NULL;
        int rc = 0;
        double started = monotime();
        char *out = command(args, 1, NULL, &rc, &error);
        bool bounded = error && rc == -1 && monotime() - started < 3;
        g_free(out);
        g_clear_error(&error);
        if (!bounded)
            g_printerr("Command timeout depended on an external main loop\n");
        return bounded ? 0 : 3;
    }
    if (!strcmp(argv[1], "config") || !strcmp(argv[1], "config-error")) {
        GError *error = NULL;
        Json *settings = config(&error);
        if (!strcmp(argv[1], "config-error")) {
            assert(!settings && error);
            g_clear_error(&error);
        } else {
            assert(settings && !error);
            assert(jint(settings, "volume", -1) == 4);
            assert(!jbool(settings, "sound", true) && !jbool(settings, "vibrate", true));
            assert(!jbool(settings, "screen", true));
            assert(!strcmp(jstr(settings, "tone", ""), "beep"));
            json_object_put(settings);
        }
        return 0;
    }
    App a = {0};
    if (!strcmp(argv[1], "retry")) {
        a.calls = json_object_new_array();
        a.hardware_ready = a.valid = true;
        schedule_audio_retry(&a, true);
        assert(!a.retry);
        json_object_array_add(a.calls, json_tokener_parse("{\"id\":\"1\",\"state\":\"active\"}"));
        schedule_audio_retry(&a, false);
        assert(!a.retry);
        a.valid = false;
        schedule_audio_retry(&a, true);
        assert(!a.retry);
        a.valid = true;
        schedule_audio_retry(&a, true);
        assert(a.retry);
        guint scheduled = a.retry;
        schedule_audio_retry(&a, true);
        assert(a.retry == scheduled);
        /* Loss of trustworthy call state suppresses the queued retry. */
        a.valid = false;
        guint timer = g_timeout_add_seconds(3, expire, NULL);
        expired = false;
        while (a.retry && !expired)
            g_main_context_iteration(NULL, TRUE);
        assert(!expired && !a.working);
        g_source_remove(timer);
        json_object_put(a.calls);
        return 0;
    }
    a.desired_key = g_strdup("test-route");
    bt_acquire(&a);
    if (!strcmp(argv[1], "cancel"))
        g_timeout_add(80, cancel_lease, &a);
    pending(&a);
    if (!strcmp(argv[1], "ok") || !strcmp(argv[1], "lost") || !strcmp(argv[1], "pcm-failed")) {
        assert(a.lease && a.lease->rate == 16000);
        if (!strcmp(argv[1], "pcm-failed")) {
            a.closing = true;
            a.working = true;
            Json *result = json_tokener_parse("{\"state\":{\"available\":true,\"active\":false,"
                                              "\"error\":\"injected PCM failure\"}}");
            GTask *task = g_task_new(NULL, NULL, NULL, NULL);
            g_task_return_pointer(task, result, json_free);
            audio_done(NULL, G_ASYNC_RESULT(task), &a);
            g_object_unref(task);
            pending(&a);
            assert(!a.lease && a.bt_retry_after_pcm && a.failed_key);
            json_object_put(a.status);
        } else if (!strcmp(argv[1], "lost")) {
            guint timer = g_timeout_add_seconds(5, expire, NULL);
            expired = false;
            while (a.lease && !expired)
                g_main_context_iteration(NULL, TRUE);
            assert(!expired && a.route_error && a.failed_key);
            g_source_remove(timer);
            pending(&a);
        } else {
            bt_release(&a);
            pending(&a);
        }
    } else {
        assert(!a.lease);
        if (!strcmp(argv[1], "reject"))
            assert(a.route_error && a.failed_key);
    }
    g_free(a.desired_key);
    g_free(a.failed_key);
    g_free(a.route_error);
    puts("SCO lease and owned A2DP cleanup passed");
    return 0;
}
