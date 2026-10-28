"""Restore active DRM planes after the display domain loses its registers.

P720S20 R25: the initial LK image has a live layer, but unblank clears the
hardware layers. The Android-era active_changed shortcut then skips restoring
the unchanged framebuffer. Android's following compositor flip hid the gap;
the Linux fbdev client can legitimately retain the same framebuffer.
Only profiles explicitly applying this preparation are changed.
"""
from pathlib import Path


def apply(kernel):
    path = Path(kernel) / 'drivers/unisoc_platform/sprd_disp/sprd_plane.c'
    source = path.read_text()
    old = '''\tif (drm_plane->state->crtc->state->active_changed) {
\t\tDRM_DEBUG("resume or suspend, no need to update plane\\n");
\t\treturn;
\t}'''
    new = '''\t/* Restore the current framebuffer when scanout becomes active. */
\tif (!drm_state->crtc->state->active)
\t\treturn;'''
    if new in source:
        return
    if source.count(old) != 1:
        raise ValueError('Unexpected DRM plane resume shortcut')
    path.write_text(source.replace(old, new, 1))
