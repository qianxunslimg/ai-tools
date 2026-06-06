# Codex VS Code 工具过滤代理

这是一个临时绕过方案，用来处理 Codex IDE 扩展在本地功能开关已关闭时，仍然把 Responses
内置工具放进请求里的问题。

代理监听本机端口，把请求转发到 OpenAI 兼容的 Responses API 入口，并在转发前从
`POST /v1/responses` JSON 请求体中移除不支持的内置工具。

适用场景：

- Codex CLI 使用 `--disable image_generation` 可以正常工作。
- VS Code Codex 扩展仍然在 `tools` 里发送 `{"type":"image_generation"}`。
- 自定义服务提供方拒绝不支持的内置工具。

这只是本地临时绕过方案。等上游 Codex 问题修复后，应移除它。

## 实现目标

这个工具需要同时支持两种使用模式：

- 账号模式：`~/.codex/config.toml` 中没有 active `model_provider`，例如把所有
  `model_provider` 配置注释掉。此时封装脚本直接运行真实 Codex，不启动本地代理，也不覆盖
  `base_url`。
- 中转站模式：`~/.codex/config.toml` 中启用了某个 provider，或同时设置
  `CODEX_VSCODE_MODEL_PROVIDER` 和 `CODEX_STRIP_TOOLS_UPSTREAM`。此时 VS Code Codex
  请求会先经过本地代理，由代理移除 `image_generation` 等当前扩展 bug 下无法关闭的工具。

## 文件

- `codex-strip-tools-proxy.py`：监听本机端口的代理，用来移除指定工具类型。
- `codex-vscode-wrapper`：给 VS Code `chatgpt.cliExecutable` 使用的封装脚本。

## 安装

在本仓库执行：

```sh
mkdir -p ~/.codex/bin
cp tools/codex-vscode-strip-tools-proxy/codex-strip-tools-proxy.py ~/.codex/bin/
cp tools/codex-vscode-strip-tools-proxy/codex-vscode-wrapper ~/.codex/bin/
chmod +x ~/.codex/bin/codex-strip-tools-proxy.py ~/.codex/bin/codex-vscode-wrapper
```

在 VS Code 全局 `settings.json` 中设置。Linux 默认配置文件路径是
`~/.config/Code/User/settings.json`。`chatgpt.cliExecutable` 需要写绝对路径，不要在 JSON 里写 `~`。

```json
"chatgpt.cliExecutable": "/home/<user>/.codex/bin/codex-vscode-wrapper"
```

修改后重载 VS Code。如果 VS Code 使用了自定义 `--user-data-dir` 或独立 Profile，需要在对应用户数据目录下找 `User/settings.json`。

## 启动代理

通常不需要手动启动，封装脚本会按需启动代理。启动脚本会等待代理端口 ready；
如果 daemon 子进程启动失败，脚本会直接退出并打印最近日志。

手动启动：

```sh
~/.codex/bin/codex-strip-tools-start
```

## 停止代理

```sh
~/.codex/bin/codex-strip-tools-stop
```

## 查看状态

```sh
~/.codex/bin/codex-strip-tools-status
tail -f /tmp/codex_strip_tools_proxy.log
```

等价的原始命令。通常不需要显式传 `UPSTREAM_BASE_URL`，启动脚本会从
`~/.codex/config.toml` 当前未注释的 `model_provider` 读取对应 provider 的
`base_url`：

```sh
~/.codex/bin/codex-strip-tools-start

python3 ~/.codex/bin/codex-strip-tools-proxy.py --stop
```

## 封装脚本行为

`codex-vscode-wrapper`:

1. 如果同时设置了 `CODEX_VSCODE_MODEL_PROVIDER` 和 `CODEX_STRIP_TOOLS_UPSTREAM`，进入中转站模式。
2. 否则读取 `~/.codex/config.toml` 当前未注释的 `model_provider`。
3. 如果没有 active `model_provider`，进入账号模式，直接运行真实 Codex。
4. 如果有 active provider，读取该 provider 对应的 `base_url`，作为本地代理的上游地址。
5. 如果本机代理还没启动，就先启动代理，并确认代理端口 ready。
6. 如果代理已经启动但上游地址不同，先停止旧代理再启动新代理。
7. 运行 Codex 扩展内置的 `codex` 二进制。
8. 覆盖当前 provider 的 `base_url`，使其使用 `http://127.0.0.1:18765/v1`。
9. 尽力关闭 `image_generation` 和 `web_search` 功能开关，作为额外保护。

脚本当前也会尝试加载 `~/.zshenv`，这是为了兼容本机已有 API Key 环境。`.zshenv`
继承问题不是这个代理要解决的核心问题；如果只配置中转站 API 和环境变量，参考
`docs/codex-vscode-relay-api/`。

假设当前 active provider 是 `my-relay`，封装脚本最终会执行类似：

```sh
~/.vscode/extensions/openai.chatgpt-26.602.40724-linux-x64/bin/linux-x86_64/codex \
  -c 'model_provider="my-relay"' \
  -c 'model_providers.my-relay.base_url="http://127.0.0.1:18765/v1"' \
  -c 'features.image_generation=false' \
  -c 'features.web_search=false'
```

## 环境变量

需要时可以通过这些环境变量覆盖默认值。如果同时设置
`CODEX_VSCODE_MODEL_PROVIDER` 和 `CODEX_STRIP_TOOLS_UPSTREAM`，封装脚本会直接使用这两个值，
不要求 `~/.codex/config.toml` 中存在同名 provider。

```sh
export CODEX_REAL_BIN=/path/to/extension/bin/linux-x86_64/codex
export CODEX_CONFIG_FILE=/path/to/config.toml
export CODEX_VSCODE_MODEL_PROVIDER=my-relay
export CODEX_STRIP_TOOLS_UPSTREAM=https://relay.example.com/v1
export CODEX_STRIP_TOOLS_PROXY_HOST=127.0.0.1
export CODEX_STRIP_TOOLS_PROXY_PORT=18765
export CODEX_STRIP_TOOLS_PROXY_LOG_FILE=/tmp/codex_strip_tools_proxy.log
export CODEX_STRIP_TOOLS_UPSTREAM_FILE=/tmp/codex_strip_tools_proxy.upstream
export STRIP_RESPONSE_TOOLS=image_generation,web_search,web_search_preview
```

代理转发请求时不会把请求头写进 `curl` 命令行参数，避免 `Authorization` 出现在
`ps` 进程列表中。

## 卸载

移除 VS Code 全局配置。Linux 默认路径是 `~/.config/Code/User/settings.json`：

```json
"chatgpt.cliExecutable": "/home/<user>/.codex/bin/codex-vscode-wrapper"
```

然后停止代理：

```sh
python3 ~/.codex/bin/codex-strip-tools-proxy.py --stop
```

可选清理：

```sh
rm -f ~/.codex/bin/codex-strip-tools-proxy.py ~/.codex/bin/codex-vscode-wrapper
```
