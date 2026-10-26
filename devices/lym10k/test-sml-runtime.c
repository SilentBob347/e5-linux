/* SPDX-License-Identifier: GPL-2.0-only */
/* Run only the audited SML's RAM-only flag decoder and selector arithmetic
 * inside an emulated AArch64 user process. No SMC or hardware MMIO is invoked.
 */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

struct table { uint16_t *values; uint32_t count, reserved; };

int main(int argc, char **argv)
{
    uint8_t *base;
    FILE *file;
    uint16_t cpu[16], sram[16];
    struct table a = {cpu, 16, 0}, b = {sram, 16, 0};
    unsigned cases = 0;
    void (*decode)(uint32_t);
    void (*adjust)(struct table *, uint32_t);
    assert(argc == 2);
    file = fopen(argv[1], "rb");
    assert(file);
    /* The compiler harness is static; this is a free guest address. */
    base = mmap((void *)0xb0000000, 0x30000,
                PROT_READ | PROT_WRITE | PROT_EXEC,
                MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    assert(base == (void *)0xb0000000);
    assert(fseek(file, 512, SEEK_SET) == 0);
    assert(fread(base, 1, 0x25f90, file) == 0x25f90);
    fclose(file);
    __builtin___clear_cache((char *)base, (char *)base + 0x25f90);
    decode = (void (*)(uint32_t))(base + 0x6248);
    adjust = (void (*)(struct table *, uint32_t))(base + 0x4068);
    for (unsigned domain = 0; domain < 3; domain++) {
        for (unsigned byte = 0; byte < 256; byte++) {
            uint32_t *state[3];
            for (unsigned i = 0; i < 3; i++) {
                state[i] = (uint32_t *)(base + 0x28068 + 0x1c + i * 0x30);
                *state[i] = 0;
            }
            decode((byte << (8 + domain * 8)) | 0x7f);
            for (unsigned i = 0; i < 3; i++)
                assert(*state[i] == (i == domain && (byte & 127) <= 100 ? byte : 0));
            cases++;
        }
    }
    for (int uv = -50000; uv <= 25000; uv += 3125) {
        unsigned byte = abs(uv) / 1000 | (uv < 0 ? 128 : 0);
        unsigned step = ((byte & 127) * 1000 + 3124) / 3125;
        int delta = uv < 0 ? -(int)step : (int)step;
        for (unsigned i = 0; i < 16; i++) {
            cpu[i] = 200 + i;
            sram[i] = 300 + i;
        }
        adjust(&a, byte);
        adjust(&b, byte);
        for (unsigned i = 0; i < 16; i++) {
            assert(cpu[i] == 200 + i + delta);
            assert(sram[i] == 300 + i + delta);
        }
        cases++;
    }
    /* Original table helper ignores null tables and invalid entry counts. */
    adjust(NULL, 1);
    a.values = NULL;
    adjust(&a, 1);
    for (unsigned count = 0; count <= 17; count += 17) {
        a.values = cpu;
        a.count = count;
        cpu[0] = 200;
        adjust(&a, 1);
        assert(cpu[0] == 200);
    }
    assert(munmap(base, 0x30000) == 0);
    printf("SML RAM-only code PASS: %u flag/offset cases, paired CPU/SRAM tables\n", cases);
    return 0;
}
