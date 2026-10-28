// SPDX-License-Identifier: GPL-2.0-only
/* AXS15205 RAM-only SPI protocol, based on AiXieSheng's GPLv2 axs_touch
 * (2020-2021), and P720S20 stock DT/firmware. No flash-update interface.
 */
#include <linux/delay.h>
#include <linux/firmware.h>
#include <linux/gpio/consumer.h>
#include <linux/input/mt.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/notifier.h>
#include <linux/of.h>
#include <linux/spi/spi.h>
#include <linux/workqueue.h>
#include <linux/unaligned.h>
#include <linux/input/sprd_touch_panel.h>

#define AXS_FW "axs15205/easyquick.bin"
#define AXS_CONTACTS 5
/* Stock zte_tpd.ko stores 0x20 in pnt_buf_size at axs_ts_probe+0x76c.
 * The extra byte in the allocation is not part of the SPI report. */
#define AXS_PACKET (AXS_CONTACTS * 6 + 2)
#define AXS_CHUNK 256
#define AXS_XFER_MAX (AXS_CHUNK + 16)

static bool verify_pram;
module_param(verify_pram, bool, 0400);
MODULE_PARM_DESC(verify_pram, "Diagnostic readback of the complete RAM firmware");

struct axs_touch {
    struct spi_device *spi;
    struct input_dev *input;
    struct gpio_desc *reset, *irq_gpio;
    const struct firmware *fw;
    struct mutex state_lock, bus_lock;
    struct notifier_block panel;
    struct delayed_work esd;
    bool running, display_on, suspended;
    unsigned int ff_count;
    unsigned int reports_logged;
    unsigned long last_irq;
    u8 *tx, *rx;
};

/* Both directions clock bytes, as the factory full-duplex SPI driver does. */
static int axs_transfer(struct axs_touch *ts, const u8 *data, size_t length)
{
    struct spi_transfer xfer = { .tx_buf=ts->tx, .rx_buf=ts->rx, .len=length };
    if (!length || length>AXS_XFER_MAX)
        return -EINVAL;
    if (data)
        memcpy(ts->tx,data,length);
    else
        memset(ts->tx,0,length);
    memset(ts->rx,0,length);
    return spi_sync_transfer(ts->spi,&xfer,1);
}

/* The factory protocol reads PRAM with one CS, 11 command bytes and five
 * dummy bytes. This is a diagnostic check before the execution marker, not
 * a substitute for the version and touch-interrupt checks. */
static int axs_check_pram(struct axs_touch *ts, u32 offset, unsigned int count)
{
    u8 command[AXS_XFER_MAX] = { 0xab, 0xb5, 0xa5, 0x5a, 0, 3 };
    int ret;

    command[6] = (count + 5) >> 8;
    command[7] = count + 5;
    command[8] = offset >> 16;
    command[9] = offset >> 8;
    command[10] = offset;
    ret = axs_transfer(ts, command, 11 + 5 + count);
    if (ret) {
        dev_warn(&ts->spi->dev, "PRAM read %06x failed: %d\n", offset, ret);
        return ret;
    }
    if (memcmp(ts->rx + 16, ts->fw->data + offset, count)) {
        dev_warn(&ts->spi->dev,
                 "PRAM %06x mismatch (expected %*phN, read %*phN)\n",
                 offset, 16, ts->fw->data + offset, 16, ts->rx + 16);
        return -EIO;
    }
    return 0;
}

