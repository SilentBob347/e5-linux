#!/bin/sh
# Runs under Magisk BusyBox ash, after stock Android has recreated /data.
# Writes only the pre-created e5root block device; never changes GPT/userdata.
set -eu
dev=${1:?} sectors=${2:?} raw=${3:?} grow=${4:?} token=${5:?}
case "$dev" in /dev/block/mmcblk[0-9]*p[0-9]*|/dev/block/sd[a-z]*[0-9]*) ;; *) exit 2 ;; esac
node=${dev##*/}
. /data/local/tmp/e5-storage.sh
disk=$(e5_storage_parent "$node")
[ "$disk" = "$(e5_storage_disk)" ]
case "$node" in *[!a-z0-9]*) exit 2 ;; esac
for n in "$sectors" "$raw"; do case "$n" in ''|0*|*[!0-9]*) exit 2 ;; esac; done
case "$grow" in 0|1) ;; *) exit 2 ;; esac
case "$token" in *[!0-9a-f]*) exit 2 ;; esac
[ "${#token}" = 32 ]
[ -b "$dev" ]
grep -qx PARTNAME=e5root /sys/class/block/$node/uevent
[ "$(cat /sys/class/block/$node/size)" = "$sectors" ]
[ -z "$(ls -A /sys/class/block/$node/holders)" ]
number=$(cat /sys/class/block/$node/dev)
for mounts in /proc/self/mountinfo /proc/1/mountinfo; do
    if awk -v n="$number" '$3 == n {yes=1} END {exit !yes}' "$mounts"; then
        echo 'root partition is mounted; refusing to write' >&2; exit 1
    fi
done
[ "$raw" -gt 0 ] && [ "$raw" -le "$((sectors * 512))" ]
lock=/data/local/tmp/e5-part-write.lock
stage=
legacy_owned=0
nv_phase=0
nv_mode=${6:-}
case "$nv_mode" in ''|--nv-check|--nv-ready) ;; *) exit 2 ;; esac
mounted=0 devbound=0 procbound=0 nvdevbound=0
cleanup() {
    rc=$?; trap - EXIT
    if [ "$rc" != 0 ] && [ "$nv_phase" = 1 ]; then echo E5_NV_PRESERVE_FAILED >&2; fi
    [ "$nvdevbound" = 0 ] || umount "$stage/view/dev" || exit 1
    [ "$mounted" = 0 ] || umount "$stage/view" || exit 1
    [ "$procbound" = 0 ] || umount "$stage/proc" || exit 1
    [ "$devbound" = 0 ] || umount "$stage/dev" || exit 1
    [ -z "$stage" ] || rm -rf "$stage"
    [ "$legacy_owned" = 0 ] || rmdir "$lock"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 1' INT TERM HUP
stage=$(mktemp -d /data/local/tmp/e5-part-tools.XXXXXX)
tar -xf /data/local/tmp/e5-ext4-tools.tar -C "$stage"
(cd "$stage" && sha256sum -c SHA256SUMS)
tar -xf /data/local/tmp/e5-install-lock-tools.tar -C "$stage"
(cd "$stage" && sha256sum -c INSTALL-LOCK-SHA256SUMS)
# The bundled installer BusyBox lacks flock. Ship the checked OpenWrt tool and
# its loader in ext4-tools instead of depending on Android's command set.
guard=/data/local/tmp/e5-part-write.flock
[ ! -L "$guard" ] && { [ ! -e "$guard" ] || [ -f "$guard" ]; } || exit 1
(umask 077; : >> "$guard")
exec 9>> "$guard"
chroot "$stage" /usr/bin/flock -n 9 || {
    echo 'another installation is actively writing; wait for it to finish' >&2; exit 1;
}
# Migrate old mkdir-only locks. Their scripts hold no kernel lock and left no
# PID record, so inspect actual script processes and writable target FDs.
if [ -e "$lock" ] || [ -L "$lock" ]; then
    [ -d "$lock" ] && [ ! -L "$lock" ] || { echo 'unsafe legacy install lock' >&2; exit 1; }
    target_id=$(stat -Lc '%t:%T' "$dev")
    for process in /proc/[0-9]*; do
        [ "${process##*/}" != "$$" ] || continue
        if tr '\000' '\n' < "$process/cmdline" 2>/dev/null | grep -qE '(^|/)(e5-)?part-write\.sh$'; then
            echo 'an older installation is still running; wait for it to finish' >&2; exit 1
        fi
        for descriptor in "$process"/fd/*; do
            [ -b "$descriptor" ] || continue
            [ "$(stat -Lc '%t:%T' "$descriptor" 2>/dev/null)" = "$target_id" ] || continue
            flags=$(awk '$1=="flags:" {print $2}' "$process/fdinfo/${descriptor##*/}" 2>/dev/null) || continue
            case "$flags" in ''|*[!0-7]*) continue ;; esac
            [ "$((flags & 3))" = 0 ] || {
                echo 'an installation still has the root device open for writing' >&2; exit 1;
            }
        done
    done
    rmdir "$lock" || { echo 'legacy lock contains unexpected files; nothing written' >&2; exit 1; }
    echo 'Recovered stale installation lock / 已回收失效安装锁'
