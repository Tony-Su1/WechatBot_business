# CODEX.md

本文件用于让 Codex 在不同设备上拉取本仓库后，可以快速接续开发。请优先阅读本文件，再阅读 `README.md`、`config.py`、`bot.py`、`config_editor.py`。

## 项目目标

将现有微信机器人改造成保险私域客户经营助手，先聚焦私聊，不优先处理群聊。

目标工作流：

1. 售前：维护旧客户，定期邀约，生日问候，保费到期提醒，观察客户人生事件与兴趣变化。
2. 售中：客户表达兴趣后，调用知识库回答问题，准备资料，邀请参加活动，必要时转接真人。
3. 售后：定期维护关系，收集服务反馈，促进转介绍，并根据客户性格、偏好、天赋能力评价调整话术。

## 当前实现状态

### 已完成

1. 删除与保险客户经营无关的 JM 下载功能。
   - 删除 `jm_download_service.py`。
   - 清理 `config.py`、`config_editor.py`、`requirements.txt`、文档中的 JM 下载相关内容。

2. 新增客户记忆配置。
   - `ENABLE_CUSTOMER_MEMORY = True`
   - `ENABLE_CUSTOMER_DB = True`
   - `CUSTOMER_DB_PATH = 'data/customer_assistant.db'`
   - `CUSTOMER_MEMORY_DIR = 'CustomerMemory'`
   - `CUSTOMER_MEMORY_PRIVATE_ONLY = True`
   - `CUSTOMER_MEMORY_AUTO_UPDATE = True`
   - `CUSTOMER_MEMORY_MAX_CHARS = 3000`

3. 新增 SQLite 客户数据库。
   - 主要逻辑在 `bot.py`。
   - 数据表：
     - `customers`：客户主档、生日、保费到期日、性格、偏好、销售阶段、转人工状态等。
     - `customer_events`：结婚、生子、生日、保单周年等事件。
     - `interactions`：聊天互动摘要与片段。
     - `followups`：跟进任务。
   - 机器人启动时会初始化数据库。
   - 客户资料会被转换成 markdown 片段，注入到当前聊天 prompt 中。

4. 保留 `CustomerMemory/*.md` 可读缓存。
   - 数据库是主存储。
   - markdown 作为可读缓存，方便人工检查客户画像。
   - `CustomerMemory/`、`data/`、`*.db` 已加入 `.gitignore`，避免把客户隐私提交到 GitHub。

5. 新增客户 CRM 前端。
   - 后端逻辑在 `config_editor.py` 的“客户 CRM 面板”区域。
   - 页面：
     - `templates/customer_crm.html`
     - `templates/customer_detail.html`
   - 原配置页 `templates/config_editor.html` 增加了“客户CRM”入口。
   - 当前支持：
     - 客户列表
     - 搜索客户
     - 筛选全部、待转人工、30 天内保费到期、30 天内生日、30 天未互动
     - 查看客户详情
     - 编辑客户主档
     - 新增跟进任务
     - 完成跟进任务
     - 查看互动记录、客户事件、客户画像预览

6. 新增联网检测快速跳过逻辑。
   - 位置：`bot.py` 的 `should_skip_online_detection_fast` 和 `needs_online_search`。
   - 原逻辑：`ENABLE_ONLINE_API=True` 时，每条消息都会先调用模型判断是否需要联网。
   - 当前优化：普通短消息、问候、一般保险咨询会直接跳过联网检测；明显包含天气、新闻、股票、官网、搜索、查一下、实时、最新新闻等关键词的消息才进入原有联网判断流程。
   - 注意：这不是删除联网功能，只是减少不必要的前置 API 调用。若正常回复阶段仍报 `Connection error`，应继续检查 API Key、Base URL、代理、模型名和网络环境。

7. 追加过项目进度文档。
   - 本地文件：`/Users/tonysu/Downloads/保险AI销售助手需求说明.docx`
   - 已追加一次“当前实现过程与进度记录”。
   - 该文件不在仓库内。

## 重要文件

