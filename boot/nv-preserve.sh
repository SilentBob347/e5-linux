# Sourced by init. No NV writers exist in this early offline phase.
nv_archive_offline() {
    local old=$1 archive=$2
    [ ! -L "$old/opt/e5/nv" ] || return 1
    [ -d "$old/opt/e5/nv" ] || return 3
    [ ! -L "$old/opt/e5/nv" ] && [ -x "$old/usr/bin/python3" ] || return 1
    # The interpreter and libraries belong to the old, verified system. Only
    # the new maintenance source is streamed on stdin; no target script runs.
    chroot "$old" /usr/bin/python3 - archive < /etc/nv-persistence.py > "$archive.part" || {
        rm -f "$archive.part"; return 1;
    }
    tar -tf "$archive.part" >/dev/null || return 1
    mv "$archive.part" "$archive" || return 1
    sha256sum "$archive" > "$archive.sha256"
}

nv_restore_offline() {
    local new=$1 archive=$2
    [ -f "$archive" ] || return 0
    sha256sum -c "$archive.sha256" || return 1
    tar -xf "$archive" -C "$new" || return 1
    chmod 700 "$new/opt/e5/nv" || return 1
    chroot "$new" /usr/bin/python3 - verify < /etc/nv-persistence.py || return 1
    chroot "$new" /usr/bin/python3 - update-backup < /etc/nv-persistence.py
}

nv_migrate_images() {
    local old=$1 new=$2 oldloop newloop result=1 signature profile cid
    mkdir -p /nv-old /nv-new || return 1
    oldloop=$(losetup -f) || return 1
    losetup "$oldloop" "$old" || return 1
    if mount -t ext4 -o ro,noload "$oldloop" /nv-old; then
        nv_archive_offline /nv-old /run/nv-update.tar
        result=$?
        umount /nv-old || return 1
    fi
    losetup -d "$oldloop" || return 1
    newloop=$(losetup -f) || return 1
    losetup "$newloop" "$new" || return 1
    mount -t ext4 "$newloop" /nv-new || { losetup -d "$newloop"; return 1; }
    if [ -f /nv-new/etc/e5/nv-update-original ]; then
        read signature profile cid < /nv-new/etc/e5/nv-update-original
        if [ "$signature" = NV-ORIGINAL-RECOVERY-V1 ] &&
           [ "$profile" = "$(cat /nv-new/etc/e5/device-profile)" ] &&
           [ "$cid" = "$(cat /sys/class/block/mmcblk0/device/cid)" ] &&
           chroot /nv-new /usr/bin/python3 - verify < /etc/nv-persistence.py; then
            result=0
        else result=1; fi
        # Consumed by nv-prepare only after the selected root actually starts.
        # A power loss before the image rename must not lose the user's choice.
    elif [ "$result" = 0 ]; then
        nv_restore_offline /nv-new /run/nv-update.tar || result=1
    elif [ "$result" = 3 ]; then result=0
    fi
    sync || result=1
    umount /nv-new || result=1
    losetup -d "$newloop" || result=1
    if [ "$result" = 0 ]; then rm -f /run/nv-update.tar /run/nv-update.tar.sha256; fi
    return "$result"
}
