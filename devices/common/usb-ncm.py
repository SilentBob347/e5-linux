#!/usr/bin/env python3
"""Retain the NCM flush deadline when USB TX requests are temporarily busy.

Based on Cosmin Tanislav's linux-usb patch of 2026-08-17, message ID
20260817192638.437798-1-cosmin-gabriel.tanislav.xa@renesas.com.
"""
from pathlib import Path


def apply(kernel):
    path = Path(kernel)/'drivers/usb/gadget/function/f_ncm.c'
    source = path.read_text()
    start = source.index('static enum hrtimer_restart ncm_tx_timeout(struct hrtimer *data)\n{')
    end = source.index('\n}', start)+2
    callback = source[start:end]
    old = '\t\tnetdev->netdev_ops->ndo_start_xmit(NULL, netdev);'
    new = '''\t\t/* A timer flush has no qdisc to retry a busy USB request. */
\t\tif (netdev->netdev_ops->ndo_start_xmit(NULL, netdev) == NETDEV_TX_BUSY) {
\t\t\thrtimer_forward_now(data, TX_TIMEOUT_NSECS);
\t\t\treturn HRTIMER_RESTART;
\t\t}'''
    if old in callback:
        if callback.count(old) != 1:
            raise ValueError('Unknown NCM timeout callback')
        callback = callback.replace(old, new)
        path.write_text(source[:start]+callback+source[end:])
    elif not all(token in callback for token in (
            'NETDEV_TX_BUSY', 'hrtimer_forward_now(', 'TX_TIMEOUT_NSECS', 'return HRTIMER_RESTART;')):
        raise ValueError('Unknown NCM timer retry implementation')


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])