static int axs_download(struct axs_touch *ts)
{
    const u8 select[]={0xa5,0x5a,0xb5,0xab,1};
    const u8 finish[]={0xab,0xb5,0xa5,0x5a,0,0,0,0};
    const u8 version[]={0x0c};
    u8 packet[AXS_CHUNK+11];
    unsigned int offset;
    unsigned int bad=0, blocks=0;
    int ret;

    if (ts->fw->size<1024 || ts->fw->size>128*1024)
        return -EINVAL;
    gpiod_set_value_cansleep(ts->reset,0);
    msleep(1);
    ret=axs_transfer(ts,select,sizeof(select));
    gpiod_set_value_cansleep(ts->reset,1);
    if (ret)
        return ret;
    msleep(15);
    for (offset=0;offset<ts->fw->size;offset+=AXS_CHUNK) {
        unsigned int count=min_t(size_t,AXS_CHUNK,ts->fw->size-offset);
        memset(packet,0,11);
        memcpy(packet,finish,4);
        packet[4]=(count+3)>>8;packet[5]=count+3;
        packet[8]=offset>>16;packet[9]=offset>>8;packet[10]=offset;
        memcpy(packet+11,ts->fw->data+offset,count);
        ret=axs_transfer(ts,packet,count+11);
        if (ret)
            return ret;
    }
    for (offset=0;verify_pram && offset<ts->fw->size;offset+=AXS_CHUNK) {
        unsigned int count=min_t(size_t,AXS_CHUNK,ts->fw->size-offset);
        ret=axs_check_pram(ts,offset,count);
        blocks++;
        if (ret)
            bad++;
        if (bad>=3)
            break;
    }
    if (verify_pram)
        dev_info(&ts->spi->dev,"PRAM checked %u/%zu blocks, %u bad\n",
                 blocks,DIV_ROUND_UP(ts->fw->size,AXS_CHUNK),bad);
    if (bad)
        return -EIO;
    ret=axs_transfer(ts,finish,sizeof(finish));
    if (ret)
        return ret;
    msleep(20);
    {
        u16 expected=get_unaligned_be16(ts->fw->data+0x5034);
        u16 actual;
        ret=axs_transfer(ts,version,sizeof(version));
        if (!ret) {
            /* P720S20 R22: an immediate second CS reads the previous
             * response; allow the firmware to prepare the version. */
            usleep_range(1000, 1500);
            ret=axs_transfer(ts,NULL,2);
        }
        if (!ret) {
            actual=get_unaligned_be16(ts->rx);
            dev_info(&ts->spi->dev,"RAM firmware version %04x (image %04x)\n",
                     actual,expected);
            if (actual!=expected)
                ret=-EIO;
        }
    }
    return ret;
}

static void axs_release(struct axs_touch *ts)
{
    unsigned int i;
    for (i=0;i<AXS_CONTACTS;i++) {
        input_mt_slot(ts->input,i);
        input_mt_report_slot_state(ts->input,MT_TOOL_FINGER,false);
    }
    input_mt_sync_frame(ts->input);
    input_sync(ts->input);
}

static irqreturn_t axs_irq(int irq, void *data)
{
    struct axs_touch *ts=data;
    u8 report[AXS_PACKET];
    unsigned long seen=0;
    unsigned int i,count;

    mutex_lock(&ts->bus_lock);
    if (axs_transfer(ts,NULL,sizeof(report)))
        goto out;
    WRITE_ONCE(ts->last_irq,jiffies);
    memcpy(report,ts->rx,sizeof(report));
    if (verify_pram && ts->reports_logged++ < 4)
        dev_info(&ts->spi->dev, "diagnostic report: %8phN\n", report);
    ts->ff_count=report[0]==0xff ? ts->ff_count+1 : 0;
    if (((report[0]&0xe0) && !(report[0]&~0xe0)) || ts->ff_count>=3) {
        dev_warn_ratelimited(&ts->spi->dev,
                             "touch controller ESD report: %8phN\n", report);
        sprd_touch_panel_report_esd();
        axs_release(ts);
        goto out;
    }
    if ((report[0]&0xf0) || (report[0]&0x08) || (report[1]&0xf0))
        goto out;
    count=report[1]&0x0f;
    if (count>AXS_CONTACTS)
        goto out;
    /* Validate the whole report before emitting any partial frame. */
    for (i=0;i<count;i++) {
        unsigned int n=i*6, id=report[n+4]>>4, flag=report[n+2]>>6;
        unsigned int x=((report[n+2]&15)<<8)|report[n+3];
        unsigned int y=((report[n+4]&15)<<8)|report[n+5];
        if (id>=AXS_CONTACTS || test_and_set_bit(id,&seen) || flag>2 ||
            (flag!=1 && (x>=480 || y>=854)))
            goto out;
    }
    for (i=0;i<count;i++) {
        unsigned int n=i*6, id=report[n+4]>>4, flag=report[n+2]>>6;
        input_mt_slot(ts->input,id);
        input_mt_report_slot_state(ts->input,MT_TOOL_FINGER,flag!=1);
        if (flag!=1) {
            input_report_abs(ts->input,ABS_MT_POSITION_X,((report[n+2]&15)<<8)|report[n+3]);
            input_report_abs(ts->input,ABS_MT_POSITION_Y,((report[n+4]&15)<<8)|report[n+5]);
        }
    }
    input_mt_sync_frame(ts->input);
    input_sync(ts->input);
out:
    mutex_unlock(&ts->bus_lock);
    return IRQ_HANDLED;
}

