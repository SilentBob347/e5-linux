/* SPDX-License-Identifier: GPL-2.0-only */
/* Stock cst8xx_touch_report reads 15 bytes and handles at most two contacts. */
#ifndef LYM10K_TOUCH_PACKET_H
#define LYM10K_TOUCH_PACKET_H
#define LYM_PACKET_BYTES 15
#define LYM_TOUCH_SLOTS 2
struct lym_point { unsigned int id, x, y; };
static inline int lym_decode_touch(const unsigned char *packet, struct lym_point *out)
{
	unsigned int seen = 0, count = packet[2] & 15;
	int i, used = 0;
	if (count > LYM_TOUCH_SLOTS)
		return -1;
	for (i = 0; i < count; i++) {
		const unsigned char *p = packet + 3 + i * 6;
		unsigned int id = p[2] >> 4, event = p[0] >> 6;
		if (id >= LYM_TOUCH_SLOTS || (seen & (1U << id)))
			return -1;
		seen |= 1U << id;
		if (event == 1)
			continue;
		if (event == 3)
			return -1;
		out[used].id = id;
		out[used].x = ((p[0] & 15) << 8) | p[1];
		out[used].y = ((p[2] & 15) << 8) | p[3];
		used++;
	}
	return used;
}
#endif
