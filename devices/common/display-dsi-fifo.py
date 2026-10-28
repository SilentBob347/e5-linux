"""Wait for both DSI FIFOs before changing work mode.

The wait helpers return zero on success.  Using logical AND on their return
values skips the payload wait when the command FIFO is already empty and logs
a false failure.  This is a source-level defect, independent of touch ESD.
"""
from pathlib import Path


def apply(kernel):
    path = Path(kernel) / 'drivers/unisoc_platform/sprd_disp/dsi/sprd_dsi_api.c'
    source = path.read_text()
    old = '''\tif (!(dsi_wait_tx_cmd_fifo_empty(dsi) &&
\t      dsi_wait_tx_payload_fifo_empty(dsi)))
\t\tpr_err("tx cmd fifo or payload fifo is not empty\\n");'''
    new = '''\t/* Both wait helpers return 0 on success; check each in order. */
\tif (dsi_wait_tx_cmd_fifo_empty(dsi) ||
\t    dsi_wait_tx_payload_fifo_empty(dsi))
\t\tpr_err("tx cmd fifo or payload fifo is not empty\\n");'''
    if new in source:
        return
    if source.count(old) != 1:
        raise ValueError('Unexpected DSI FIFO wait source')
    path.write_text(source.replace(old, new, 1))
