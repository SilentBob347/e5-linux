#!/bin/sh
# Feed cfg80211's pending regulatory.db request (and its signature) while it waits in
# the sysfs firmware fallback, then reload.  Late calls cannot work: the request is
# one-shot at boot, and without it the domain stays world/00 (all channels NO-IR).
for f in regulatory.db regulatory.db.p7s; do
    src=/lib/firmware/$f
    [ -e "$src" ] || continue
    s=/sys/class/firmware/$f
    [ -d "$s" ] || continue
    echo 1 > "$s/loading" && cat "$src" > "$s/data" && echo 0 > "$s/loading" && echo "fed $f"
done
# Both regulatory requests are handed off above before reload. The kernel
# owns completion; a fixed sleep neither checks it nor improves validation.
iw reg reload || { echo 'regulatory database reload failed' >&2; exit 1; }
iw reg set CN || { echo 'regulatory country selection failed' >&2; exit 1; }
iw reg get 2>/dev/null | head -3
