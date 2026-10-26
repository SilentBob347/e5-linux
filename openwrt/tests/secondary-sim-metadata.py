#!/usr/bin/env python3
"""Compile production callbacks with real GLib tasks; no AT or device access."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(sys.argv[1])
source = (root if root.is_file() else root / 'plugins/unisoc/mm-broadband-modem-unisoc.c').read_text()


def function(name):
    pos = source.index(name + ' (')
    start = source.rfind('\nstatic ', 0, pos) + 1
    return source[start:source.index('\n}\n', pos) + 3]


model = r'''
#include <gio/gio.h>
#include <assert.h>
#include <stdarg.h>
#include <string.h>
#include <stdio.h>
typedef GObject MMBaseModem;
typedef GObject MMBroadbandModemUnisoc;
typedef GObject MMIfaceModem;
typedef GObject MMBaseSim;
typedef int MMModemState;
enum { MM_MODEM_STATE_FAILED=-1, MM_MODEM_STATE_UNKNOWN, MM_MODEM_STATE_LOCKED,
       MM_MODEM_STATE_DISABLED, MM_MODEM_STATE_ENABLING, MM_MODEM_STATE_ENABLED,
       MM_MODEM_STATE_SEARCHING, MM_MODEM_STATE_REGISTERED, MM_MODEM_STATE_CONNECTING,
       MM_MODEM_STATE_CONNECTED };
#define MM_BASE_MODEM(p) ((MMBaseModem *)(p))
#define MM_GDBUS_SIM(p) (p)
#define MM_IFACE_MODEM_STATE "state"
#define MM_IFACE_MODEM_SIM_SLOTS "slots"
#define mm_obj_dbg(...) ((void)0)
static unsigned own;
static int state, valid=1;
static GPtrArray *current;
static guint port_card(void) { return own; }
static gboolean mm_base_modem_get_valid(MMBaseModem *self) { return valid; }
static void fixture_get(gpointer object, ...) {
    va_list args; va_start(args,object); const char *key;
    while ((key=va_arg(args,const char *))) {
        void *out=va_arg(args,void *);
        if (!strcmp(key,"state")) *(int *)out=state;
        else { assert(!strcmp(key,"slots")); *(GPtrArray **)out=current ? g_ptr_array_ref(current) : NULL; }
    }
    va_end(args);
}
#define g_object_get fixture_get
static const char *mm_gdbus_sim_get_sim_identifier(MMBaseSim *sim) { return g_object_get_data(sim,"iccid"); }
static const char *mm_gdbus_sim_get_imsi(MMBaseSim *sim) { return g_object_get_data(sim,"imsi"); }
static void mm_gdbus_sim_set_imsi(MMBaseSim *sim,const char *text) { g_object_set_data_full(sim,"imsi",g_strdup(text),g_free); }
static void mm_gdbus_sim_set_operator_identifier(MMBaseSim *sim,const char *text) { g_object_set_data_full(sim,"operator",g_strdup(text),g_free); }
static MMBaseSim *mm_base_sim_new_initialized(MMBaseModem *modem,guint slot,gboolean active,
 const char *iccid,const char *imsi,const char *eid,const char *op,const char *name,const GStrv numbers) {
    MMBaseSim *sim=g_object_new(G_TYPE_OBJECT,NULL);
    g_object_set_data(sim,"slot",GUINT_TO_POINTER(slot));
    g_object_set_data(sim,"active",GINT_TO_POINTER(active));
    g_object_set_data_full(sim,"iccid",g_strdup(iccid),g_free);
    mm_gdbus_sim_set_imsi(sim,imsi);
    mm_gdbus_sim_set_operator_identifier(sim,op);
    return sim;
}
typedef struct { char *command; GAsyncReadyCallback callback; gpointer data; } Command;
static GQueue queue=G_QUEUE_INIT;
static void mm_base_modem_at_command(MMBaseModem *self,const char *command,guint timeout,
 gboolean cached,GAsyncReadyCallback callback,gpointer data) {
    Command *c=g_new0(Command,1); c->command=g_strdup(command); c->callback=callback; c->data=data;
    assert(timeout==5); assert(!cached); g_queue_push_tail(&queue,c);
}
static const char *mm_base_modem_at_command_finish(MMBaseModem *self,GAsyncResult *result,GError **error) {
    GError *failure=g_object_get_data(G_OBJECT(result),"error");
    if (failure && error) *error=g_error_copy(failure);
    return g_object_get_data(G_OBJECT(result),"reply");
}
static const char *mm_strip_tag(const char *response,const char *tag) {
    return g_str_has_prefix(response,tag) ? response+strlen(tag) : response;
}
static void sim_slot_free(MMBaseSim *sim) { if(sim) g_object_unref(sim); }
typedef struct { guint card; char *iccid; } LoadSimSlotsContext;
static void free_context(gpointer value) { LoadSimSlotsContext *ctx=value;g_free(ctx->iccid);g_free(ctx); }
'''

tests = r'''
static void complete(MMBaseModem *modem,const char *expected,const char *reply,int error) {
    Command *c=g_queue_pop_head(&queue); assert(c); assert(!strcmp(c->command,expected));
    if(c->callback) {
        GTask *result=g_task_new(modem,NULL,NULL,NULL);
        g_object_set_data(G_OBJECT(result),"reply",(gpointer)reply);
        if(error) g_object_set_data_full(G_OBJECT(result),"error",g_error_new_literal(G_IO_ERROR,error,"fixture error"),(GDestroyNotify)g_error_free);
        c->callback(G_OBJECT(modem),G_ASYNC_RESULT(result),c->data);
        g_object_unref(result);
    }
    g_free(c->command);g_free(c);
}
static GTask *slot_load(MMBaseModem *modem,const char *ccid) {
    GTask *task=g_task_new(modem,NULL,NULL,NULL);
    LoadSimSlotsContext *ctx=g_new0(LoadSimSlotsContext,1);ctx->card=own;
    g_task_set_task_data(task,ctx,free_context);
    GTask *result=g_task_new(modem,NULL,NULL,NULL);
    g_object_set_data(G_OBJECT(result),"reply",(gpointer)ccid);
    /* Callback owns its task reference, retain our finish() reference. */
    other_card_ccid_ready(modem,G_ASYNC_RESULT(result),g_object_ref(task));
    g_object_unref(result);
    return task;
}
static void slots_ready(MMBaseModem *modem,GTask *task) {
    guint primary=0;GError *error=NULL;
    assert(modem_load_sim_slots_finish((MMIfaceModem *)modem,G_ASYNC_RESULT(task),&current,&primary,&error));
    assert(!error && primary==own+1 && current->len==2);
    g_object_unref(task);
}
static void changed(MMBaseModem *modem,int next) { state=next;secondary_sim_state_changed(modem,NULL,NULL); }
static void reset_fixture(void) {
    assert(g_queue_is_empty(&queue));g_clear_pointer(&current,g_ptr_array_unref);valid=1;state=MM_MODEM_STATE_DISABLED;
}
static void load(MMBaseModem *modem,const char *ccid) {
    char restore[40];g_snprintf(restore,sizeof restore,"+SPACTCARD=%u;+CFUN?",own);
    GTask *task=slot_load(modem,ccid);
    /* No synchronous CIMI is allowed before the original context restore. */
    assert(g_queue_get_length(&queue)==1);
    complete(modem,restore,"+CFUN: 1",0);slots_ready(modem,task);
}
static void finalized(gpointer flag,GObject *object) { *(int *)flag=1; }
int main(void) {
    MMBaseModem *modem=g_object_new(G_TYPE_OBJECT,NULL);
    assert(!secondary_sim_parse_imsi(NULL,"ABC"));
    assert(!secondary_sim_parse_imsi("+CCID: ABC\n12345",NULL));
    assert(!secondary_sim_parse_imsi("+CCID: WRONG\n460011234567890","ABC"));
    assert(!secondary_sim_parse_imsi("+CCID: ABC\n12345\n67890","ABC"));
    assert(!secondary_sim_parse_imsi("+CCID: ABC\n+CCID: ABC\n12345","ABC"));
    assert(!secondary_sim_parse_imsi("+CCID: ABC\n1234","ABC"));
    char *id=secondary_sim_parse_imsi("+CCID: \"89ABCz\"\r\n460011234567890","89ABCz");
    assert(id && !strcmp(id,"460011234567890"));g_free(id);
    id=secondary_sim_parse_imsi("89ABCz\n460011234567890","89ABCz");assert(id);g_free(id);
    for(own=0;own<2;own++) {
        char query[64],restore[40];
        g_snprintf(query,sizeof query,"+SPACTCARD=%u;+CCID?;+CIMI",1-own);
        g_snprintf(restore,sizeof restore,"+SPACTCARD=%u;+CFUN?",own);
        reset_fixture();load(modem,"+CCID: \"89ABCz\"");
        MMBaseSim *sim=g_ptr_array_index(current,1-own);
        assert(sim && !strcmp(mm_gdbus_sim_get_sim_identifier(sim),"89ABCz"));
        MMBaseSim *primary=g_ptr_array_index(current,own);
        assert(primary && GPOINTER_TO_INT(g_object_get_data(primary,"active")));
        assert(!GPOINTER_TO_INT(g_object_get_data(sim,"active")));
        assert(GPOINTER_TO_UINT(g_object_get_data(sim,"slot"))==2-own);
        for(int s=MM_MODEM_STATE_FAILED;s<MM_MODEM_STATE_CONNECTED;s++) {
            changed(modem,s);assert(g_queue_is_empty(&queue));
        }
        mm_gdbus_sim_set_imsi(sim,"");
        changed(modem,MM_MODEM_STATE_CONNECTED);changed(modem,MM_MODEM_STATE_CONNECTED);
        assert(g_queue_get_length(&queue)==1);
        complete(modem,query,"+CCID: \"89ABCz\"\n460011234567890",0);
        assert(!strcmp(mm_gdbus_sim_get_imsi(sim),"460011234567890"));
        assert(!strcmp(g_object_get_data(sim,"operator"),"46001"));
        assert(g_ptr_array_index(current,own)==primary);
        assert(!mm_gdbus_sim_get_imsi(primary));
        complete(modem,restore,"+CFUN: 1",0);
        changed(modem,MM_MODEM_STATE_CONNECTED);assert(g_queue_is_empty(&queue));
        /* Metadata errors preserve the existing secondary object and ICCID. */
        for(int error=0;error<2;error++) {
            reset_fixture();load(modem,"+CCID: \"89ABCz\"");sim=g_ptr_array_index(current,1-own);
            changed(modem,MM_MODEM_STATE_CONNECTED);
            complete(modem,query,"+CCID: REPLACED\n460011234567890",error);
            assert(!mm_gdbus_sim_get_imsi(sim));assert(g_ptr_array_index(current,1-own)==sim);
            complete(modem,restore,"+CFUN: 1",0);
            /* No timer retry; a later real connection transition may retry. */
            assert(g_queue_is_empty(&queue));changed(modem,MM_MODEM_STATE_REGISTERED);
            assert(g_queue_is_empty(&queue));changed(modem,MM_MODEM_STATE_CONNECTED);
            complete(modem,query,"+CCID: \"89ABCz\"\n460011234567890",0);
            complete(modem,restore,"+CFUN: 1",0);
        }
        /* A removed slot is retained only for callback lifetime, never updated. */
        reset_fixture();load(modem,"+CCID: \"89ABCz\"");sim=g_ptr_array_index(current,1-own);
        int gone=0;g_object_weak_ref(sim,finalized,&gone);
        changed(modem,MM_MODEM_STATE_CONNECTED);
        g_ptr_array_index(current,1-own)=NULL;g_object_unref(sim);assert(!gone);
        complete(modem,query,"+CCID: \"89ABCz\"\n460011234567890",0);assert(gone);
        complete(modem,restore,"+CFUN: 1",0);
        /* CP/MM invalidation must not send a new restore command. */
        reset_fixture();load(modem,"+CCID: \"89ABCz\"");sim=g_ptr_array_index(current,1-own);
        changed(modem,MM_MODEM_STATE_CONNECTED);valid=0;
        complete(modem,query,"+CCID: \"89ABCz\"\n460011234567890",0);
        assert(!mm_gdbus_sim_get_imsi(sim));assert(g_queue_is_empty(&queue));
        /* An absent secondary card never queues a metadata operation. */
        reset_fixture();load(modem,NULL);assert(!g_ptr_array_index(current,1-own));
        changed(modem,MM_MODEM_STATE_CONNECTED);assert(g_queue_is_empty(&queue));
    }
    reset_fixture();g_object_unref(modem);
    puts("PASS: primary initialization never waits for secondary IMSI; both slots, connection gate, identity mismatch, stale objects, errors, context restoration and task lifetime");
}
'''

parts = [function(name) for name in (
    'secondary_sim_is_current', 'secondary_sim_parse_imsi', 'secondary_sim_identity_ready',
    'secondary_sim_state_changed', 'modem_load_sim_slots_finish',
    'other_card_back_ready', 'other_card_back', 'other_card_ccid_ready')]
assert 'other_card_cimi_ready' not in source
assert 'G_CALLBACK (secondary_sim_state_changed)' in source
loader = function('modem_load_sim_slots')
assert '+CCID?' in loader and '+CIMI' not in loader
assert '+CIMI' not in function('other_card_ccid_ready')
metadata = '\n'.join(parts[:4])
assert '+SFUN' not in metadata and '+SPSWDATA' not in metadata
with tempfile.TemporaryDirectory(prefix='e5-secondary-metadata-') as directory:
    path = Path(directory)
    (path / 'test.c').write_text(model + '\n'.join(parts) + tests)
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gio-2.0'], text=True).split()
    subprocess.run(['cc', '-Wall', '-Werror', '-g', '-fsanitize=undefined',
                    str(path / 'test.c'), '-o', str(path / 'test'), *flags], check=True)
    subprocess.run([str(path / 'test')], check=True)
