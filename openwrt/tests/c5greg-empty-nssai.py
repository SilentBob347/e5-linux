#!/usr/bin/env python3
"""Use production GLib registration regexes; URC removal must preserve final OK."""
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
start = source.index('static const gchar *creg_regex[] = {')
array = source[start:source.index('\n};', start)+3]
start = source.index('GPtrArray *\nmm_3gpp_creg_regex_get (')
function = source[start:source.index('\n}\n',start)+3]
test = r'''
#include <glib.h>
#include <stdio.h>
#include <string.h>
PRODUCTION
static void check(const char *line, const char *final) {
    GPtrArray *regexes=mm_3gpp_creg_regex_get(FALSE);
    gchar *buffer=g_strdup_printf("\r\n%s\r\n\r\n%s\r\n",line,final);
    gboolean matched=FALSE;
    for(guint i=0;i<regexes->len;i++) {
        GRegex *regex=g_ptr_array_index(regexes,i);
        if(g_regex_match(regex,buffer,0,NULL)) {
            GError *error=NULL;
            gchar *next=g_regex_replace_literal(regex,buffer,-1,0,"",0,&error);
            g_assert_no_error(error);g_free(buffer);buffer=next;matched=TRUE;
        }
    }
    g_assert_true(matched);
    if(!strstr(buffer,final))g_error("registration URC consumed final result: %s",final);
    g_free(buffer);
    for(guint i=0;i<regexes->len;i++)g_regex_unref(g_ptr_array_index(regexes,i));
    g_ptr_array_free(regexes,TRUE);
}
int main(void) {
    const char *lines[]={
      "+C5GREG: 2,1,\"1234\",\"ABCDEF\",11,0,",
      "+C5GREG: 1,\"1234\",\"ABCDEF\",11,0,",
      "+C5GREG: 2,1,\"1234\",\"ABCDEF\",11,0, ",
      "+C5GREG:\t2, 1, \"1234\", \"ABCDEF\", 11, 0,\t",
      "+C5GREG: 2,1,\"1234\",\"ABCDEF\",11,3,010203",
      "+C5GREG: 1,\"1234\",\"ABCDEF\",11,3,010203",
      "+CREG: 2,1,\"1234\",\"ABCDEF\",7",
      "+CGREG: 2,1,\"1234\",\"ABCDEF\",7",
      "+CEREG: 2,1,\"1234\",\"ABCDEF\",11"
    };
    for(guint i=0;i<G_N_ELEMENTS(lines);i++) {
        check(lines[i],"OK");check(lines[i],"ERROR");
    }
    puts("18 production GLib registration framing cases passed");
}
'''.replace('PRODUCTION',array+'\n'+function)
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory);(p/'test.c').write_text(test)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','glib-2.0'],text=True))
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'test.c'),*flags,'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