fi
# Also exclude a genuinely older installer while this version runs. The stable
# flock inode is never unlinked; inherited FD 9 protects orphan writer children.
mkdir "$lock" || { echo 'another legacy installation just started' >&2; exit 1; }
legacy_owned=1
mkdir "$stage/dev" "$stage/proc" "$stage/etc" "$stage/view"
mount --bind /dev "$stage/dev"; devbound=1
mount --bind /proc "$stage/proc"; procbound=1
ln -s /proc/mounts "$stage/etc/mtab"
tools() { name=$1; shift; chroot "$stage" "/usr/sbin/$name" "$@"; }
image=/data/local/tmp/openwrt.ext4.gz

# Reinstall must not throw away calibration written only in OpenWrt. Capture
# the unmounted old root before the first write, using its own interpreter.
# Keep this backup outside the root being overwritten, including on failure.
nv_phase=1
nvbase=/data/local/tmp/e5-nv-backups
# The tools chroot has /dev, but the old/new root mounted at view is a separate
# chroot. Python's entropy fallback needs /dev/urandom there as well.
nv_python() {
    local rc=0
    [ -d "$stage/view/dev" ] || return 1
    mount --bind /dev "$stage/view/dev" || return 1
    nvdevbound=1
    chroot "$stage/view" /usr/bin/python3 - "$@" < "$nvhelper" || rc=$?
    umount "$stage/view/dev" || return 1
    nvdevbound=0
    return "$rc"
}
[ ! -L "$nvbase" ]
mkdir -p "$nvbase"; chmod 700 "$nvbase"
nvbackup= nvhash= nvfile=no
nvreceipt=$nvbase/$token.receipt
nvhelper=/data/local/tmp/e5-nv-persistence.py
[ -s "$nvhelper" ] && [ ! -L "$nvreceipt" ]
if [ -f "$nvreceipt" ] && { [ "${E5_NV_POLICY:-preserve}" != original ] || [ "${nv_mode:-}" = --nv-ready ]; }; then
    read signature identity nvfile nvhash < "$nvreceipt"
    [ "$signature" = NV-PRESERVATION-V1 ] && [ "$identity" = "$token" ]
    if [ "$nvfile" != no ]; then
        case "$nvfile" in "$token".tar.??????) ;; *) exit 1 ;; esac
        suffix=${nvfile##*.}; case "$suffix" in *[!A-Za-z0-9]*) exit 1 ;; esac
        case "$nvhash" in *[!0-9a-f]*) exit 1 ;; esac; [ "${#nvhash}" = 64 ]
        nvbackup=$nvbase/$nvfile
        [ ! -L "$nvbackup" ]
        printf '%s  %s\n' "$nvhash" "$nvbackup" | sha256sum -c -
    fi
fi
if [ "${nv_mode:-}" = --nv-ready ]; then
    [ -f "$nvreceipt" ]
elif [ "${E5_NV_POLICY:-preserve}" = original ]; then
    [ -s /data/local/tmp/e5-nv-original.tar ]
    nvbackup=$(mktemp "$nvbase/$token.tar.XXXXXX")
    cp /data/local/tmp/e5-nv-original.tar "$nvbackup"
    tar -tf "$nvbackup" >/dev/null
    nvfile=${nvbackup##*/}; nvhash=$(sha256sum "$nvbackup" | cut -d' ' -f1)
    [ "${#nvhash}" = 64 ]; case "$nvhash" in *[!0-9a-f]*) exit 1 ;; esac
elif mount -t ext4 -o ro,noload "$dev" "$stage/view" 2>/dev/null; then
    mounted=1
    if [ -e "$stage/view/opt/e5/nv" ] || [ -L "$stage/view/opt/e5/nv" ]; then
        # Every completed archive is immutable. An atomic receipt points at it,
        # so interruption cannot pair a newer tar with an older checksum.
        nvbackup=$(mktemp "$nvbase/$token.tar.XXXXXX")
        umask 077
        nv_python archive > "$nvbackup.part"
        tar -tf "$nvbackup.part" >/dev/null
        mv "$nvbackup.part" "$nvbackup"
        nvfile=${nvbackup##*/}; nvhash=$(sha256sum "$nvbackup" | cut -d' ' -f1)
        [ "${#nvhash}" = 64 ]; case "$nvhash" in *[!0-9a-f]*) exit 1 ;; esac
    fi
    umount "$stage/view"; mounted=0
