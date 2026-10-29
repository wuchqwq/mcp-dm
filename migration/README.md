# 明天迁仓：两个独立 MCP，而不是两个操作系统版本

本 PR 只做**可运行的迁仓准备**，不创建新仓库、不自动合并任何 PR、不删除旧代码。
`microscopy-core` 是 Windows/macOS/Linux 的科学产品；`mcp-dm` 是可选、独立维护的
DigitalMicrograph MCP。它们由 Agent 客户端并列连接，不互相 import。

## 代码归属

| 归属 | 内容 | 不能依赖什么 |
| --- | --- | --- |
| 新 `microscopy-core` | `image_*`、图像面板、独立数据检查、`structure_*`、科学上下文、执行协调、专业 Skills | DM 安装、Gatan Python/SDK、原生 DLL、旧仓库路径 |
| 原 `mcp-dm` | `dm_*`、DM Python 桥、C++ 原生适配、版本/能力门禁、宿主生命周期、数值接力 | 新核心、其 GUI/Skills、ASE/diffsims |
| 协议兼容边界 | 小型 stdio/schema/registry 实现及只读 capture 校验 | 只复制带来源的协议快照；不得建立跨仓运行时依赖 |

`migration/ownership.json` 是实际导出清单，不是仅供参考的架构图。
现有 `bridge/analysis2d_core.py` 等旧版 DM 数值辅助仍留在 DM 端维持兼容；
不会借迁仓重写算法或冒称它们是新的通用科学引擎。

## 本次修复的具体接线问题

Image Panel 启动 stdio 子服务时原来只传 `DM_IMAGE_*`。新科学入口读取
`MICROSCOPY_*`，因此简单搬文件会让面板可能访问默认工作区而不是选中的工作区。
导出时用受控的单处精确匹配适配，给同一明确 workspace/interpreter 同时传入两个
入口配置，并隔离子进程不需要的结构/上下文配置。适配内容与来源在清单中记录；
找不到唯一原语句就拒绝，不做盲目全文替换。原仓库和并行 GUI 分支的文件不改动；
原有工具、数组、标定、请求日志与 API 均不改名。

导出的科学 `server.mjs` 只接入 `science-server.mjs`；导出的 DM `server.mjs`
只接入新 `createDMRuntime`，不加载图像/结构模块。DM 超时门槛和原 `dm_*`
目录不变。迁仓工具不复制 `.git`、venv、运行时目录、原始显微数据、凭据或厂商二进制。

## 已检查的分支关系

- 基线 `main`: `be1a85dceccb37e774abd386aabdf7789ae43ace`。
- #46 独立入口：`e6f1301a29cb0d4e6d5e6a4b5856e2cdf6b3169a`，仍保持 Draft。
- #50 界面栈：`a158b1ac58af7d3b6e68d9e95afb17becaedfe2c`，包含 #48 → #49；
  只在临时集成分支中纳入，不据此自动合并这些 PR。
- 本 PR #52 在 main 上单独开发，仅在导出科学包内适配面板接线；不改 #46 的源入口，
  不改 #50 的 GUI 操作逻辑，不动 #27 / Draft #3 的 GMS 兼容研究。

清单要求上述两个固定提交是导出源的祖先，防止只迁了入口、漏掉最新界面。
发现新提交时先审核、更新清单和定点验证，不悄悄换成浮动 branch HEAD。

## 你创建新仓库之后

先创建一个**空**的 `microscopy-core` 仓库，先不要初始化 README、LICENSE 或
.gitignore。下一步使用独立 worktree 组装候选，**以下 merge 只发生在新建的本地
`migration/science-split` 分支，绝不合并 main**。先确认没有同名分支/工作目录。

```bash
git fetch origin feature/prepare-science-repository-split-20261029
# 这两个 SHA 是上述固定且已核对的 PR 快照。
git fetch origin e6f1301a29cb0d4e6d5e6a4b5856e2cdf6b3169a a158b1ac58af7d3b6e68d9e95afb17becaedfe2c
git worktree add -b migration/science-split ../mcp-dm-migration be1a85dceccb37e774abd386aabdf7789ae43ace
cd ../mcp-dm-migration
git merge --no-ff --no-edit e6f1301a29cb0d4e6d5e6a4b5856e2cdf6b3169a
git merge --no-ff --no-edit a158b1ac58af7d3b6e68d9e95afb17becaedfe2c
git merge --no-ff --no-edit origin/feature/prepare-science-repository-split-20261029
python3 -B tools/prepare_repository_split.py --source-ref HEAD --check
python3 -B tools/prepare_repository_split.py --source-ref HEAD --output ../split-ready
```

冲突或检查失败就停止，不能选择“全部保留某边”来抹掉科学/UI 修改。目录已存在时
导出器拒绝，即使它是空目录；改用新的明确路径。Windows 可用同一 Git 流程和
独立 Python >=3.10，解释器命令按实际安装填写，不依赖 GMS Python。

输出：

```text
split-ready/
  microscopy-core/       # 可以独立安装/运行的科学仓库候选
  mcp-dm/                # 可以独立运行的 DM-only 候选，不自动替换原仓库
  split-manifest.json    # 原始提交、配方提交、Git tree、逐文件来源和 SHA256
```

每个候选内也有 `MIGRATION_MANIFEST.json`。源树/配方都从 Git 已提交对象读取；
本地未提交改动和 untracked 文件不会混进来。只在完整检查后发布到独占的新目录；
发布中断保留 `INCOMPLETE.txt`，存在此文件时不能当成可用候选。

分别在两个候选中运行 `npm test`。科学候选再用独立环境安装
`requirements-images.txt`，设置绝对 `MICROSCOPY_PYTHON` 后运行
`npm run test:science`，核对 TIFF、FFT、测量、导出、重连和面板 HTTP。

通过后，在**科学候选目录**内初始化新仓库并由你审核后推送：

```bash
cd ../split-ready/microscopy-core
git init -b main
git add .
git commit -m "Import reviewed standalone microscopy core"
# 将下面的地址替换为你刚创建的空仓库；这是唯一需要补的远端信息。
git remote add origin <你的新仓库地址>
git push -u origin main
```

这是一份可追溯的源码快照导入，**不是重写历史或保留逐行 blame 的 filter-repo
迁移**。原仓库和历史继续存在，LICENSE 与来源哈希保留。不要删除源仓库来“收尾”。

## 旧仓库何时删通用代码

先在新仓库验证实际客户端和用户工作流，再对原仓库单独提交 DM-only 清理 PR。
当前旧组合入口暂留兼容，迁移提示后再移除；不要用导出的 DM 目录直接覆盖整个
原仓库，也不要同时长期开发两份通用科学实现。

迁的是代码，不是研究工作目录。持久日志绑定的路径/对象/哈希维持原义；跨机器、
改绝对路径后的历史工作区迁移必须单独验证，不能声称旧 ID 自动代表新位置的数据。

## 证据边界

自动 CI 只有迁仓定点 stdlib/Node 检查和候选包检查，不跑全量 Windows/Python/C++，
不装 GMS，不调用真实 DM。真实本地合成科学闭环另有明确命令；缺依赖会失败而非
偷偷跳过。实际 Mac、Windows GMS、模型视觉、完整浏览器手势、CIF/diffsims 实算和
跨机器工作区恢复，不由本次迁仓 smoke 冒充验收。详见 `VALIDATION.md`。
