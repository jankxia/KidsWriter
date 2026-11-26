<div align="center">

# 阅答题 KidsWriter v2.0

给 KidsReader / CleanMiTV 电视端配套的 Web 工具：**写稿、答题、出题、阅读**四合一；文章与题库都放在夸克网盘（OpenList），电视端和本工具共用同一套数据，电视上不用做任何同步操作。

</div>

## 它做什么

顶部四个页签，按登录角色显隐：

| 页签 | 功能 | 管理员 | 一般账户 |
| --- | --- | :---: | :---: |
| 写稿器 | AI 批量写文章（文字 + 封面 + 逐句配音），确认后一键上传网盘 | ✅ | ❌ |
| 答题库 | 按学段 / 年级 / 学科浏览题库，在线答题、判分、看解析 | ✅ | ✅ |
| 加题目 | AI 出题 / 手工录入，本地校验后上传网盘并重建清单 | ✅ | ❌ |
| 阅读 | 浏览网盘文章，逐句朗读（小学逐字注音、逐句音频） | ✅ | ✅ |

### 写稿器（沿用 v1.x 能力）

- **写稿**：AI 先出 4–6 段大纲，再逐段写，字数不够自动补写；分段失败退回整篇重写。
- **切句**：按句末标点切句，纯标点句直接丢弃。
- **配音**：edge-tts 逐句合成 `001.mp3…`，音色、语速、并发可配。
- **配封面**：按标题关键词从 `covers/` 图池挑图，命中不了按 id 哈希兜底。
- **手动上传**：生成完停在「待上传」，确认标题、字数、句数、封面无误再上传；顺序是建目录 → mp3 → cover → **最后**写 json，电视端不会扫到半成品。

### 答题库

- 题库清单三档回退：内网 OpenList `http://192.168.1.24:5244` → 外网 `https://list.717611.xyz` → GitHub Release。
- 清单与题目均来自网盘 `夸克/CleanMiTV/quiz`，与 CleanMiTV 电视端同库；本地可配离线目录联调。
- 每题字段：`id / st / g / s / q / o / a / l`（学段 / 年级 / 学科 / 题干 / 选项 / 答案 / 解析）。

### 加题目

- **AI 出题**：选学段、年级、学科、数量，调大模型生成候选。
- **手工录入**：逐条填写题干、选项、答案、解析。
- **校验**：答案必须落在选项内、题干与选项非空；通过后暂存 `data/quiz-edit/`，确认再上传网盘并重建 `index.json` 清单。

### 阅读

- 文章 json 在网盘 `<root>/content/ai/<id>.json`，根目录默认 `夸克/KidsReader`。
- 列表按年级 / 分类过滤；点开一篇看正文、逐句注音与逐句音频直链。

## 账户体系

账户存于 `data/accounts.json`，登录态以 HttpOnly Cookie（token）保存在内存会话表，重启后需重新登录。

| 角色 | 可见页签 | 可调用接口 | 默认账户 |
| --- | --- | --- | --- |
| 管理员 `admin` | 写稿器 / 答题库 / 加题目 / 阅读 | 全部接口，含写稿、出题、上传、删题、账户管理 | `admin / jankxia`（首次启动自动建） |
| 一般账户 `user` | 答题库 / 阅读 | 仅答题与阅读类只读接口；写稿、出题、上传、删题、账户管理一律 403 | 由管理员在「账户管理」新增 |

- 账户之间数据隔离：登录只决定能看到哪些功能，题库与文章仍是网盘同一份。
- 管理员通过右上角「账户管理」新增账户、改密码、删除；系统保护最后一个管理员不被删除。
- 未登录访问任何业务接口返回 `未登录`；管理类接口对一般账户返回 403。

## 两种跑法

**本机**：双击 `启动.bat`，浏览器打开 `http://127.0.0.1:8122`。

**Docker**（挂 NAS 上，关机自启一直在）：

```yaml
# compose.yaml
services:
  kidswriter:
    image: kidswriter:v2.0
    build: .
    container_name: kidswriter
    restart: unless-stopped
    ports:
      - "8122:8122"
    volumes:
      - /vol3/1000/kidswriter/data:/app/data
    environment:
      TZ: Asia/Shanghai
      KIDSWRITER_PORT: "8122"

networks:
  default:
    driver: bridge
    ipam:
      config:
        - subnet: 172.32.0.0/24
```

```bash
docker compose up -d --build
```

数据都在挂载的 `data/`：`config.json`、`accounts.json`、`quiz-edit/`、`输出/<文章id>/`。容器重启后未上传的稿子回到「待上传」，不会丢。

## 配置

首次启动生成 `config.json`（照 `config.example.json` 填）：

- 网盘：`server` / `user` / `password`；题库目录 `quiz_root`（默认 `夸克/CleanMiTV/quiz`）；文章根 `root`（默认 `夸克/KidsReader`）。
- AI：`ai_base` / `ai_model` / `api_key`；音色 `voice`、语速 `rate`、并发 `conc`。
- 题库三档镜像与学段、学科标签在后端内置，一般无需改。

`config.json`、`accounts.json` 含密码与 Key，**不要提交到仓库**。

## 目录

```
KidsWriter/
├─ 启动.bat            本机一键启动
├─ 童阅写稿器.py       后端：写稿 + 配音 + 上传 + 题库/阅读/鉴权接口（标准库 + edge-tts）
├─ 界面.html           单页界面（四页签 + 登录 + 账户管理弹层）
├─ covers/             封面图池，丢新 .jpg 进来即参与匹配
├─ Dockerfile
├─ compose.yaml
├─ config.example.json 配置样例
└─ data/                运行数据（挂载进容器）
   ├─ config.json
   ├─ accounts.json
   ├─ quiz-edit/       待上传题目暂存
   └─ 输出/<文章id>/    json + mp3 + cover.jpg + .uploaded 标记
```

## 题库包（quiz-pack）

`quiz-pack/` 是与 CleanMiTV 对齐的基线题库：`index.json` 清单 + 12 个年级文件（`primary-1..6`、`middle-7..9`、`high-10..12`），每文件 1000 题共 12000 题，清单版本 `2026-11-15-12000-v4`。上传 OpenList 后落在 `夸克/CleanMiTV/quiz/`，电视端与本工具同时读取。

## 已知边界

- 一篇一张封面，不做每句插图（阅读页目前没有句图位）。
- 小学一到六年级逐字注音（`tokens: [{h, p}]`，带声调与「一 / 不」变调、轻声）；中学与名著不注音。电视端需 KidsReader 1.0.9 及以上才解析 `tokens`。
- 自动校验目前只覆盖"答案落在选项内、题干选项非空、字数够不够、句子能否合成"，文章与题目的内容质量取决于模型发挥。
- 会话 token 存内存，容器重启后全部登录态失效；账户与密码落盘 `accounts.json`。

## 版本

- `v2.0`：新增答题库、加题目、阅读三页；接入 OpenList 共享题库；新增管理员 / 一般账户体系与权限隔离；管理接口鉴权；配置脱敏。
- `v1.4`：列表勾选框与「全选 / 删除选中 N」批量删除；正在生成篇目禁选、跳过并在日志说明。
- `v1.3`：给电视端开接口——`POST /api/start` 返回本批文章 id，`GET /api/tasks` 精简任务列表。
- `v1.2`：小学文章逐字注音（tokens + 声调 + 变调），Docker 镜像内置 pypinyin。
- `v1.1`：分阶段状态与进度、随机主题可刷新、生成完手动上传、Docker 镜像、重启不丢稿、可删除本地稿。