static void axs_esd(struct work_struct *work)
{
    struct axs_touch *ts=container_of(to_delayed_work(work),struct axs_touch,esd);
    if (!READ_ONCE(ts->running))
        return;
    /* Stock expects a touch/heartbeat interrupt at least every 1.5 s. */
    if (time_after_eq(jiffies,READ_ONCE(ts->last_irq)+msecs_to_jiffies(1500))) {
        dev_warn_ratelimited(&ts->spi->dev, "touch heartbeat timeout\n");
        WRITE_ONCE(ts->last_irq,jiffies);
        sprd_touch_panel_report_esd();
    }
    if (READ_ONCE(ts->running))
        schedule_delayed_work(&ts->esd,msecs_to_jiffies(500));
}

/* state_lock serializes PM, panel events and remove. IRQ/work only use
 * bus_lock/atomic reporting, so joining them never waits on panel locks. */
static void axs_stop(struct axs_touch *ts)
{
    if (!ts->running)
        return;
    WRITE_ONCE(ts->running,false);
    disable_irq(ts->spi->irq);
    cancel_delayed_work_sync(&ts->esd);
    mutex_lock(&ts->bus_lock);
    axs_release(ts);
    mutex_unlock(&ts->bus_lock);
}

static int axs_start(struct axs_touch *ts)
{
    int ret;
    if (ts->running || ts->suspended || !ts->display_on)
        return 0;
    mutex_lock(&ts->bus_lock);
    ret=axs_download(ts);
    mutex_unlock(&ts->bus_lock);
    if (ret)
        return ret;
    ts->ff_count=0;
    ts->reports_logged=0;
    WRITE_ONCE(ts->last_irq,jiffies);
    WRITE_ONCE(ts->running,true);
    enable_irq(ts->spi->irq);
    schedule_delayed_work(&ts->esd,msecs_to_jiffies(1000));
    return 0;
}

static int axs_panel(struct notifier_block *nb,unsigned long on,void *unused)
{
    struct axs_touch *ts=container_of(nb,struct axs_touch,panel);
    int ret=0;
    mutex_lock(&ts->state_lock);
    ts->display_on=!!on;
    if (on)
        ret=axs_start(ts);
    else
        axs_stop(ts);
    mutex_unlock(&ts->state_lock);
    if (ret)
        dev_err(&ts->spi->dev,"panel resume failed: %d\n",ret);
    return notifier_from_errno(ret);
}

static void axs_cleanup(void *data)
{
    struct axs_touch *ts=data;
    sprd_touch_panel_unregister(&ts->panel);
    mutex_lock(&ts->state_lock);
    axs_stop(ts);
    mutex_unlock(&ts->state_lock);
}

static void axs_release_fw(void *data)
{
    release_firmware(data);
}

