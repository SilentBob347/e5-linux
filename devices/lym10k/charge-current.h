/* SPDX-License-Identifier: GPL-2.0-only */
/* LYM-10K-V32 bq2560x_charger_set_current @0x2d08:
 * REG0B & 3 == 1: 59/63/57.5 mA segments, limit 2875 mA.
 * Else (supported 0x12): 90/57 mA setter segments, limit 3047 mA.
 * These encode register requests, not a new current/JEITA policy.
 */
#ifndef LYM10K_CHARGE_CURRENT_H
#define LYM10K_CHARGE_CURRENT_H
static inline unsigned int lym_charge_code(unsigned int id, unsigned int ma)
{
	if ((id & 3) == 1) {
		if (ma > 2875) ma = 2875;
		if (ma < 59) return 0;
		if (ma <= 815) return (ma - 59) / 63 + 1;
		return (ma * 2 - 1610) / 115 + 14;
	}
	if (ma > 3047) ma = 3047;
	return ma <= 1170 ? ma / 90 : (ma - 805) / 57 + 14;
}
static inline unsigned int lym_charge_ma(unsigned int id, unsigned int code)
{
	if ((id & 3) == 1) {
		if (!code) return 0;
		if (code <= 13) return (code - 1) * 63 + 59;
	} else if (code <= 13) {
		return code * 90;
	}
	return (code - 14) * 115 / 2 + 805;
}
#endif
