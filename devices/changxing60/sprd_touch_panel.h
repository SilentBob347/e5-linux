/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _SPRD_TOUCH_PANEL_H
#define _SPRD_TOUCH_PANEL_H
#include <linux/notifier.h>
int sprd_touch_panel_register(struct notifier_block *nb);
int sprd_touch_panel_unregister(struct notifier_block *nb);
bool sprd_touch_panel_active(void);
void sprd_touch_panel_report_esd(void);
#endif