static int axs_probe(struct spi_device *spi)
{
    struct device *dev=&spi->dev;
    struct axs_touch *ts;
    int ret;

    ts=devm_kzalloc(dev,sizeof(*ts),GFP_KERNEL);
    if (!ts)
        return -ENOMEM;
    ts->spi=spi;
    mutex_init(&ts->state_lock);mutex_init(&ts->bus_lock);
    INIT_DELAYED_WORK(&ts->esd,axs_esd);
    spi_set_drvdata(spi,ts);
    ts->tx=devm_kzalloc(dev,AXS_XFER_MAX,GFP_KERNEL);
    ts->rx=devm_kzalloc(dev,AXS_XFER_MAX,GFP_KERNEL);
    if (!ts->tx || !ts->rx)
        return -ENOMEM;
    spi->bits_per_word=8;spi->mode=SPI_MODE_0;
    ret=spi_setup(spi);
    if (ret)
        return ret;
    ts->reset=devm_gpiod_get(dev,"touch,reset",GPIOD_OUT_HIGH);
    if (IS_ERR(ts->reset))
        return dev_err_probe(dev,PTR_ERR(ts->reset),"reset GPIO\n");
    /* P720S20's stock axs_ts_hw_init calls axs_reset_proc(120) before the
     * first RAM download: high, low for 10 ms, high for 120 ms. */
    usleep_range(1000, 2000);
    gpiod_set_value_cansleep(ts->reset, 0);
    usleep_range(10000, 11000);
    gpiod_set_value_cansleep(ts->reset, 1);
    msleep(120);
    ts->irq_gpio=devm_gpiod_get(dev,"touch,irq",GPIOD_IN);
    if (IS_ERR(ts->irq_gpio))
        return dev_err_probe(dev,PTR_ERR(ts->irq_gpio),"IRQ GPIO\n");
    spi->irq=gpiod_to_irq(ts->irq_gpio);
    if (spi->irq<0)
        return spi->irq;
    ret=request_firmware(&ts->fw,AXS_FW,dev);
    if (ret)
        return dev_err_probe(dev,ret,"own RAM firmware\n");
    if (ts->fw->size<=0x5035) {
        release_firmware(ts->fw);
        return -EINVAL;
    }
    ret=devm_add_action_or_reset(dev,axs_release_fw,(void *)ts->fw);
    if (ret)
        return ret;
    ts->input=devm_input_allocate_device(dev);
    if (!ts->input)
        return -ENOMEM;
    ts->input->name="AXS15205";ts->input->id.bustype=BUS_SPI;
    input_set_abs_params(ts->input,ABS_MT_POSITION_X,0,479,0,0);
    input_set_abs_params(ts->input,ABS_MT_POSITION_Y,0,853,0,0);
    ret=input_mt_init_slots(ts->input,AXS_CONTACTS,INPUT_MT_DIRECT|INPUT_MT_DROP_UNUSED);
    if (ret)
        return ret;
    ret=devm_request_threaded_irq(dev,spi->irq,NULL,axs_irq,
        IRQF_ONESHOT|IRQF_TRIGGER_FALLING|IRQF_NO_AUTOEN,dev_name(dev),ts);
    if (ret)
        return ret;
    ret=input_register_device(ts->input);
    if (ret)
        return ret;
    ts->panel.notifier_call=axs_panel;
    ret=sprd_touch_panel_register(&ts->panel);
    if (ret)
        return ret;
    ret=devm_add_action_or_reset(dev,axs_cleanup,ts);
    if (ret)
        return ret;
    return notifier_to_errno(axs_panel(&ts->panel,sprd_touch_panel_active(),NULL));
}

static int axs_suspend(struct device *dev)
{
    struct axs_touch *ts=dev_get_drvdata(dev);
    mutex_lock(&ts->state_lock);ts->suspended=true;axs_stop(ts);
    mutex_unlock(&ts->state_lock);
    return 0;
}

static int axs_resume(struct device *dev)
{
    struct axs_touch *ts=dev_get_drvdata(dev);
    int ret;
    mutex_lock(&ts->state_lock);ts->suspended=false;ret=axs_start(ts);
    mutex_unlock(&ts->state_lock);
    return ret;
}

static DEFINE_SIMPLE_DEV_PM_OPS(axs_pm,axs_suspend,axs_resume);
static const struct of_device_id axs_match[]={
    { .compatible="axs15205,axs15205_touch" },{}
};
MODULE_DEVICE_TABLE(of,axs_match);
static const struct spi_device_id axs_ids[]={ { "axs15205_touch" },{} };
MODULE_DEVICE_TABLE(spi,axs_ids);
static struct spi_driver axs_driver={
    .driver={ .name="axs15205-ram",.of_match_table=axs_match,.pm=pm_sleep_ptr(&axs_pm) },
    .probe=axs_probe,.id_table=axs_ids,
};
module_spi_driver(axs_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("P720S20 AXS15205 RAM-download SPI touchscreen");
MODULE_FIRMWARE(AXS_FW);
