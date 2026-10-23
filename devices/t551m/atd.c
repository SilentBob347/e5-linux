/* SPDX-License-Identifier: MIT
 * E5 dedicated AT owner. Native replacement for atd.py, using the same socket
 * request/plain/JSON contracts and the same nr2/nr6/nr7 ownership boundaries.
 * No command retries, tty reopen on timeout, URC-port reads or radio resets.
 */
#define _GNU_SOURCE
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/netlink.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/inotify.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

#define LIMIT 131072
static volatile sig_atomic_t stopping;
static int modem = -1, server = -1, notifier = -1, kernel_events = -1;
static const char *root = "";
static char endpoint[108], partial[LIMIT + 1];
static size_t partial_used;
static bool synchronized = true;
static double last_write, failed_at;
static void stop(int sig)
{
    (void)sig;
    stopping = 1;
}
static double now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static void pause_until(double end)
{
    while (!stopping && now() < end) {
        int ms = (int)((end - now()) * 1000) + 1;
        poll(NULL, 0, ms);
    }
}
static void path(char *out, size_t n, const char *suffix)
{
    if (snprintf(out, n, "%s%s", root, suffix) >= (int)n) {
        fputs("AT path too long\n", stderr);
        exit(1);
    }
}
static int text(const char *suffix, char *out, size_t size)
{
    char p[512];
    path(p, sizeof(p), suffix);
    int fd = open(p, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return -1;
    ssize_t n = read(fd, out, size - 1);
    close(fd);
    if (n < 0)
        return -1;
    out[n] = 0;
    return 0;
}
static bool final(const char *s)
{
    return !strcmp(s, "OK") || !strcmp(s, "ERROR") || !strcmp(s, "NO CARRIER") ||
           !strcmp(s, "BUSY") || !strcmp(s, "NO ANSWER") || !strcmp(s, "CONNECT") ||
           !strncmp(s, "CONNECT ", 8) || !strcmp(s, "+CME ERROR") || !strcmp(s, "+CMS ERROR") ||
           !strncmp(s, "+CME ERROR:", 11) || !strncmp(s, "+CMS ERROR:", 11);
}

/* Bounded JSON parser. Decode strings before validating the ASCII command;
 * nested unknown fields are parsed, never interpreted as request fields. */
struct request {
    char command[1025];
    double timeout, deadline;
    bool plain, have_command, have_deadline;
};
static void ws(const char **s)
{
    while (isspace((unsigned char)**s))
        (*s)++;
}
static int string(const char **s, char *out, size_t size)
{
    if (*(*s)++ != '"')
        return -1;
    size_t n = 0;
    while (**s && **s != '"') {
        unsigned c = (unsigned char)*(*s)++;
        if (c < 32)
            return -1;
        if (c == '\\') {
            if (!**s)
                return -1;
            c = (unsigned char)*(*s)++;
            switch (c) {
            case '"':
            case '\\':
            case '/':
                break;
            case 'b':
                c = 8;
                break;
            case 'f':
                c = 12;
                break;
            case 'n':
                c = 10;
                break;
            case 'r':
                c = 13;
                break;
            case 't':
                c = 9;
                break;
            case 'u': {
                c = 0;
                for (int i = 0; i < 4; i++) {
                    unsigned x = (unsigned char)**s;
                    if (!x || !isxdigit(x))
                        return -1;
                    (*s)++;
                    c = c * 16 + (isdigit(x) ? x - '0' : tolower(x) - 'a' + 10);
                }
                if (c > 127 || !c)
                    return -1;
                break;
            }
            default:
                return -1;
            }
        }
        if (n + 1 >= size)
            return -1;
        out[n++] = (char)c;
    }
    if (**s != '"')
        return -1;
    (*s)++;
    out[n] = 0;
    return 0;
}
static int number(const char **s, double *value)
{
    const char *p = *s, *start = p;
    if (*p == '-')
        p++;
    if (*p == '0')
        p++;
    else {
        if (*p < '1' || *p > '9')
            return -1;
        while (isdigit((unsigned char)*p))
            p++;
    }
    if (*p == '.') {
        p++;
        if (!isdigit((unsigned char)*p))
            return -1;
        while (isdigit((unsigned char)*p))
            p++;
    }
    if (*p == 'e' || *p == 'E') {
        p++;
        if (*p == '+' || *p == '-')
            p++;
        if (!isdigit((unsigned char)*p))
            return -1;
        while (isdigit((unsigned char)*p))
            p++;
    }
    char *end;
    *value = strtod(start, &end);
    if (end != p)
        return -1;
    *s = p;
    return 0;
}
static int skip(const char **s, int depth)
{
    if (depth > 16)
        return -1;
    ws(s);
    if (**s == '"') {
        char tmp[4097];
        return string(s, tmp, sizeof(tmp));
    }
    if (**s == '{' || **s == '[') {
        bool obj = **s == '{';
        char end = obj ? '}' : ']';
        (*s)++;
        ws(s);
        if (**s == end) {
            (*s)++;
            return 0;
        }
        while (**s) {
            if (obj) {
                char key[4097];
                if (string(s, key, sizeof(key)))
                    return -1;
                ws(s);
                if (*(*s)++ != ':')
                    return -1;
            }
            if (skip(s, depth + 1))
                return -1;
            ws(s);
            if (**s == end) {
                (*s)++;
                return 0;
            }
            if (*(*s)++ != ',')
                return -1;
            ws(s);
        }
        return -1;
    }
    for (int i = 0; i < 3; i++) {
        const char *v = i == 0 ? "true" : i == 1 ? "false" : "null";
        size_t n = strlen(v);
        if (!strncmp(*s, v, n)) {
            *s += n;
            return 0;
        }
    }
    double v;
    return number(s, &v);
}
static int parse(const char *s, struct request *r)
{
    memset(r, 0, sizeof(*r));
    r->timeout = 8;
    ws(&s);
    if (*s++ != '{')
        return -1;
    ws(&s);
    if (*s != '}')
        for (;;) {
            char key[128];
            if (string(&s, key, sizeof(key)))
                return -1;
            ws(&s);
            if (*s++ != ':')
                return -1;
            ws(&s);
            if (!strcmp(key, "command")) {
                if (string(&s, r->command, sizeof(r->command)))
                    return -1;
                r->have_command = true;
            } else if (!strcmp(key, "timeout")) {
                if (number(&s, &r->timeout))
                    return -1;
            } else if (!strcmp(key, "deadline")) {
                if (number(&s, &r->deadline))
                    return -1;
                r->have_deadline = true;
            } else if (!strcmp(key, "plain")) {
                if (!strncmp(s, "true", 4)) {
                    r->plain = true;
                    s += 4;
                } else if (!strncmp(s, "false", 5)) {
                    r->plain = false;
                    s += 5;
                } else
                    return -1;
            } else if (skip(&s, 0))
                return -1;
            ws(&s);
            if (*s == '}')
                break;
            if (*s++ != ',')
                return -1;
            ws(&s);
        }
    if (*s++ != '}')
        return -1;
    ws(&s);
    if (*s)
        return -1;
    if (!r->have_command || !r->have_deadline || strncasecmp(r->command, "AT", 2) ||
        r->timeout < 1 || r->timeout > 60 || !(r->deadline > now() && r->deadline <= now() + 90))
        return -1;
    for (const unsigned char *p = (unsigned char *)r->command; *p; p++)
        if (*p < 32 || *p > 126)
            return -1;
    return 0;
}

/* A timeout leaves the descriptor and its framing state intact. Idle finals
 * may synchronize it; otherwise only two named, read-only recovery replies do. */
struct capture {
    char *answer;
    size_t used;
    bool done, payload, rejected;
    const char *probe;
};
static int line(struct capture *c, char *s)
{
    if (!*s)
        return 0;
    if (!c) {
        if (final(s))
            synchronized = true;
        return 0;
    }
    if (c->probe) {
        int a, b;
        char tail;
        if ((!strcmp(c->probe, "CFUN") && sscanf(s, "+CFUN: %d %c", &a, &tail) == 1 && a >= 0) ||
            (!strcmp(c->probe, "CSQ") && sscanf(s, "+CSQ: %d,%d %c", &a, &b, &tail) == 2 &&
             a >= 0 && b >= 0))
            c->payload = true;
        else if (c->payload && final(s)) {
            c->rejected = strcmp(s, "OK") != 0;
            c->done = true;
        }
    } else {
        size_t n = strlen(s);
        if (c->used + n + 1 > LIMIT)
            return -1;
        memcpy(c->answer + c->used, s, n);
        c->used += n;
        c->answer[c->used++] = '\n';
        c->answer[c->used] = 0;
        if (final(s))
            c->done = true;
    }
    return 0;
}
static int read_lines(struct capture *c, int wait_ms)
{
    struct pollfd p = {modem, POLLIN, 0};
    int rc = poll(&p, 1, wait_ms);
    if (rc < 0)
        return errno == EINTR ? 0 : -1;
    if (!rc)
        return 0;
    char buf[4096];
    ssize_t n = read(modem, buf, sizeof(buf));
    // SIPC's empty nonblocking read may be EAGAIN/ENODATA; neither permits a reopen.
    if (n < 0 && (errno == EAGAIN || errno == ENODATA)) {
        poll(NULL, 0, 10);
        return 0;
    }
    if (n <= 0)
        return -1;
    for (ssize_t i = 0; i < n; i++) {
        if (buf[i] == '\n') {
            while (partial_used && partial[partial_used - 1] == '\r')
                partial_used--;
            partial[partial_used] = 0;
            if (line(c, partial))
                return -1;
            partial_used = 0;
            if (c && c->done)
                return 0;
        } else {
            if (!buf[i] || partial_used == LIMIT)
                return -1;
            partial[partial_used++] = buf[i];
        }
    }
    return 0;
}
static int transmit(const char *command)
{
    pause_until(last_write + .05);
    if (stopping)
        return -1;
    synchronized = false;
    last_write = now();
    size_t size = strlen(command);
    ssize_t n = write(modem, command, size);
    if (n != (ssize_t)size) {
        fputs("AT short write; not retried\n", stderr);
        return -1;
    }
    return 0;
}
static int recover(void)
{
    if (read_lines(NULL, 0))
        return -1;
    if (synchronized)
        return 0;
    if (failed_at && now() - failed_at < 2)
        return 1;
    for (int i = 0; i < 2; i++) {
        if (read_lines(NULL, 0))
            return -1;
        struct capture c = {.probe = i ? "CSQ" : "CFUN"};
        if (transmit(i ? "AT+CSQ\r" : "AT+CFUN?\r"))
            return -1;
        double until = now() + 3;
        while (!stopping && !c.done && now() < until)
            if (read_lines(&c, (int)((until - now()) * 1000) + 1))
                return -1;
        if (!c.done || c.rejected) {
            failed_at = now();
            return 1;
        }
    }
    synchronized = true;
    failed_at = 0;
    return 0;
}
static int command(struct request *r, char *answer)
{
    if (read_lines(NULL, 0))
        return -1;
    if (!synchronized)
        return 1;
    char card[32], payload[1100];
    if (text("/sys/module/sipc_wwan/parameters/card", card, sizeof(card)))
        return -1;
    if ((card[0] != '0' && card[0] != '1') || (card[1] != '\n' && card[1] != 0))
        return -1;
    if (!strncasecmp(r->command, "AT+", 3) && strncasecmp(r->command, "AT+SPACTCARD", 12))
        snprintf(payload, sizeof(payload), "AT+SPACTCARD=%c;%s\r", card[0], r->command + 2);
    else
        snprintf(payload, sizeof(payload), "%s\r", r->command);
    pause_until(last_write + .05);
    if (now() >= r->deadline)
        return 2;
    if (transmit(payload))
        return -1;
    struct capture c = {.answer = answer};
    double until = now() + r->timeout;
    while (!stopping && !c.done && now() < until)
        if (read_lines(&c, (int)((until - now()) * 1000) + 1))
            return -1;
    if (!c.done) {
        failed_at = now();
        return 1;
    }
    synchronized = true;
    failed_at = 0;
    return 0;
}
static int send_all(int fd, const char *p, size_t size)
{
    while (size) {
        ssize_t n = send(fd, p, size, MSG_NOSIGNAL);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            return -1;
        p += n;
        size -= n;
    }
    return 0;
}
static size_t utf8_sequence(const unsigned char *p)
{
    if (*p < 128)
        return 1;
    size_t n = *p >= 0xc2 && *p <= 0xdf   ? 2
               : *p >= 0xe0 && *p <= 0xef ? 3
               : *p >= 0xf0 && *p <= 0xf4 ? 4
                                          : 0;
    if (!n)
        return 0;
    for (size_t i = 1; i < n; i++)
        if (!p[i] || (p[i] & 0xc0) != 0x80)
            return 0;
    if ((*p == 0xe0 && p[1] < 0xa0) || (*p == 0xed && p[1] >= 0xa0) ||
        (*p == 0xf0 && p[1] < 0x90) || (*p == 0xf4 && p[1] >= 0x90))
        return 0;
    return n;
}
static void body(FILE *f, const char *s, bool json)
{
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        size_t n = utf8_sequence(p);
        if (!n) {
            fputs(json ? "\\ufffd" : "\xef\xbf\xbd", f);
            continue;
        }
        if (n > 1) {
            fwrite(p, 1, n, f);
            p += n - 1;
        } else if (json && (*p == '"' || *p == '\\'))
            fprintf(f, "\\%c", *p);
        else if (json && *p < 32)
            fprintf(f, "\\u%04x", *p);
        else
            fputc(*p, f);
    }
}
static void quoted(FILE *f, const char *s)
{
    fputc('"', f);
    body(f, s, true);
    fputc('"', f);
}
static void reply(int fd, struct request *r, bool ok, const char *value)
{
    char *out = NULL;
    size_t size = 0;
    FILE *f = open_memstream(&out, &size);
    if (!f)
        return;
    if (r->plain) {
        fprintf(f, "%c\n", ok ? '0' : '1');
        body(f, value, false);
    } else {
        fprintf(f, "{\"ok\":%s,\"%s\":", ok ? "true" : "false", ok ? "response" : "error");
        quoted(f, value);
        fputs("}\n", f);
    }
    fclose(f);
    send_all(fd, out, size);
    free(out);
}
static int serve_client(int fd)
{
    struct timeval tv = {1, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    char request[4097];
    size_t used = 0;
    struct request r = {0};
    double until = now() + 1;
    while (used < 4096 && now() < until && !stopping) {
        ssize_t n = recv(fd, request + used, 4096 - used, 0);
        if (n <= 0) {
            if (n < 0 && errno == EINTR)
                continue;
            reply(fd, &r, false, "Incomplete request");
            return 0;
        }
        used += n;
        if (memchr(request, '\n', used))
            break;
    }
    request[used] = 0;
    char *end = strchr(request, '\n');
    if (!end) {
        reply(fd, &r, false, "Request too large or incomplete");
        return 0;
    }
    *end = 0;
    if (parse(request, &r)) {
        reply(fd, &r, false, "Invalid or expired AT request");
        return 0;
    }
    char probe;
    ssize_t available = recv(fd, &probe, 1, MSG_PEEK | MSG_DONTWAIT);
    if (!available)
        return 0;
    int rc = synchronized ? 0 : recover();
    if (rc < 0)
        return -1;
    if (rc) {
        reply(fd, &r, false, "Previous AT command has not finished; channel quarantined");
        return 0;
    }
    if (now() >= r.deadline) {
        reply(fd, &r, false, "Request expired before execution");
        return 0;
    }
    char *answer = calloc(1, LIMIT + 1);
    if (!answer)
        return -1;
    rc = command(&r, answer);
    if (rc >= 0)
        reply(fd, &r, rc == 0,
              rc == 2 ? "Request expired before execution"
              : rc    ? "Modem returned no final response; awaiting late reply"
                      : answer);
    free(answer);
    return rc < 0 ? -1 : 0;
}
int main(int argc, char **argv)
{
    int nr = 2;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--serve"))
            continue;
        if (!strcmp(argv[i], "--channel") && i + 1 < argc) {
            char *end;
            nr = (int)strtol(argv[++i], &end, 10);
            if (*end)
                return 2;
        } else {
            fputs("usage: t551m-atd --serve --channel 2|6|7\n", stderr);
            return 2;
        }
    }
    if (nr != 2 && nr != 6 && nr != 7)
        return 2;
    root = getenv("E5_AT_ROOT") ? getenv("E5_AT_ROOT") : "";
    umask(0077);
    signal(SIGINT, stop);
    signal(SIGTERM, stop);
    signal(SIGPIPE, SIG_IGN);
    char directory[512], suffix[128], p[512];
    snprintf(suffix, sizeof(suffix), "/run/t551m-at%d", nr);
    path(directory, sizeof(directory), suffix);
    if (mkdir(directory, 0700) && errno != EEXIST) {
        perror("AT runtime");
        return 1;
    }
    if (snprintf(p, sizeof(p), "%s/owner.lock", directory) >= (int)sizeof(p))
        return 1;
    int owner = open(p, O_WRONLY | O_CREAT | O_CLOEXEC, 0600);
    if (owner < 0 || flock(owner, LOCK_EX | LOCK_NB)) {
        perror("AT owner lock");
        return 1;
    }
    // kernfs creation/removal is announced by kobject uevents. Do not rely
    // solely on inotify (which also observes ordinary-file test fixtures).
    kernel_events =
        socket(AF_NETLINK, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, NETLINK_KOBJECT_UEVENT);
    struct sockaddr_nl kernel_address = {.nl_family = AF_NETLINK, .nl_groups = 1};
    if (kernel_events < 0 || bind(kernel_events, (void *)&kernel_address, sizeof(kernel_address))) {
        perror("AT WWAN uevents");
        return 1;
    }
    path(p, sizeof(p), "/sys/class/wwan");
    notifier = inotify_init1(IN_CLOEXEC | IN_NONBLOCK);
    if (notifier < 0 || inotify_add_watch(notifier, p,
                                          IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO |
                                              IN_DELETE_SELF) < 0) {
        perror("AT WWAN watch");
        return 1;
    }
    path(p, sizeof(p), "/sys/class/wwan/wwan0at0");
    struct stat generation;
    double until = now() + 120;
    while (stat(p, &generation) && !stopping && now() < until) {
        struct pollfd wait = {notifier, POLLIN, 0};
        poll(&wait, 1, 200);
        char discard[4096];
        while (read(notifier, discard, sizeof(discard)) > 0) {
        }
    }
    if (stopping || stat(p, &generation)) {
        fputs("AT WWAN port not ready after 120 seconds\n", stderr);
        return 1;
    }
    for (int i = 0; i < 3; i++) {
        char value[128];
        const char *name = i == 0 ? "cmd_ring" : i == 1 ? "urc_ring" : "drain_rings";
        snprintf(suffix, sizeof(suffix), "/sys/module/sipc_wwan/parameters/%s", name);
        if (text(suffix, value, sizeof(value))) {
            fputs("AT ownership metadata unavailable\n", stderr);
            return 1;
        }
        int count = 0;
        char *save = NULL;
        for (char *n = strtok_r(value, ", \n", &save); n; n = strtok_r(NULL, ", \n", &save)) {
            char *end;
            errno = 0;
            long ring = strtol(n, &end, 10);
            count++;
            if (errno || *end || (ring < 0 && !(i == 1 && ring == -1)) || ring > 31) {
                fputs("AT ownership metadata invalid\n", stderr);
                return 1;
            }
            if (ring == nr) {
                fputs("AT ring belongs to sipc_wwan\n", stderr);
                return 1;
            }
        }
        if (i < 2 && count != 1) {
            fputs("AT ownership metadata incomplete\n", stderr);
            return 1;
        }
    }
    snprintf(suffix, sizeof(suffix), "/dev/stty_nr%d", nr);
    path(p, sizeof(p), suffix);
    modem = open(p, O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
    if (modem < 0) {
        perror("AT open");
        return 1;
    }
    struct termios tty;
    if (!tcgetattr(modem, &tty)) {
        cfmakeraw(&tty);
        if (tcsetattr(modem, TCSANOW, &tty))
            return 1;
    }
    // Match the original single initial drain; never add it to successful reads.
    until = now() + 3;
    while (now() < until && !stopping) {
        struct pollfd wait = {modem, POLLIN, 0};
        int rc = poll(&wait, 1, 1000);
        if (!rc)
            break;
        if (rc < 0 && errno == EINTR)
            continue;
        if (rc < 0 || read_lines(NULL, 0))
            return 1;
    }
    if (snprintf(endpoint, sizeof(endpoint), "%s/cmd.sock", directory) >= (int)sizeof(endpoint))
        return 1;
    server = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    strcpy(addr.sun_path, endpoint);
    unlink(endpoint);
    if (server < 0 || bind(server, (void *)&addr, sizeof(addr)) || listen(server, 8)) {
        perror("AT socket");
        return 1;
    }
    printf("t551m-atd: nr%d open; independent queue, 50ms pacing\n", nr);
    fflush(stdout);
    int rc = 0;
    while (!stopping) {
        path(p, sizeof(p), "/sys/class/wwan/wwan0at0");
        struct stat current;
        if (stat(p, &current) || current.st_ino != generation.st_ino ||
            current.st_dev != generation.st_dev) {
            fputs("AT CP channel generation changed\n", stderr);
            rc = 1;
            break;
        }
        struct pollfd waits[4] = {{server, POLLIN, 0},
                                  {modem, POLLIN, 0},
                                  {notifier, POLLIN, 0},
                                  {kernel_events, POLLIN, 0}};
        if (poll(waits, 4, -1) < 0) {
            if (errno == EINTR)
                continue;
            rc = 1;
            break;
        }
        if (waits[3].revents) {
            char event[16384];
            struct sockaddr_nl sender;
            socklen_t size = sizeof(sender);
            ssize_t n = recvfrom(kernel_events, event, sizeof(event), 0, (void *)&sender, &size);
            if (n > 0 && size >= sizeof(sender) && sender.nl_pid == 0 &&
                memmem(event, (size_t)n, "SUBSYSTEM=wwan", 14))
                continue;
        }
        if (waits[2].revents) {
            char discard[4096];
            while (read(notifier, discard, sizeof(discard)) > 0) {
            }
            continue;
        }
        if (waits[1].revents && read_lines(NULL, 0)) {
            rc = 1;
            break;
        }
        if (waits[0].revents) {
            int client = accept4(server, NULL, NULL, SOCK_CLOEXEC);
            if (client < 0)
                continue;
            int result = serve_client(client);
            close(client);
            if (result) {
                rc = 1;
                break;
            }
        }
    }
    unlink(endpoint);
    close(server);
    close(modem);
    close(notifier);
    close(kernel_events);
    close(owner);
    return rc;
}
