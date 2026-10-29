# M8 充电芯片变种的隔离兼容

参考 [上游 PR #18](https://github.com/sprd-linux-devs/e5-linux/pull/18)，
来源提交 `08ad6072ea4ba7cae566fc08b7ccdea36468f922`，作者 yzmninglang。
其报告的类似 M8 硬件在 REG0B 返回 0x11，原厂 500 mA 请求对应 REG02=0x88。
本次未连接或写入设备；0x11 实物的充电截止、温升、OTG 仍需硬件验证。

仅在 `devices/m8/prepare-kernel.py` 的实际 recipient 为 `m8` 时启用该变种。
0x11 使用 PR 提供的 60 mA/LSB 编码，0x12 保持现有 A6 分段表；输入限流、
终止电压、OTG enable/disable、VBUS regulator 和外部供电角色策略均未改动。
没有合入 PR 中公共 gadget-guard 的 UDC 重绑定修改。

不能按旧 PR 原样合并：41S 的准备器先运行 M8 donor，再替换本机 SGM41513
识别条件。PR 的双 ID 表达式会让该精确替换静默失效，生成先将 I2C 地址改为
0x1a、随后却要求其为 0x6b 的驱动，必然返回 ENODEV。
本次默认 donor 保持原 0x12 条件，仅由真正 M8 构建显式开启变种。

验证：新增 6 项测试包含实际生成 C 的编译执行、真实 41S 组合链、K1 独立电压、
自定义 charger 回调、OTG/电压函数逐字节比较。现有 DWC3 外部供电 7 项测试通过。
额外与 `182b24e9` 比较，默认 donor、K1、41S 的整份生成充电驱动逐字节相同。
E5、T551M、T512N、LYM-10K 的准备代码未改；畅行60继续走自己的 charger 回调。

后续发布须重编 M8 的配套 Image/模块。此轮遵照用户要求暂停 E5 仓库发布构建，
没有更新现有固件 ZIP，也没有部署硬件。
