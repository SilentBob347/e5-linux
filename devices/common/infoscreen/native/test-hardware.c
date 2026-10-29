/* Exercise real routing code with an in-memory ALSA boundary. */
#include "voice-hardware.c"
#include <assert.h>

typedef struct {
    unsigned id;
    long values[2];
} FakeValue;
static GPtrArray *names, *writes;
static long values[256][2];
static const char *reject;
static int opened, prepared, started, closed;
static int info_alloc(Info **p) {
    *p = g_malloc0(260);
    return 0;
}
static void release(void *p) {
    g_free(p);
}
static void iface(Info *p, int x) {
    (void)p;
    (void)x;
}
static void name_set(Info *p, const char *s) {
    g_strlcpy(p, s, 256);
}
static unsigned type(Info *p) {
    return g_str_has_prefix(p, "S_VOICE_") || !strcmp(p, "Speaker Function") ||
                   !strcmp(p, "Earpiece Function") || !strcmp(p, "VBC_DL_MUTE")
               ? 3
               : 2;
}
static unsigned items(Info *p) {
    (void)p;
    return 4;
}
static void item_set(Info *p, unsigned n) {
    *((unsigned *)((char *)p + 256)) = n;
}
static const char *item_name(Info *p) {
    static const char *choices[] = {"off", "on", "disable", "enable"};
    return choices[*((unsigned *)((char *)p + 256))];
}
static unsigned enum_get(Value *v, unsigned n) {
    return (unsigned)((FakeValue *)v)->values[n];
}
static void enum_set(Value *v, unsigned n, unsigned x) {
    ((FakeValue *)v)->values[n] = x;
}
static unsigned count(Info *p) {
    (void)p;
    return 2;
}
static unsigned id(Info *p) {
    for (unsigned i = 0; i < names->len; i++)
        if (!strcmp(p, g_ptr_array_index(names, i)))
            return i;
    assert(false);
    return 0;
}
static int metadata(Ctl *p, Info *i) {
    (void)p;
    (void)i;
    return 0;
}
static int val_alloc(Value **p) {
    *p = g_new0(FakeValue, 1);
    return 0;
}
static void val_id(Value *p, unsigned n) {
    ((FakeValue *)p)->id = n;
}
static int val_read(Ctl *p, Value *v) {
    (void)p;
    FakeValue *f = v;
    memcpy(f->values, values[f->id], sizeof(f->values));
    return 0;
}
static int val_write(Ctl *p, Value *v) {
    (void)p;
    FakeValue *f = v;
    const char *name = g_ptr_array_index(names, f->id);
    if (reject && !strcmp(name, reject)) {
        reject = NULL;
        return -5;
    }
    memcpy(values[f->id], f->values, sizeof(f->values));
    g_ptr_array_add(writes, g_strdup(name));
    return 0;
}
static long val_get(Value *v, unsigned n) {
    return ((FakeValue *)v)->values[n];
}
static void val_set(Value *v, unsigned n, long x) {
    ((FakeValue *)v)->values[n] = x;
}
static const char *err(int n) {
    (void)n;
    return "injected failure";
}
static int pcm(Pcm **p, const char *name, int direction, int flags) {
    (void)name;
    (void)direction;
    (void)flags;
    *p = g_malloc0(1);
    opened++;
    return 0;
}
static int pcm_close_fake(Pcm *p) {
    closed++;
    g_free(p);
    return 0;
}
static int prepare(Pcm *p) {
    (void)p;
    prepared++;
    return 0;
}
static int start(Pcm *p) {
    (void)p;
    assert(prepared == opened);
    started++;
    return 0;
}
static long forward(Pcm *p, unsigned long n) {
    (void)p;
    return n;
}
static int any(Pcm *p, Params *v) {
    (void)p;
    (void)v;
    return 0;
}
static int parm_i(Pcm *p, Params *v, int n) {
    (void)n;
    return any(p, v);
}
static int parm_u(Pcm *p, Params *v, unsigned n) {
    return parm_i(p, v, (int)n);
}
static int rate(Pcm *p, Params *v, unsigned n, int d) {
    (void)d;
    return parm_u(p, v, n);
}
static int period(Pcm *p, Params *v, unsigned long *n, int *d) {
    (void)n;
    (void)d;
    return any(p, v);
}
static int buffer(Pcm *p, Params *v, unsigned long *n) {
    (void)n;
    return any(p, v);
}
static void fixture(VoiceHardware *h) {
    names = g_ptr_array_new_with_free_func(g_free);
    writes = g_ptr_array_new_with_free_func(g_free);
    const char *all[] = {"VBC_VOLUME", "VBC DAC1 DG Set", "VBC DAC1 DSP MDG Set", "VBC_DL_MUTE",
                         "VBC ADC2 DG Set"};
    for (unsigned i = 0; i < G_N_ELEMENTS(all); i++)
        g_ptr_array_add(names, g_strdup(all[i]));
    h->controls = g_ptr_array_new_with_free_func(g_free);
    h->elements = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    h->routes = read_json("/usr/share/e5/voice-routes.json");
    assert(h->routes);
    json_object_object_foreach(h->routes, key, group) {
        (void)key;
        if (json_object_is_type(group, json_type_object)) {
            json_object_object_foreach(group, k, v) {
                (void)v;
                bool found = false;
                for (unsigned i = 0; i < names->len; i++)
                    if (!strcmp(k, g_ptr_array_index(names, i)))
                        found = true;
                if (!found)
                    g_ptr_array_add(names, g_strdup(k));
            }
        } else
            for (size_t j = 0; j < json_object_array_length(group); j++) {
                const char *k = json_object_get_string(json_object_array_get_idx(group, j));
                bool found = false;
                for (unsigned i = 0; i < names->len; i++)
                    if (!strcmp(k, g_ptr_array_index(names, i)))
                        found = true;
                if (!found)
                    g_ptr_array_add(names, g_strdup(k));
            }
    }
    for (unsigned i = 0; i < names->len; i++)
        add_control(h, g_ptr_array_index(names, i));
    /* Route symbols are represented as numeric values in this fake mixer. */
    json_object_object_foreach(h->routes, k, g) {
        (void)k;
        if (json_object_is_type(g, json_type_object)) {
            json_object_object_foreach(g, n, v) {
                (void)v;
                js(g, n, "1");
            }
        }
    }
    h->gains = json_object_new_object();
    assert(volume_config(h, NULL));
    h->volume = h->ceiling = 15;
    h->call_card = -1;
    h->rate = 8000;
    for (unsigned i = 0; i < 256; i++)
        for (unsigned j = 0; j < 15; j++)
            h->curves[i][j] = (j + 1) * 100;
    h->a = (Alsa){.strerror = err,
                  .ctl_elem_info_malloc = info_alloc,
                  .ctl_elem_info_free = release,
                  .ctl_elem_info_set_interface = iface,
                  .ctl_elem_info_set_name = name_set,
                  .ctl_elem_info_get_type = type,
                  .ctl_elem_info_set_item = item_set,
                  .ctl_elem_info_get_item_name = item_name,
                  .ctl_elem_info_get_items = items,
                  .ctl_elem_info_get_count = count,
                  .ctl_elem_info_get_numid = id,
                  .ctl_elem_info = metadata,
                  .ctl_elem_value_malloc = val_alloc,
                  .ctl_elem_value_free = release,
                  .ctl_elem_value_set_numid = val_id,
                  .ctl_elem_read = val_read,
                  .ctl_elem_write = val_write,
                  .ctl_elem_value_get_enumerated = enum_get,
                  .ctl_elem_value_set_enumerated = enum_set,
                  .ctl_elem_value_get_integer = val_get,
                  .ctl_elem_value_set_integer = val_set,
                  .pcm_open = pcm,
                  .pcm_close = pcm_close_fake,
                  .pcm_prepare = prepare,
                  .pcm_start = start,
                  .pcm_forward = forward,
                  .pcm_hw_params_malloc = info_alloc,
                  .pcm_hw_params_free = release,
                  .pcm_hw_params_any = any,
                  .pcm_hw_params_set_access = parm_i,
                  .pcm_hw_params_set_format = parm_i,
                  .pcm_hw_params_set_channels = parm_u,
                  .pcm_hw_params_set_rate = rate,
                  .pcm_hw_params_set_period_size_near = period,
                  .pcm_hw_params_set_buffer_size_near = buffer,
                  .pcm_hw_params = any};
}
int main(void) {
    VoiceHardware *h = g_new0(VoiceHardware, 1);
    fixture(h);
    GError *error = NULL;
    /* The fake control type is integer: use numeric endpoint names for values. */
    assert(put(h, "VBC_VOLUME", "7", &error));
    char *initial = get(h, "VBC_VOLUME", &error);
    assert(!strcmp(initial, "7,7"));
    g_free(initial);
    unsigned index = 0;
    for (; index < names->len; index++)
        if (!strcmp(g_ptr_array_index(names, index), "VBC_VOLUME"))
            break;
    values[index][0] = 9;
    char *fresh = get(h, "VBC_VOLUME", &error);
    assert(!strcmp(fresh, "9,7"));
    g_free(fresh);
    assert(pcm_open(h, 0, &error));
    assert(pcm_open(h, 1, &error));
    assert(!started);
    assert(start(h->pcm[0]) == 0 && start(h->pcm[1]) == 0);
    h->saved = snapshot(h, &error);
    assert(h->saved);
    h->active = true;
    assert(put(h, "VBC_VOLUME", "2", &error));
    assert(stop_audio(h, &error));
    assert(closed == 2);
    fresh = get(h, "VBC_VOLUME", &error);
    assert(!strcmp(fresh, "9,7"));
    g_free(fresh);
    Json *before = snapshot(h, &error);
    reject = "VBC_VOLUME";
    assert(!put(h, "VBC_VOLUME", "3", &error));
    g_clear_error(&error);
    assert(restore(h, before, &error));
    json_object_put(before);
    for (unsigned band = 0; band < 4; band++) {
        h->band = band;
        for (int ceiling = 1; ceiling <= 15; ceiling++) {
            h->ceiling = ceiling;
            int previous = 0;
            for (int volume = 0; volume <= 15; volume++) {
                h->volume = volume;
                int step = dsp_volume(h);
                assert(step >= 1 && step <= 7 && step >= previous);
                previous = step;
            }
        }
    }
    /* Ten-step recipient calibration reaches the real maximum on both routes;
     * legacy tables and Bluetooth keep their original seven-step behavior. */
    Json *stock = json_tokener_parse("{\"steps\":10,\"dac_gain\":{\"0\":25,\"2\":25,\"4\":24,\"5\":24,\"7\":26,\"9\":26,\"11\":24,\"12\":24}}");
    json_object_object_add(h->routes, "VOICE_VOLUME", stock);
    assert(volume_config(h, &error));
    for (unsigned band = 0; band < 4; band++)
        for (unsigned speaker = 0; speaker < 2; speaker++) {
            h->band = band; h->speaker = speaker; h->ceiling = 15;
            int previous = 0;
            for (int level = 0; level <= 15; level++) {
                h->volume = level;
                int step = dsp_volume(h);
                assert(step >= previous && step >= 1 && step <= 10);
                previous = step;
            }
            assert(dsp_volume(h) == 10);
            assert(volume(h, true, &error));
            assert(h->applied_gain == (band < 2 ? (speaker ? 26 : 25) : 24));
        }
    h->bluetooth = true;
    assert(dsp_volume(h) == 7);
    assert(volume(h, true, &error) && h->applied_gain == 24);
    h->bluetooth = false;
    json_object_object_add(stock, "steps", json_object_new_int(16));
    assert(!volume_config(h, &error));
    g_clear_error(&error);
    json_object_object_del(h->routes, "VOICE_VOLUME");
    assert(volume_config(h, &error) && h->volume_steps == 7);
    h->band = 0; h->speaker = false;
    AudioRequest request = {
        .live = true, .card = 0, .route = "receiver", .volume = 15, .rate = 8000};
    Json *state = audio_apply(h, &request, &error);
    if (error)
        g_printerr("%s\n", error->message);
    assert(!error && jbool(state, "active", false));
    json_object_put(state);
    request.muted = true;
    request.route = "speaker";
    state = audio_apply(h, &request, &error);
    assert(!error && jbool(state, "speaker", false) && jbool(state, "muted", false));
    json_object_put(state);
    request.route = "bluetooth";
    request.rate = 16000;
    state = audio_apply(h, &request, &error);
    assert(!error && !strcmp(jstr(state, "route", ""), "bluetooth") &&
           jbool(state, "muted", false));
    json_object_put(state);
    request.route = "receiver";
    request.card = 1;
    state = audio_apply(h, &request, &error);
    assert(!error && jint(state, "card", -1) == 1 && jbool(state, "active", false));
    json_object_put(state);
    request.live = false;
    request.volume = 3;
    request.band = 1;
    reject = "VBC_VOLUME";
    state = audio_apply(h, &request, &error);
    /* Inject a failing mixer at the exact hangup/config-change boundary.
     * Reporting restore failure is correct; retaining active PCM is not. */
    assert(error && !jbool(state, "active", true));
    g_clear_error(&error);
    json_object_put(state);
    assert(opened == closed);
    audio_free(h);
    g_ptr_array_unref(names);
    g_ptr_array_unref(writes);
    puts("mixer freshness, rollback, PCM prepare order and volume bounds passed");
    return 0;
}
