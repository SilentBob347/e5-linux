#!/usr/bin/env python3
"""Compile the production topology predicate with device metadata fixtures."""
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
start = source.index('static gboolean\ndevice_context_has_complete_unisoc_ports (')
function = source[start:source.index('\n}\n', start)+3]
model = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef int gboolean;
typedef char gchar;
typedef unsigned guint;
#define TRUE 1
#define FALSE 0
typedef struct {const char *subsystem,*driver; int tag;} MMKernelDevice;
typedef struct GList {void *data;struct GList *next;} GList;
typedef struct {GList *ports;unsigned bank[2];} Device;
typedef struct {Device *device;} DeviceContext;
#define MM_PORT_PROBE(x) (x)
#define g_list_next(x) ((x)->next)
#define g_strcmp0(a,b) strcmp(a,b)
#define g_snprintf snprintf
static GList *mm_device_peek_port_probe_list(Device *d) {return d->ports;}
static MMKernelDevice *mm_port_probe_peek_port(void *p) {return p;}
static const char *mm_kernel_device_get_subsystem(MMKernelDevice *p) {return p->subsystem;}
static const char *mm_kernel_device_get_driver(MMKernelDevice *p) {return p->driver;}
static int mm_kernel_device_get_property_as_boolean(MMKernelDevice *p,const char *key) {
 assert(!strcmp(key,"ID_MM_UNISOC_SIPC"));return p->tag;
}
static int mm_device_owns_port_name(Device *d,const char *sub,const char *name) {
 unsigned i;assert(!strcmp(sub,"net"));assert(sscanf(name,"sipa_eth%u",&i)==1);
 return !!(d->bank[i/8] & (1U<<(i%8)));
}
'''
cases = r'''
int main(void) {
 MMKernelDevice port={"wwan","sprd-spipe",1};
 GList list={&port,NULL};Device d={&list,{255,0}};DeviceContext c={&d};
 assert(device_context_has_complete_unisoc_ports(&c));
 d.bank[0]=0;d.bank[1]=255;assert(device_context_has_complete_unisoc_ports(&c));
 for(unsigned bank=0;bank<2;bank++) for(unsigned bit=0;bit<8;bit++) {
  d.bank[0]=d.bank[1]=0;d.bank[bank]=255 & ~(1U<<bit);
  assert(!device_context_has_complete_unisoc_ports(&c));
 }
 d.bank[0]=255;d.bank[1]=7;assert(device_context_has_complete_unisoc_ports(&c));
 d.bank[1]=0;
 port.tag=0;assert(!device_context_has_complete_unisoc_ports(&c));port.tag=1;
 port.driver="option";assert(!device_context_has_complete_unisoc_ports(&c));port.driver="sprd-spipe";
 port.subsystem="tty";assert(!device_context_has_complete_unisoc_ports(&c));port.subsystem="wwan";
 d.ports=NULL;assert(!device_context_has_complete_unisoc_ports(&c));
 puts("23 production topology cases passed");
}
'''
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory);(p/'test.c').write_text(model+function+cases)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
