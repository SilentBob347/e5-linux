/* SPDX-License-Identifier: GPL-2.0-only */
/* Exercise the actual QUERY constructor/parser without hardware or sysfs. */
#include <assert.h>
#include <stdarg.h>
#include <sys/ioctl.h>
static int query_ioctl(int fd, unsigned long op, ...);
#define ioctl query_ioctl
#define main ufs_identity_program_main
#include "../ufs-id.c"
#undef main
#undef ioctl

static int fault;
static int calls;
static int query_ioctl(int fd, unsigned long op, ...)
{
    va_list args;
    va_start(args,op);
    struct sg_io_v4 *io=va_arg(args,struct sg_io_v4 *);
    va_end(args);
    const struct ufs_bsg_request *req=(void *)(uintptr_t)io->request;
    struct ufs_bsg_reply *reply=(void *)(uintptr_t)io->response;
    unsigned char *data=(void *)(uintptr_t)io->din_xferp;
    assert(fd==7 && op==SG_IO);
    assert(io->guard=='Q' && io->protocol==0 && io->subprotocol==2);
    assert(!io->dout_xfer_len && !io->dout_xferp);
    assert(io->din_xfer_len==255 && io->request_len==sizeof(*req));
    assert(req->msgcode==0x16 && req->upiu_req.qr.opcode==1);
    assert(be32toh(req->upiu_req.header.dword_0)==0x16000000);
    assert(be32toh(req->upiu_req.header.dword_1)==0x00010000);
    assert(req->upiu_req.qr.idn==0 || req->upiu_req.qr.idn==5);
    assert(!req->upiu_req.qr.selector && !req->upiu_req.qr.value);
    assert(be16toh(req->upiu_req.qr.length)==255);
    calls++;
    data[0]=8;data[1]=req->upiu_req.qr.idn;
    reply->reply_payload_rcv_len=8;
    switch(fault) {
    case 1:errno=EIO;return -1;
    case 2:reply->result=-EIO;break;
    case 3:io->transport_status=1;break;
    case 4:io->device_status=1;break;
    case 5:io->driver_status=1;break;
    case 6:reply->reply_payload_rcv_len=2;break;
    case 7:reply->reply_payload_rcv_len=256;break;
    case 8:data[1]=7;break;
    case 9:data[0]=2;break;
    case 10:data[0]=9;break;
    }
    return 0;
}

int main(void)
{
    unsigned char data[255];
    for(fault=0;fault<=10;fault++) {
        memset(data,0,sizeof(data));
        int result=read_descriptor(7,0,0,data);
        assert(fault ? result==-1 : result==8);
    }
    fault=0;
    assert(read_descriptor(7,5,3,data)==8);
    assert(calls==12);
    puts("UFS identity: READ-only UPIU and malformed/error response cases passed");
    return 0;
}
