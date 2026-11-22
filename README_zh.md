# Agent Loop 词典 Agent

[English](README.md) | 简体中文

这是一个从零搭建、仅含单个源文件的词典 Agent，使用 Python 和
[OpenAI Python SDK](https://github.com/openai/openai-python)。它演示了完整的
工具调用 Agent Loop：模型收到一个英语单词后调用 `lookup_word` 工具，读取工具
返回结果，再按固定格式输出中文词典内容。

## 功能特点

- **单文件实现**——所有应用代码都在 `agent.py` 中。
- **真正的 Agent Loop**——最多 10 轮；工具结果会追加回对话，直到模型不再请求
  调用工具。
- **只定义一个工具**——`lookup_word(word)` 查询有道词典并返回规范化 JSON 字符串。
- **严格工具定义**——function 定义中启用 `strict: True`。
- **固定输出格式**——最终回答严格按指定中文版式输出；接口未返回的板块写“无”，
  不编造内容。
- **不硬编码密钥**——API Key 在运行时读取，任何情况下都不打印。
- **完善的失败处理**——网络、HTTP、JSON 和模型错误都会被报告，且不会破坏格式
  约束。

## 环境要求

- Python 3.12+（开发机使用本机的 Python 3.14.10）。
- `openai` 包（`openai>=1.0`）。
- 可访问 `https://api.deepseek.com` 和 `https://dict.youdao.com/jsonapi`。

## 安装

```powershell
# 建议创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 安装唯一的三方依赖
python -m pip install "openai>=1.0"
```

macOS/Linux 使用 `source .venv/bin/activate` 激活虚拟环境。

## API Key 读取顺序

脚本不会把 API Key 写入仓库，按以下顺序解析：

1. DeepSeek Harness 凭据文件中的 `refs.DEEPSEEK_API_KEY`
   （`%USERPROFILE%\.dsh\.credentials.yaml`，或
   `$DSH_HOME/.credentials.yaml`）。也就是本 Harness 中添加的自定义 DeepSeek
   API Key。
2. 环境变量 `DEEPSEEK_API_KEY`。
3. 环境变量 `DEEPSEEK_ACCOUNT_API_KEY`（账户 API 回退）。
4. Harness 凭据文件中的 DeepSeek 账户令牌
   （`deepseek-account-platform/default` → `payload.token`），作为最后的回退。

因此，只要 Harness 凭据可读，脚本就会优先使用其中的自定义 Key；读取不到时再
尝试环境变量和账户回退。若找不到任何 Key，脚本会打印配置说明并退出。

> Key 只传给 OpenAI 客户端，不会被记录到日志、写入磁盘或放入工具返回值。

## 运行

```powershell
python agent.py
```

然后输入一个英语单词：

```text
请输入一个英语单词：apple
```

## 输出格式

```text
单词：<word>
音标：<接口返回时展示，否则省略此行>
中文含义：
- <词性 + 释义，每条一行>
例句：
- <英文例句>
  译文：<中文翻译>
派生词：
- <词形变化名称：形式，例如“复数：apples”>
```

规则：

- 接口未返回整个板块时，该板块输出“无”。
- 接口未返回音标时，整行“音标”省略。
- 模型不得编造释义、例句、音标或词形变化。
- 工具返回 `{"error": ...}` 时，模型直接说明查询失败及原因，不编造词典内容。

## Agent Loop 工作流程

1. 从命令行读取一个单词。
2. 用系统提示和用户单词初始化 `messages`。
3. 每轮把完整对话、`tools` 和 `tool_choice: "auto"` 发给模型。
4. 如果模型返回 `tool_calls`，执行 `lookup_word`，追加一条 assistant 消息和
   每个调用对应的 `role="tool"` 消息，然后进入下一轮。
5. 如果模型不再返回 `tool_calls`，打印最终回答并退出。
6. 如果 10 轮用完，打印“达到最大轮次，任务未完成”并退出。

## 工具返回结构

`lookup_word` 始终返回 JSON 字符串：

```json
{
  "word": "apple",
  "phonetic": "英 /ˈæp(ə)l/ 美 /ˈæp(ə)l/",
  "meanings": ["n. 苹果"],
  "examples": [{"en": "An apple a day keeps the doctor away.", "zh": "一天一苹果，医生远离我。"}],
  "derivatives": [{"name": "复数", "form": "apples"}]
}
```

所有字段始终存在。缺失数据用空字符串或空列表表示，不抛出中断异常。HTTP 或
JSON 解析失败时返回：

```json
{"error": "查询失败: <原因>"}
```

各字段的提取优先级：

| 字段 | 主要来源 | 回退来源 |
| --- | --- | --- |
| 音标 | `ec.word[0].usphone` / `ukphone` | `simple.word[0]` |
| 中文含义 | `ec.word[*].trs[*].tr[0].l.i[0]` | `simple`，再尝试 `web_trans` |
| 例句 | `auth_sents_part.sent` | `blng_sents_part.sent` 或 `sentence-pair` |
| 派生词 | `simple.wfs` | `ec.word[0].wfs` |

有道实际返回的权威例句常常只有英文 `foreign` 字段，没有中文 `zh` 字段。工具会
跳过这类不完整例句，回退到 `blng_sents_part` 的双语内容
（`sentence` / `sentence-translation`），绝不自行补写翻译。派生词同时兼容需求
中的扁平结构 `{"w": ..., "name": ...}` 和线上嵌套结构
`{"wf": {"name": ..., "value": ...}}`。

有道返回文本可能以 `@(#)@` 等 JSONP 前缀开头；工具会先截取第一个 `{` 到最后一个
`}` 之间的内容，再调用 `json.loads`。

## 模型

模型为 `deepseek-flash`，`base_url` 为 `https://api.deepseek.com`。

原始需求指定 `deepseek-v4.1-flash`。接入测试时，当前可用的自定义 Key 对该模型名
返回 HTTP 400，并明确说明只支持 `deepseek-flash` 和 `deepseek-v4-pro`；经确认后
改用 `deepseek-flash`。如果之后账户开放 `deepseek-v4.1-flash`，修改 `agent.py`
中的 `MODEL` 常量即可。

## 验证结果

2026-11-22 使用本机 Python 3.14.10、`openai` 3.57.0、Harness 自定义 Key 和
`deepseek-flash` 完成实测：

| 检查项 | 结果 |
| --- | --- |
| `lookup_word("apple")` | 有道实时数据：音标、1 条释义、3 条双语例句、`复数：apples` |
| `python agent.py` 输入 `apple` | 按固定格式完整输出 |
| 未知单词 | 省略音标行；`中文含义`、`例句`、`派生词` 均显示 `无` |
| JSONP 与回退结构 | 剥离 `@(#)@` 前缀；扁平/嵌套派生词和 `web_trans` 回退均可解析 |
| 模拟工具错误 | 输出 `查询失败: 模拟网络故障`，没有重复前缀 |
| 十轮循环桩 | 恰好 10 次模型调用后输出 `达到最大轮次，任务未完成` |
| HTTP 错误路径 | `{"error": "查询失败: HTTP 404"}` |
| 非 JSON 路径 | `{"error": "查询失败: JSON 解析失败: ..."}` |

验证过程中没有打印或提交任何 API Key。

## 项目结构

```text
.
├── agent.py
├── README.md
└── README_zh.md
```

## 说明

- 有道的 `jsonapi` 是非官方公开接口，可能随时变化。
- 本项目是教学用 Agent Loop 示例，不是生产级词典服务。
