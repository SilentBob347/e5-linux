"""Temporary read-only DPU evidence for P720S20 blank/unblank diagnosis."""
from pathlib import Path


def apply(kernel):
    path = Path(kernel) / 'drivers/unisoc_platform/sprd_disp/sprd_dpu.c'
    source = path.read_text()
    marker = '/* P720S20 diagnostic: observe scanout without register writes. */'
    if marker in source:
        return
    helper = '''
/* P720S20 diagnostic: observe scanout without register writes. */
static void cx60_trace_dpu(struct dpu_context *ctx, const char *phase)
{
    DRM_INFO("CX60-DPU %s ctrl=%08x cfg0=%08x cfg1=%08x layers=%08x dpi=%08x irq=%08x\\n",
        phase, readl(ctx->base + 0x08), readl(ctx->base + 0x0c),
        readl(ctx->base + 0x10), readl(ctx->base + 0x2c),
        readl(ctx->base + 0x260), readl(ctx->base + 0x250));
}

'''
    anchor = 'void sprd_dpu_run(struct sprd_dpu *dpu)'
    if source.count(anchor) != 1:
        raise ValueError('Unexpected DPU run entry')
    source = source.replace(anchor, helper + anchor, 1)
    source = source.replace('dpu->core->run(ctx);',
                            'dpu->core->run(ctx);\n\tcx60_trace_dpu(ctx, "run");', 1)
    anchor = '\tDRM_INFO("dpu resume OK\\n");'
    if source.count(anchor) != 1:
        raise ValueError('Unexpected DPU resume entry')
    source = source.replace(anchor, '\tcx60_trace_dpu(&dpu->ctx, "resume");\n' + anchor, 1)
    anchor = '\t\tDRM_WARN("Warning: dpu underflow!\\n");'
    if source.count(anchor) != 1:
        raise ValueError('Unexpected DPU interrupt entry')
    source = source.replace(anchor, anchor + '\n\t\tcx60_trace_dpu(ctx, "underflow");', 1)
    path.write_text(source)


def remove(kernel):
    path = Path(kernel) / 'drivers/unisoc_platform/sprd_disp/sprd_dpu.c'
    source = path.read_text()
    marker = '/* P720S20 diagnostic: observe scanout without register writes. */'
    if marker not in source:
        return
    start=source.index(marker)
    end=source.index('void sprd_dpu_run(struct sprd_dpu *dpu)',start)
    source=source[:start]+source[end:]
    for line in ('\n\tcx60_trace_dpu(ctx, "run");',
                 '\n\tcx60_trace_dpu(&dpu->ctx, "resume");',
                 '\n\t\tcx60_trace_dpu(ctx, "underflow");'):
        if source.count(line)!=1:
            raise ValueError('Unexpected diagnostic DPU trace call')
        source=source.replace(line,'',1)
    if 'cx60_trace_dpu' in source:
        raise ValueError('Diagnostic DPU trace removal incomplete')
    path.write_text(source)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel',type=Path)
    parser.add_argument('--remove',action='store_true')
    args=parser.parse_args()
    (remove if args.remove else apply)(args.kernel)