- `bot.py`：机器人主逻辑、消息处理、客户记忆、SQLite 客户数据库、联网检测。
- `config.py`：机器人配置、客户记忆开关、API 配置。
- `config_editor.py`：Flask 配置编辑器，同时包含客户 CRM 后端路由。
- `templates/config_editor.html`：配置编辑器页面，含客户 CRM 入口。
- `templates/customer_crm.html`：客户 CRM 列表页。
- `templates/customer_detail.html`：客户详情页。
- `.gitignore`：已忽略客户隐私数据和数据库文件。

## 当前运行方式

Windows 运行时需要确保私有依赖 `wxautox4_wechatbot` 可用。若从 GitHub 新设备拉取后出现：

```text
ModuleNotFoundError: No module named 'wxautox4_wechatbot'
```

说明私有 wheel 或 `libs/` 没有安装。需要从已备份的本地项目复制 `libs/`，或按当前 Python 版本安装对应 wheel，例如 Python 3.11：

```bash
python -m pip install "libs\wxautox4_wechatbot-40.1.10-cp311-cp311-win_amd64.whl" --no-deps --force-reinstall
```

配置编辑器运行后，可以从主配置页点击“客户CRM”进入客户面板。

## 已验证

本次提交前通过：

```bash
python3 -m py_compile bot.py config.py config_editor.py
```

注意：当前 macOS 开发环境没有完整 Flask/Windows 微信自动化运行环境，因此只做了语法级验证；实际微信自动化需要在 Windows + 微信客户端环境中验证。

## GitHub 远端

业务备份仓库：

```text
ssh://git@ssh.github.com:443/Tony-Su1/WechatBot_business.git
```

本仓库用于保险客户经营助手方向。旧 `origin` 仍可能指向原 JM 版本仓库，推送业务版本时优先使用 `business main`。

## 下一步建议

1. 在 Windows 环境完整跑通机器人。
   - 验证 `wxautox4_wechatbot` 安装。
   - 验证配置编辑器可打开。
   - 验证客户 CRM 页面可访问。
   - 验证私聊消息能写入 SQLite。

2. 改进客户记忆抽取。
   - 当前客户资料更新偏基础。
   - 下一步应让模型从每轮聊天中抽取结构化字段：
     - 客户生日
     - 保费到期日
     - 家庭状态
     - 子女信息
     - 兴趣偏好
     - 性格与沟通风格
     - 当前销售阶段
     - 下一步动作
     - 是否需要转人工

3. 增加“人工确认后写入”机制。
   - 重要信息如生日、保费到期、家庭状态不应完全自动覆盖。
   - 可以先生成“待确认更新”，在 CRM 页面由人工确认。

4. 增加跟进提醒闭环。
   - 根据生日、保费到期日、长期未互动自动生成 followup。
   - 在机器人启动或配置页中展示今日待办。
   - 后续可加入主动触达策略，但要避免过度打扰客户。

5. 增加知识库接入。
   - 售中问题应优先检索保险知识库、产品资料、活动资料。
   - 需要区分“可直接回答”和“必须转人工”的问题。

6. 增加转人工工作流。
   - 当客户明确有购买意向、投诉、敏感问题、复杂健康/理赔问题时，标记 `needs_handoff`。
   - CRM 首页突出显示待转人工客户。

7. 优化 CRM 页面。
   - 增加今日待办视图。
   - 增加客户阶段看板。
   - 增加客户事件时间线。
   - 增加客户画像编辑的字段校验和日期选择器。

8. 增加测试。
   - 为客户数据库初始化、客户画像生成、日期筛选、联网检测快速跳过逻辑增加单元测试。

## 开发注意事项

1. 不要提交客户真实数据。
   - `data/`
   - `CustomerMemory/`
   - `*.db`
   - `*.sqlite`

2. 不要把 API Key 写入提交。

3. 修改客户数据库 schema 时，要考虑已有 SQLite 文件的兼容迁移。

4. 联网检测逻辑最初可以正常运行。当前优化只是为了减少每条消息都调用检测模型导致的成本和网络依赖，不要误删原有联网搜索流程。

5. 目前优先做私聊客户经营，不要提前扩大到群聊复杂场景。
