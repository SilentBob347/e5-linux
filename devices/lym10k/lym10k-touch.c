// SPDX-License-Identifier: GPL-2.0-only
/* LYM-10K factory hynitron,hyn_ts node; CST8xx register protocol.
 * No firmware upload, address rewriting or binding to the TLSC6x node.
 * See README.md for the stock binary and DT evidence.
 */
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/input/mt.h>
#include <linux/input/touchscreen.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/pm.h>
#include <linux/property.h>

#include "touch-packet.h"

struct lym_touch {
	struct i2c_client *client;
	struct gpio_desc *reset;
	struct gpio_desc *irq_gpio;
	struct input_dev *input;
	struct touchscreen_properties props;
};

static void lym_reset(struct lym_touch *ts)
{
	/* Stock hyn_reset_proc: physical low for 20 ms, high then 40 ms. */
	gpiod_set_value_cansleep(ts->reset, 1);
	msleep(20);
	gpiod_set_value_cansleep(ts->reset, 0);
	msleep(40);
}

static irqreturn_t lym_touch_irq(int irq, void *data)
{
	struct lym_touch *ts = data;
	u8 reg, packet[LYM_PACKET_BYTES];
	struct lym_point points[LYM_TOUCH_SLOTS];
	struct i2c_msg msgs[] = {
		{ .addr = ts->client->addr, .len = 1, .buf = &reg },
		{ .addr = ts->client->addr, .flags = I2C_M_RD,
		  .len = 5, .buf = packet },
	};
	int count, i, ret;

	/* Mirror cst8xx_touch_report's 0/5/10 register reads. Some controller
	 * firmware limits each transfer; do not assume one 15-byte burst works.
	 */
	for (reg = 0; reg < sizeof(packet); reg += 5) {
		msgs[1].buf = packet + reg;
		ret = i2c_transfer(ts->client->adapter, msgs, ARRAY_SIZE(msgs));
		if (ret != ARRAY_SIZE(msgs)) {
			dev_err_ratelimited(&ts->client->dev, "touch read failed: %d\n", ret);
			return IRQ_HANDLED;
		}
	}
	count = lym_decode_touch(packet, points);
	if (count < 0)
		return IRQ_HANDLED;
	for (i = 0; i < count; i++) {
		if (points[i].x > ts->props.max_x || points[i].y > ts->props.max_y)
			continue;
		input_mt_slot(ts->input, points[i].id);
		input_mt_report_slot_state(ts->input, MT_TOOL_FINGER, true);
		touchscreen_report_pos(ts->input, &ts->props,
				       points[i].x, points[i].y, true);
	}
	input_mt_sync_frame(ts->input);
	input_mt_report_pointer_emulation(ts->input, true);
	input_sync(ts->input);
	return IRQ_HANDLED;
}

static int lym_touch_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct lym_touch *ts;
	u32 size[2];
	int error;

	if (client->addr != 0x15 || !i2c_check_functionality(client->adapter, I2C_FUNC_I2C))
		return -ENODEV;
	ts = devm_kzalloc(dev, sizeof(*ts), GFP_KERNEL);
	if (!ts)
		return -ENOMEM;
	ts->client = client;
	i2c_set_clientdata(client, ts);
	ts->reset = devm_gpiod_get(dev, "hynitron,reset", GPIOD_OUT_HIGH);
	if (IS_ERR(ts->reset))
		return dev_err_probe(dev, PTR_ERR(ts->reset), "reset GPIO unavailable\n");
	ts->irq_gpio = devm_gpiod_get(dev, "hynitron,irq", GPIOD_IN);
	if (IS_ERR(ts->irq_gpio))
		return dev_err_probe(dev, PTR_ERR(ts->irq_gpio), "IRQ GPIO unavailable\n");
	client->irq = gpiod_to_irq(ts->irq_gpio);
	if (client->irq < 0)
		return client->irq;
	error = device_property_read_u32_array(dev, "hynitron,display-coords", size, 2);
	if (error || !size[0] || !size[1] || size[0] > 4095 || size[1] > 4095)
		return dev_err_probe(dev, -EINVAL, "invalid touch dimensions\n");
	lym_reset(ts);
	/* A readable factory firmware ID confirms a responding controller.
	 * The stock project selects its ID table internally; do not invent a list.
	 * cst8xx_firmware_info waits 100 ms before its A6 read.
	 */
	msleep(100);
	error = i2c_smbus_read_byte_data(client, 0xa6);
	if (error < 0)
		return dev_err_probe(dev, error, "controller did not respond\n");
	ts->input = devm_input_allocate_device(dev);
	if (!ts->input)
		return -ENOMEM;
	ts->input->name = "LYM-10K Hynitron Touchscreen";
	ts->input->id.bustype = BUS_I2C;
	input_set_abs_params(ts->input, ABS_MT_POSITION_X, 0, size[0], 0, 0);
	input_set_abs_params(ts->input, ABS_MT_POSITION_Y, 0, size[1], 0, 0);
	touchscreen_parse_properties(ts->input, true, &ts->props);
	error = input_mt_init_slots(ts->input, LYM_TOUCH_SLOTS,
				    INPUT_MT_DIRECT | INPUT_MT_DROP_UNUSED);
	if (error)
		return error;
	error = input_register_device(ts->input);
	if (error)
		return error;
	return devm_request_threaded_irq(dev, client->irq, NULL, lym_touch_irq,
					IRQF_ONESHOT | IRQF_TRIGGER_FALLING,
					dev_name(dev), ts);
}

static int lym_touch_suspend(struct device *dev)
{
	struct lym_touch *ts = dev_get_drvdata(dev);
	int error;

	disable_irq(ts->client->irq);
	error = i2c_smbus_write_byte_data(ts->client, 0xa5, 3);
	if (error) {
		enable_irq(ts->client->irq);
		return error;
	}
	input_mt_sync_frame(ts->input);
	input_mt_report_pointer_emulation(ts->input, true);
	input_sync(ts->input);
	return 0;
}

static int lym_touch_resume(struct device *dev)
{
	struct lym_touch *ts = dev_get_drvdata(dev);

	lym_reset(ts);
	enable_irq(ts->client->irq);
	return 0;
}

static DEFINE_SIMPLE_DEV_PM_OPS(lym_touch_pm, lym_touch_suspend, lym_touch_resume);
static const struct of_device_id lym_touch_of[] = {
	{ .compatible = "hynitron,hyn_ts" },
	{ }
};
MODULE_DEVICE_TABLE(of, lym_touch_of);
static struct i2c_driver lym_touch_driver = {
	.driver = {
		.name = "lym10k-touch",
		.of_match_table = lym_touch_of,
		.pm = pm_sleep_ptr(&lym_touch_pm),
	},
	.probe = lym_touch_probe,
};
module_i2c_driver(lym_touch_driver);
MODULE_DESCRIPTION("LYM-10K factory Hynitron touchscreen");
MODULE_LICENSE("GPL");
