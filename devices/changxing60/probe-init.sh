#!/bin/sh
# Bounded diagnostic init. No Android mount, GPT, NV or modem.
# Charger/FGU are loaded only by the explicitly selected --power-test image.
/bin/busybox mkdir -p /proc /sys /dev /tmp /run /bin /config
/bin/busybox mount -t proc proc /proc
/bin/busybox mount -t sysfs sysfs /sys
/bin/busybox mount -t devtmpfs devtmpfs /dev
/bin/busybox --install -s /bin
mkdir -p /dev/pts
mount -t devpts devpts /dev/pts
mount -t debugfs debugfs /sys/kernel/debug 2>/dev/null || :
log() { echo "CX60-PROBE: $*" | tee -a /tmp/probe.log >/dev/console; echo "CX60-PROBE: $*" >/dev/kmsg; }
log "PID1 reached: $(uname -a)"
# No daemon can extend this deliberately bounded trial. A kernel deadlock may
# still require physical recovery; software timeout is not that guarantee.
(sleep 180; reboot -f) &
. /e5-overlay/etc/storage.sh
export E5_UFS_ID_HELPER=/e5-overlay/usr/libexec/e5-ufs-id
expected=$(cat /e5-overlay/etc/storage-identity)
probe_verified=0
disk=
actual=
i=0
while [ "$i" -lt 30 ]; do
    disk=$(e5_storage_disk)
    actual=$(e5_storage_identity "$disk" 2>/tmp/storage-error.log)
    [ -n "$disk" ] && [ -n "$actual" ] && break
    sleep 1; i=$((i+1))
done
if [ -z "$disk" ] || [ "$(e5_storage_kind "$disk")" != ufs ] ||
   [ "$actual" != "$expected" ]; then
    log "UFS identity not confirmed: disk=$disk actual=$actual expected=$expected; no boot-control write"
    log "identity reader: $(cat /tmp/storage-error.log)"
else
    misc=$(e5_storage_part misc "$disk")
    if [ -n "$misc" ] && [ -b "/dev/$misc" ]; then
        # Restore exactly this trial's original 32 bytes; not a generated
        # default-A record. No GPT, boot payload or NV write from Linux.
        if dd if=/e5-overlay/etc/android-bc of="/dev/$misc" bs=1 seek=2048 count=32 conv=notrunc,fsync &&
           dd if="/dev/$misc" of=/tmp/bc-check bs=1 skip=2048 count=32 &&
           cmp -s /e5-overlay/etc/android-bc /tmp/bc-check; then
            log 'original Android boot control restored and verified'
            probe_verified=1
        else
            log 'boot-control restoration failed; keep backup for recovery'
        fi
    fi
fi
# Everything else is block-read-only, including the original NV partitions.
readonly_ok=1
for p in /sys/class/block/sd*; do
    [ -e "$p/dev" ] || continue
    blockdev --setro "/dev/${p##*/}" || { readonly_ok=0; log "read-only ioctl failed: ${p##*/}"; }
done
cat /proc/partitions >/tmp/partitions.txt
dmesg >/tmp/dmesg.txt
if [ -d /e5-overlay/lib/firmware ]; then
    mkdir -p /lib
    ln -s /e5-overlay/lib/firmware /lib/firmware
fi
for p in /sys/bus/platform/devices/*.ufs; do
    [ -e "$p" ] || continue
    {
        echo "$p"; readlink "$p/driver"
        for f in clkgate_enable clkgate_delay_ms rpm_lvl spm_lvl power/control; do echo "$f"; cat "$p/$f"; done
    } >/tmp/ufs.txt 2>&1
done
udc=
i=0
while [ "$i" -lt 40 ]; do
    set -- /sys/class/udc/*
    if [ "$#" = 1 ] && [ -e "$1" ]; then udc=${1##*/}; break; fi
    sleep 1; i=$((i+1))
done
if [ -n "$udc" ]; then
    mount -t configfs configfs /config
    # Shared USB controls address this standard gadget name after RAM handoff.
    g=/config/usb_gadget/linux
    mkdir -p "$g/strings/0x409" "$g/configs/c.1/strings/0x409" "$g/functions/ncm.usb0" "$g/functions/acm.GS0"
    echo 0x0525 >"$g/idVendor"; echo 0xa4a1 >"$g/idProduct"; echo 0x0200 >"$g/bcdUSB"
    echo CX60PROBE >"$g/strings/0x409/serialnumber"
    echo Unisoc >"$g/strings/0x409/manufacturer"
    echo 'Changxing 60 read-only probe' >"$g/strings/0x409/product"
    echo 'NCM + ACM diagnostic console' >"$g/configs/c.1/strings/0x409/configuration"
    echo 250 >"$g/configs/c.1/MaxPower"
    echo 02:50:00:00:60:01 >"$g/functions/ncm.usb0/dev_addr"
    echo 02:50:00:00:60:02 >"$g/functions/ncm.usb0/host_addr"
    ln -s "$g/functions/ncm.usb0" "$g/configs/c.1/f1"
    ln -s "$g/functions/acm.GS0" "$g/configs/c.1/f2"
    echo "$udc" >"$g/UDC"
    ifconfig lo 127.0.0.1 up
    ifconfig usb0 192.168.92.1 netmask 255.255.255.0 up
    mkdir -p /var/lib/misc; touch /var/lib/misc/udhcpd.leases
    printf 'start 192.168.92.2\nend 192.168.92.2\ninterface usb0\noption subnet 255.255.255.0\nopt lease 300\n' >/tmp/udhcpd.conf
    udhcpd /tmp/udhcpd.conf
    telnetd -b 192.168.92.1 -p 23 -l /bin/sh
    log 'USB diagnostics ready at 192.168.92.1; no DHCP gateway or DNS'
else
    log 'no unique UDC; retain RAM logs until timeout'
fi
# Keep the USB console available even if a display probe blocks.
(
# Only explicitly listed display modules; no wildcard auto-loader.
while read -r module; do
    [ -n "$module" ] || continue
    if [ "$module" = axs15205.ko ]; then
        insmod "/linux-modules/$module" verify_pram=1 >>/tmp/module.log 2>&1
    else
        insmod "/linux-modules/$module" >>/tmp/module.log 2>&1
    fi
    log "module $module rc=$?"
done </etc/module-order
) &
while :; do
    if [ "$probe_verified" = 1 ] && [ "$readonly_ok" = 1 ] && [ -f /e5-overlay/etc/ram-handoff.sh ]; then
        . /e5-overlay/etc/ram-handoff.sh
        ram_handoff
    fi
    dmesg >/tmp/dmesg.txt
    [ ! -e /tmp/reboot ] || reboot -f
    sleep 2
done
