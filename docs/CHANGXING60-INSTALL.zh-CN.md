# 畅行60正式安装接入

2026-10-29；机型 ZTE 7552N／P720S20，原厂版本
`ZTE/CN_P720S20/P720S20:13/TP1A.220624.014/20240919.212928:user/release-keys`。

## 已知硬件与流程

本机实际使用 UFS、4096 字节逻辑块，userdata 是 FBE＋metadata 加密。
原始调查和完整 RAM 试运行记录见 `devices/changxing60/README.md`；不从
MU300 的 U30 Air 推断畅行60已经完成安装验收。

正式安装使用公共安装器，不使用探测 init、测试色块或 RAM 根归档。
有足够 GPT 未分配空间时直接创建独立分区；否则加密 userdata 必须经用户
明确确认清空，进入 initramfs 离线分区，再由本机原厂 recovery 格式化。
返回 Android 后，安装器等待用户完成设置、调试及 root 授权，核对电脑事务、
存储身份、分区标记和容量后续装。载荷留在电脑，不依赖解密旧 userdata。

## 公共存储约定

- `boot/storage.sh` 是 Android、initramfs 和正常系统共用的拓扑来源。
  从唯一内置 userdata 建立父盘；不假定 UFS 用户盘一定是 sda。
- UFS 身份来自随包的只读 READ-DESCRIPTOR 工具；Android 与 Linux
  采用相同工具、相同带 LUN 摘要，不使用厂商通用 WWID 代替唯一身份。
- sysfs、事务和上层 API 一律使用 512 字节 sector；只有 GPT 编解码
  使用真实逻辑块。电脑、ucode、卸载恢复均处理 512／4096。
- 两阶段安装的 GPT 备份范围从主备头解码，不再固定前34、后33个 sector。
- 重装不改 userdata；更新保留容量、工作 NV、固件与设置；卸载继续要求
  匹配的设备及安装证据，按原安装方式归还空间。

## 本机资源

正常 boot 合并本机供应者和公共模块列表后解析依赖，目前为46项；SPI控制器在AXS触摸之前，显示电源域在DRM之前。不沿用仅替换公共触摸模块名称的旧45项列表。
AXS15205 需要本机 `axs_firmware_easyquick.bin`，安装时生成
`lib/firmware/axs15205/easyquick.bin`，加载触摸驱动前提供固件。

本机 `audio_config.xml`、`audio_route.xml`、`audio_pga.xml`、`codec.xml`
随本机固件提取；启动时生成听筒／免提路由与10档原厂通话增益，不分发捐献机
校准数据。更新路径保留这些文件及触摸固件。

Android／OpenWrt 槽位动态确定。本机已验证的配套启动链除了公共
uboot/sml/teecfg/trustos/vbmeta，还需核对 dtbo/vendor_boot；仅 P720S20
增加这两项，同步前备份两槽，只写备用槽并回读，不修改当前 Android 槽。

## 回归与验收边界

已执行：电脑模拟 A/B 槽位、加密UFS、非sda命名、4K GPT备份、两阶段请求、
跨盘拒绝；实际 ucode 对稀疏文件执行512／4096分区与校验；卸载恢复及原有
缩容、NV、安装器回归。所有这些测试都不访问物理磁盘。

此前用户已确认 RAM 试运行的屏幕、触摸、蜂窝、热点、提示音、免提及扩展坞
联网与充电。2026-10-29用户完成正式安装；随后本轮修正正式显示/SPI初始化，
正常重启后用户确认触摸、息屏／亮屏均正常。见
[安装与启动回归](INSTALLER-FLOW-AUDIT-20261029.zh-CN.md)。
新自动在线worker的物理掉电、正式更新/卸载仍未完成硬件验收。