elif [ ! -f "$nvreceipt" ]; then
    # A prepared but never-installed partition has no filesystem or NV. All
    # other unreadable roots require recovery, not silently losing calibration.
    marker=$(head -c 128 "$dev" | tr -d '\000')
    prepared=${E5_PREPARED_TOKEN:-$token}
    case "$prepared" in *[!0-9a-f]*) exit 1 ;; esac
    [ "${#prepared}" = 32 ]
    signature=$(dd if="$dev" bs=1 skip=1080 count=2 2>/dev/null | od -An -tx1 | tr -d ' \n')
    [ "$signature" != 53ef ] || { echo 'Unreadable ext4 root may contain NV; nothing overwritten' >&2; exit 1; }
    signature=$(dd if="$dev" bs=1 skip=1024 count=4 2>/dev/null | od -An -tx1 | tr -d ' \n')
    [ "$signature" != 1020f5f2 ] || { echo 'Unexpected F2FS in root; nothing overwritten' >&2; exit 1; }
    case "$marker" in "E5-PART-PREPARED-V2 $prepared") ;; *)
        echo 'Cannot preserve existing OpenWrt NV; root was not overwritten' >&2; exit 1 ;;
    esac
fi
# The SAME transaction may safely resume a partially written installation.
# Old immutable archives and an interrupted .part are retained for diagnosis.
(umask 077; printf 'NV-PRESERVATION-V1 %s %s %s\n' "$token" "$nvfile" "${nvhash:--}" > "$nvreceipt.part")
mv "$nvreceipt.part" "$nvreceipt"
sync
nv_phase=0
[ "${nv_mode:-}" != --nv-check ] || { echo NV-PREPARED; exit 0; }
gzip -t "$image"
[ "$(gzip -dc "$image" | wc -c | tr -d ' ')" = "$raw" ]
want=$(gzip -dc "$image" | sha256sum | cut -d' ' -f1)
echo '1/4 writing root image'
gzip -dc "$image" > "$dev"
sync
[ "$(head -c "$raw" "$dev" | sha256sum | cut -d' ' -f1)" = "$want" ]
echo '2/4 checking and growing filesystem'
tools e2fsck -f -p "$dev" || { rc=$?; [ "$rc" = 1 ] || exit "$rc"; }
if [ "$grow" = 1 ]; then
    tools resize2fs "$dev" "$((sectors / 8))"
fi
tools e2fsck -f -n "$dev"
if [ "$grow" = 1 ]; then
    . "$stage/ext4-geometry.sh"
    ext4_verify_grown "$dev" "$sectors" || { echo 'filesystem geometry does not fill target' >&2; exit 1; }
fi
echo '3/4 installing device firmware and settings'
mount -t ext4 "$dev" "$stage/view"; mounted=1
tar -xf /data/local/tmp/e5-device-files.tar -C "$stage/view"
if [ -f "$nvbackup" ]; then
    printf '%s  %s\n' "$nvhash" "$nvbackup" | sha256sum -c -
    tar -xf "$nvbackup" -C "$stage/view"
    chmod 700 "$stage/view/opt/e5/nv"
    nv_python verify
    nv_python update-backup
fi
test -s "$stage/view/lib/firmware/wcnmodem.bin"
test -x "$stage/view/sbin/init"
test -s "$stage/view/etc/openwrt_release"
mkdir -p "$stage/view/etc/e5" "$stage/view/etc/e5linux"
echo linux > "$stage/view/etc/e5linux/default-boot"
cp /data/local/tmp/e5-install.conf "$stage/view/etc/e5/install.conf"
chmod 600 "$stage/view/etc/e5/install.conf"
rm -f "$stage/view/etc/e5/sd-root" "$stage/view/etc/e5/sd-trial"
printf 'e5root /dev/%s\n' "$disk" > "$stage/view/etc/e5/part-root"
echo 1 > "$stage/view/etc/e5/part-trial"
echo "$token" > "$stage/view/etc/e5/part-install-token"
test -x "$stage/view/opt/e5/android/vendor/bin/modem_control"
chroot "$stage/view" /bin/busybox find /lib/firmware /opt/e5/android -type f \
    -exec /bin/busybox sha256sum '{}' \; > "$stage/root-files.sha256"
chroot "$stage/view" /bin/busybox sha256sum /sbin/init /etc/e5/install.conf \
    /etc/e5/part-root /etc/e5/part-trial /etc/e5/part-install-token >> "$stage/root-files.sha256"
test -s "$stage/root-files.sha256"
sync
umount "$stage/view"; mounted=0
blockdev --flushbufs "$dev"
echo '4/4 verifying installed root read-only'
mount -t ext4 -o ro,noload "$dev" "$stage/view"; mounted=1
chroot "$stage/view" /bin/busybox sha256sum -c < "$stage/root-files.sha256"
test "$(cat "$stage/view/etc/e5/part-install-token")" = "$token"
test -s "$stage/view/lib/firmware/wcnmodem.bin"
test -x "$stage/view/sbin/init"
umount "$stage/view"; mounted=0

# The final read-only mount must validate NV too, after actual writeback.
if [ -f "$nvbackup" ]; then
    mount -t ext4 -o ro,noload "$dev" "$stage/view"; mounted=1
    nv_python verify
    umount "$stage/view"; mounted=0
fi
echo "ROOT-VERIFIED $dev filesystem_blocks=$(od -An -tu4 -j 1028 -N 4 "$dev")"
