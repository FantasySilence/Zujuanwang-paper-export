# 组卷网试卷导出工具

从 [组卷网](https://zujuan.xkw.com/) 抓取试卷（需要登录），解析成结构化数据，并生成可直接打印的 Word 文档。

- 爬虫：**Scrapy** + **Playwright**（站点正文由 JS 渲染，必须用真实浏览器）
- 交互：**CMD 窗口菜单**，粘贴试卷网址即可，无需记命令
- 产出：**Word 文档**（干净试卷正文 + 可选答案）+ **JSON / CSV**（用于数据分析）

> 请仅导出你自己有权访问的试卷，控制抓取频率，不要用于批量转载或商业分发。

---

## 快速开始

环境已经准备好（`.venv` 内含全部依赖）。推荐直接双击：

```
start.bat
```

或者在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe run.py
```

菜单长这样：

```
----------------------------------------------------------------------------------------------------------------------

  ______     _                                            _____                      ______                       _
 |___  /    (_)                                          |  __ \                    |  ____|                     | |
    / /_   _ _ _   _  __ _ _ ____      ____ _ _ __   __ _| |__) |_ _ _ __   ___ _ __| |__  __  ___ __   ___ _ __| |_
   / /| | | | | | | |/ _` | '_ \ \ /\ / / _` | '_ \ / _` |  ___/ _` | '_ \ / _ \ '__|  __| \ \/ / '_ \ / _ \| '__| __|
  / /_| |_| | | |_| | (_| | | | \ V  V / (_| | | | | (_| | |  | (_| | |_) |  __/ |  | |____ >  <| |_) | (_) | |  | |_
 /_____\__,_| |\__,_|\__,_|_| |_|\_/\_/ \__,_|_| |_|\__, |_|   \__,_| .__/ \___|_|  |______/_/\_\ .__/ \___/|_|   \__|
           _/ |                                      __/ |          | |                         | |
          |__/                                      |___/           |_|                         |_|

----------------------------------------------------------------------------------------------------------------------

  组卷网试卷导出工具   ·   Scrapy + Playwright
  中间产物：.temp      输出目录：output
  作者：Fantasy_Silence   ·   仓库地址：https://github.com/FantasySilence/Zujuanwang-paper-export

----------------------------------------------------------------------------------------------------------------------

  账号：已登录（本地登录态有效）

----------------------------------------------------------------------------------------------------------------------

  [1] 导出试卷（输入试卷网址）
  [2] 登录 / 更换账号
  [3] 用缓存数据重新生成 Word
  [4] 查看 / 清理缓存
  [0] 退出

请选择: 
```

选 `1`，粘贴形如 `https://zujuan.xkw.com/3p2856667.html` 的网址，按提示回答「是否导答案」「文件叫什么名字」，等十几秒，Word 就会出现在 `output\` 目录里。

### 也可以直接用命令行

```powershell
# 导出单份试卷
.\.venv\Scripts\python.exe run.py https://zujuan.xkw.com/3p2856667.html

# 自定义文件名（不填就用试卷原标题）
.\.venv\Scripts\python.exe run.py 3p2856667 -n "九年级英语期中卷"

# 同时导出答案解析（注意每日查看额度）
.\.venv\Scripts\python.exe run.py 3p2856667 --answers

# 只导出前 5 题的答案解析，节省额度
.\.venv\Scripts\python.exe run.py 3p2856667 --answers --answers-limit 5

# 忽略本地缓存，重新访问站点（例如试卷更新了）
.\.venv\Scripts\python.exe run.py 3p2856667 --no-cache

# 生成后不自动打开 Word
.\.venv\Scripts\python.exe run.py 3p2856667 --no-open
```

网址参数也接受纯试卷编号（`3p2856667` 或 `2856667`）。

---

## 产出说明

### `output\`：最终 Word 文档

文件名默认取自试卷标题，也可以用 `-n` 或菜单里的提示自己起，例如：

```
output\四川省成都树德中学2025-2026学年九年级上学期期中考试英语试卷.docx
output\九年级英语期中卷.docx
```

文档内容刻意保持干净，只保留试卷本身：

1. 试卷标题 + 一条分隔线（不再显示题数、难度、考查范围等元信息）
2. 按题型分节（`一、选词填空`、`二、补全对话`……），逐题还原段落、表格、图片、下划线空格
3. 可选「参考答案与解析」附录（`--answers`，答案为组卷网以图片形式提供的解析）

不含文章大意（`【文章大意】` 提示）、试卷分析附录和页脚，导出来就能直接印给学生。

排版为 A4、宋体 + Times New Roman；选项表格保留网页的对齐方式，但不加边框。

### `.temp\`：中间产物（可随时整体删除）

| 目录 | 内容 | 复用方式 |
| --- | --- | --- |
| `.temp\httpcache\` | 渲染后的页面 HTML 缓存 | 同一份试卷第二次导出直接读缓存，不再访问站点 |
| `.temp\data\` | `*.paper.json`（完整结构）、`*.questions.csv`（一题一行）、`*.page.html`（原始页面） | 数据分析、离线重生成 Word |
| `.temp\images\` | 题目图片（按 URL 哈希命名） | 重生成 Word 时不再重复下载 |
| `.temp\auth\auth.json` | Playwright 登录态 | 免重复登录 |
| `.temp\logs\` | `scrapy.log`、`last_run.json` | 排查失败原因 |

### 数据分析

`*.paper.json` 是完整的结构化数据（`sections[].questions[].blocks[]` 保留了段落/表格/图片的层级与行内格式），
`*.questions.csv` 是扁平的「一题一行」表，可直接用 Excel 或 pandas 打开：

```python
import pandas as pd
df = pd.read_csv(r".temp\data\3p2856667.questions.csv")
df.groupby("type_label")["difficulty_score"].mean()
```

---

## 工作原理

```
run.py（CMD 菜单）
   │  输入网址、显示进度
   ├─ 子进程：python -m zujuan.run_spider --url ...      ← 每份试卷一次干净运行
   │     └─ Scrapy 引擎
   │          ├─ PlaywrightDownloadHandler（自定义下载器）
   │          │     └─ Chromium 打开页面 → 等渲染完成 → 交回 HTML
   │          └─ PaperSpider.parse → extractor.parse_paper → PaperJsonPipeline
   │                                                └─ 写 .temp\data\*.json / *.csv
   └─ docx_writer.build_document → output\*.docx（带图片下载缓存）
```

几个关键设计：

- **为什么自写下载处理器**：站点的题目正文由 JS 渲染，普通 HTTP 请求拿到的 HTML 是空壳。
  处理器按 Scrapy 2.13+ 的异步下载器协议实现，只把 `meta['playwright']=True` 的请求交给浏览器。
- **为什么 Playwright 跑在独立线程**：Windows 上 Twisted 默认的 `SelectorEventLoop` 不支持
  `subprocess_exec`，而 Playwright 需要启动 node 驱动子进程。所以给它单独一个线程 + `ProactorEventLoop`，
  浏览器在该循环里长期存活，主线程只提交协程。
- **为什么要有 HTTP 缓存**：抓一次渲染页约 5～10 秒，缓存后重跑只要 2 秒；调排版时非常有用。
- **答案解析为什么要 `--answers`**：答案藏在点击后才加载的图片里，需要逐题点击，且站方限制
  「每日最多查看 30 道试题的答案解析」，所以默认不抓、支持 `--answers-limit` 限流。

---

## 目录结构

```
run.py                     CMD 交互入口
start.bat                  双击运行（UTF-8 代码页 + 结束暂停）
scrapy.cfg                 Scrapy 项目配置入口
requirements.txt           依赖（pip freeze）
zujuan/
  cli.py                   菜单、进度、缓存管理
  auth.py                  登录态检查 / 交互式登录 / 旧登录态迁移
  run_spider.py            子进程入口：跑一次 paper 爬虫
  spiders/paper.py         试卷爬虫（入口、校验、写状态）
  playwright_handler.py    Playwright 下载处理器
  extractor.py             HTML → 结构化数据（纯函数，可离线测试）
  docx_writer.py           结构化数据 → Word
  images.py                图片下载 + 本地缓存
  pipelines.py             JSON / CSV 落盘
  items.py, status.py, paths.py, settings.py
```

---

## 常见问题

**登录态过期**（`登录态已失效，请重新运行登录`）
菜单 `2` 会打开浏览器，手动登录完成后脚本自动检测并保存 `.temp\auth\auth.json`。
登录态有效期约 1 天，过期后重跑一次菜单 2 即可（不需要退出工具）。

**提示「该试卷需要更高权限」**
该试卷对当前账号需要会员/下载券，工具无法绕过，只能换一份试卷或升级账号。

**提示「站点要求输入验证码」**
打开菜单 `--no-cache` 重试；仍不行就在浏览器里手动打开该试卷页面完成验证，再回来导出。

**答案解析图片是「加载超时，请重新进入页面查看」**
组卷网的答案图片 URL 带时效签名。`--answers` 导出时请**当场生成 Word**（菜单 1 会自动生成），
不要隔天再用旧 JSON 重新生成；已下载的答案图片会缓存进 `.temp\images`，只要当时成功下载就能反复复用。

**文件名想换个叫法**
命令行用 `-n "名字"`，菜单里在输入网址后会问「保存的文件名」，直接回车就用试卷原标题。
名字里的 `\ / : * ? " < > |` 会被自动换成下划线，`.docx` 后缀不用自己加。

**Word 里提示文件被占用**
生成时会检测到并自动另存为 `标题_20260101_120000.docx`。

**想换按钮文字 / 字体 / 页边距**
改 `zujuan\docx_writer.py` 顶部的常量与 `DocxOptions`；`font_body`、`font_heading`、`body_size` 都可以按需调整。

**想批量抓多份试卷**
直接循环调用即可，爬虫本身是标准 Scrapy spider：

```powershell
foreach ($id in @("3p2856667","3p3506327")) {
  .\.venv\Scripts\python.exe -m zujuan.run_spider --url $id
}
```

`run_spider` 每份试卷返回 0/1，并把结果写进 `.temp\logs\last_run.json`，便于脚本判断。

---

## 环境

- Python 3.12，Windows 10/11
- 主要依赖：`Scrapy 2.19`、`playwright 1.64`、`python-docx 1.2`、`beautifulsoup4`、`lxml`、`pandas`
- 若 `Playwright` 提示缺少浏览器：

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```
