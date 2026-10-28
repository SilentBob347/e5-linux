/* SPDX-License-Identifier: GPL-2.0-only */
/* Accept the reset binding actually supplied by the board's stock DT. */
#include <linux/mfd/syscon.h>
#include <linux/regmap.h>
#include <linux/reset.h>
#include <linux/slab.h>

struct sprd_display_reset {
    struct reset_control *control;
    struct regmap *syscon;
    unsigned int reg, mask;
};

static inline struct sprd_display_reset *sprd_display_reset_get(
    struct device *dev, struct device_node *np, const char *name, const char *property)
{
    struct sprd_display_reset *reset=devm_kzalloc(dev,sizeof(*reset),GFP_KERNEL);
    unsigned int args[2];
    if (!reset)
        return ERR_PTR(-ENOMEM);
    if (of_find_property(np,property,NULL)) {
        reset->syscon=syscon_regmap_lookup_by_phandle_args(np,property,2,args);
        if (IS_ERR(reset->syscon))
            return ERR_CAST(reset->syscon);
        reset->reg=args[0];reset->mask=args[1];
        if (!reset->mask)
            return ERR_PTR(-EINVAL);
    } else {
        reset->control=devm_reset_control_get(dev,name);
        if (IS_ERR(reset->control))
            return ERR_CAST(reset->control);
    }
    return reset;
}

static inline int sprd_display_reset_assert(struct sprd_display_reset *reset)
{
    return reset->syscon ? regmap_update_bits(reset->syscon,reset->reg,reset->mask,reset->mask) :
        reset_control_assert(reset->control);
}

static inline int sprd_display_reset_deassert(struct sprd_display_reset *reset)
{
    return reset->syscon ? regmap_update_bits(reset->syscon,reset->reg,reset->mask,0) :
        reset_control_deassert(reset->control);
}
