# MCP-DM：独立 DM Provider 参考

本候选包只提供 `dm_*`。Python/TCP 与 native 是两个显式后端；不包含通用
图像工作台、`image_*`、`structure_*` 或它们的工作区配置，也不会静默回退。
实际工具参数以连接返回的 `tools/list` 为准，宿主操作资格以 `dm_status` 和
具体算子的构建/数据类型/几何门禁为准。

## 使用入口

- [安装与范围](README.md)
- [Agent 安装和操作指南](README.agent.md)
- [独立 DM 注册脚本](setup/register_codex.ps1)：`python` / `native`，先用 `-CheckOnly`
- [保留的原资格合同](DM_QUALIFICATION_CONTRACT.md)：其中旧的混合产品说明不代表本包仍含科学工作台
- [原生适配器门禁](experiments/native-bridge/mvp/ADAPTERS.md)
- [科学数值交接](docs/SCIENTIFIC_HANDOFF.md)
- [回传 DM 的受限能力](docs/DM_NUMERIC_RELAY.md)

默认任意 DM-Script 关闭；不控制显微镜硬件。原生会话、请求 ID、坐标域、
标定和数组类型必须保持原义。超时后查原请求，不自动重放。独立 TIFF、FFT、
标注和结构分析属于另行配置的科学 MCP，不需要为它安装 GMS。
