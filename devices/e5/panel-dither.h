/* E5 ST7365P: RGB888 input, controller-side colour dithering. */
static void e5_st7365p_dither(struct sprd_panel *panel)
{
	static const u8 commands[][2] = {
		{ 0xf0, 0xc3 }, { 0xf0, 0x96 }, { 0xb9, 0x02 },
		{ 0xf0, 0x3c }, { 0xf0, 0x69 },
	};
	u8 reg = 0xb9, value = 0;
	ssize_t ret;
	int i;
	bool written = true;
	bool verified = false;

	if (!of_node_name_eq(panel->info.of_node, "lcd_st7365p_mipi_hdp"))
		return;
	panel->e5_dither_applied = false;

	/* Called under panel->lock, after INIT and before enabling backlight.
	 * Even a failed write must close the extended-command bank again.
	 */
	for (i = 0; i < ARRAY_SIZE(commands); i++) {
		if (i < 3 && !written)
			continue;
		if (panel->info.use_dcs)
			ret = mipi_dsi_dcs_write_buffer(panel->slave, commands[i], 2);
		else
			ret = mipi_dsi_generic_write(panel->slave, commands[i], 2);
		if (ret < 0) {
			DRM_WARN("E5 ST7365P dither command %d failed: %zd\n", i, ret);
			written = false;
		}
		if (i == 2 && written) {
			ret = mipi_dsi_set_maximum_return_packet_size(panel->slave, 1);
			if (ret < 0) {
				DRM_WARN("E5 ST7365P read size setup failed: %zd\n", ret);
				continue;
			}
			if (panel->info.use_dcs)
				ret = mipi_dsi_dcs_read(panel->slave, reg, &value, 1);
			else
				ret = mipi_dsi_generic_read(panel->slave, &reg, 1, &value, 1);
			if (ret != 1 || value != 0x02)
				DRM_WARN("E5 ST7365P B9 readback: ret=%zd value=%02x\n", ret, value);
			else
				verified = true;
		}
	}
	panel->e5_dither_applied = written && verified;
	if (panel->e5_dither_applied)
		DRM_INFO("E5 ST7365P B9=02 verified\n");
}

/* Initial boot adopts an already running DSI host and bypasses panel_enable.
 * Apply once there as well, under the same panel lock. The E5 stock host
 * starts in video mode with LP commands disabled; restore its configured
 * video command policy after this transaction.
 */
void sprd_panel_e5_dither_handoff(struct sprd_panel *panel)
{
	struct sprd_dsi *dsi;
	struct mipi_dsi_host *host;

	if (!of_node_name_eq(panel->info.of_node, "lcd_st7365p_mipi_hdp"))
		return;
	host = panel->slave->host;
	dsi = host_to_dsi(host);
	mutex_lock(&panel->lock);
	if (!panel->e5_dither_applied) {
		sprd_dsi_lp_cmd_enable(dsi, true);
		e5_st7365p_dither(panel);
		sprd_dsi_lp_cmd_enable(dsi, dsi->ctx.video_lp_cmd_en);
	}
	mutex_unlock(&panel->lock);
}
