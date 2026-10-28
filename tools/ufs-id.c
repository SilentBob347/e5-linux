/* SPDX-License-Identifier: GPL-2.0-only */
/* Read-only UFS QUERY READ DESCRIPTOR fingerprint input.
 * Use raw descriptor bytes, not kernel-specific UTF16->ASCII presentation.
 * There is no WRITE query, UIC command, RPMB or block-write operation here.
 * Wire ABI: Linux include/uapi/scsi/scsi_bsg_ufs.h (5.4 and 6.18).
 */
#define _GNU_SOURCE
#include <ctype.h>
#include <dirent.h>
#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/bsg.h>
#include <scsi/scsi_bsg_ufs.h>
#include <scsi/sg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

_Static_assert(sizeof(struct utp_upiu_req)==32,"UFS UPIU ABI differs");
_Static_assert(sizeof(struct ufs_bsg_request)==36,"UFS BSG ABI differs");

static int read_descriptor(int fd,unsigned idn,unsigned index,unsigned char *out)
{
    struct ufs_bsg_request req={0};
    struct ufs_bsg_reply reply={0};
    struct sg_io_v4 io={0};
    req.msgcode=0x16; /* QUERY_REQ */
    req.upiu_req.header.dword_0=htobe32(0x16000000);
    req.upiu_req.header.dword_1=htobe32(0x00010000); /* STANDARD_READ */
    req.upiu_req.qr.opcode=1; /* READ_DESC, never caller-selected */
    req.upiu_req.qr.idn=idn;
    req.upiu_req.qr.index=index;
    req.upiu_req.qr.length=htobe16(255);
    io.guard='Q';io.protocol=0;io.subprotocol=2;
    io.request_len=sizeof(req);io.request=(uintptr_t)&req;
    io.max_response_len=sizeof(reply);io.response=(uintptr_t)&reply;
    io.din_xfer_len=255;io.din_xferp=(uintptr_t)out;io.timeout=3000;
    if(ioctl(fd,SG_IO,&io)<0)return -1;
    if(reply.result||io.driver_status||io.transport_status||io.device_status||
       reply.reply_payload_rcv_len<3||reply.reply_payload_rcv_len>255||
       out[1]!=idn||out[0]<3||out[0]>reply.reply_payload_rcv_len) {
        errno=EIO;return -1;
    }
    return out[0];
}

static int open_bsg(const char *controller)
{
    DIR *dir=opendir("/sys/class/bsg");struct dirent *e;char selected[PATH_MAX]={0};
    if(!dir)return -1;
    while((e=readdir(dir))) {
        char path[PATH_MAX],resolved[PATH_MAX];const char *p=e->d_name;
        if(strncmp(p,"ufs-bsg",7)||!p[7])continue;
        unsigned n=7;while(isdigit((unsigned char)p[n]))n++;
        if(p[n])continue;
        snprintf(path,sizeof path,"/sys/class/bsg/%s",p);
        if(!realpath(path,resolved)||strncmp(resolved,controller,strlen(controller))||resolved[strlen(controller)]!='/')continue;
        if(selected[0]){closedir(dir);errno=EEXIST;return -1;}
        snprintf(selected,sizeof selected,"/sys/class/bsg/%s/dev",p);
    }
    closedir(dir);
    if(!selected[0]){errno=ENODEV;return -1;}
    FILE *f=fopen(selected,"r");unsigned maj,min;char extra;
    if(!f)return -1;
    int ok=fscanf(f,"%u:%u %c",&maj,&min,&extra);fclose(f);
    if(ok!=2){errno=EINVAL;return -1;}
    /* Android may expose the class but not create /dev/bsg. The temporary
     * node lives only in devtmpfs and is unlinked immediately after open. */
    char temp[]="/dev/.e5-ufs-id-XXXXXX",node[PATH_MAX];struct stat st;
    if(!mkdtemp(temp))return -1;
    snprintf(node,sizeof node,"%s/query",temp);
    int fd=-1;
    if(!mknod(node,S_IFCHR|0600,makedev(maj,min)))fd=open(node,O_RDWR|O_CLOEXEC|O_NOFOLLOW);
    int saved=errno;unlink(node);rmdir(temp);errno=saved;
    if(fd>=0&&(fstat(fd,&st)||!S_ISCHR(st.st_mode)||st.st_rdev!=makedev(maj,min))){close(fd);errno=ENODEV;return -1;}
    return fd;
}

int main(int argc,char **argv)
{
    char controller[PATH_MAX];unsigned char device[255]={0},manufacturer[255]={0},serial[255]={0};
    if(argc!=2||geteuid()!=0||!realpath(argv[1],controller)||
       strncmp(controller,"/sys/devices/",13)||strlen(controller)<4||strcmp(controller+strlen(controller)-4,".ufs")) {
        fputs("usage: ufs-id /sys/.../CONTROLLER.ufs (root, READ descriptors only)\n",stderr);return 2;
    }
    int fd=open_bsg(controller);
    if(fd<0){perror("UFS read-only BSG channel");return 1;}
    int d=read_descriptor(fd,0,0,device),m=-1,s=-1;
    if(d>0x16&&device[0x14]&&device[0x16]) {
        m=read_descriptor(fd,5,device[0x14],manufacturer);
        s=read_descriptor(fd,5,device[0x16],serial);
    }
    close(fd);
    if(m<3||s<3){perror("UFS READ DESCRIPTOR");return 1;}
    printf("ufs-descriptor-v1:");
    for(int i=0;i<m;i++)printf("%02x",manufacturer[i]);
    putchar(':');for(int i=0;i<s;i++)printf("%02x",serial[i]);
    putchar('\n');return 0;
}
