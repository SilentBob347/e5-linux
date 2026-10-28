/* SPDX-License-Identifier: GPL-2.0-only */
/* Read-only snapshot of retained input MT coordinates; no generated input. */
#include <fcntl.h>
#include <linux/input.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    char name[128] = {0};
    int axes[] = {ABS_MT_TRACKING_ID, ABS_MT_POSITION_X, ABS_MT_POSITION_Y};
    int fd = open(argc > 1 ? argv[1] : "/dev/input/event1", O_RDONLY);
    if (fd < 0 || ioctl(fd, EVIOCGNAME(sizeof(name)), name) < 0) {
        perror("input device");
        return 1;
    }
    printf("input: %s\n", name);
    for (unsigned i = 0; i < sizeof(axes)/sizeof(axes[0]); i++) {
        int values[6] = {axes[i]};
        if (ioctl(fd, EVIOCGMTSLOTS(sizeof(values)), values) < 0) {
            perror("MT slots");
            close(fd);
            return 1;
        }
        printf("axis %x:", axes[i]);
        for (unsigned j = 1; j < 6; j++)
            printf(" %d", values[j]);
        putchar('\n');
    }
    close(fd);
    return 0;
}
