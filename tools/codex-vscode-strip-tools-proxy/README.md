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

通常不需要手动启动，封装脚本会按需启动代理。

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

等价的原始命令：

```sh
UPSTREAM_BASE_URL=https://muyuan.do/v1 \
python3 ~/.codex/bin/codex-strip-tools-proxy.py --host 127.0.0.1 --port 18765 --daemon

python3 ~/.codex/bin/codex-strip-tools-proxy.py --stop
```

## 封装脚本行为

`codex-vscode-wrapper`:

1. 加载 `~/.zshenv`，让 VS Code 启动的 Codex 能读到服务提供方 API 密钥。
2. 如果本机代理还没启动，就先启动代理。
3. 运行 Codex 扩展内置的 `codex` 二进制。
4. 覆盖 `muyuan` 服务提供方，使其使用 `http://127.0.0.1:18765/v1`。
5. 尽力关闭 `image_generation` 和 `web_search` 功能开关，作为额外保护。

默认封装命令：

```sh
~/.vscode/extensions/openai.chatgpt-26.602.40724-linux-x64/bin/linux-x86_64/codex \
  -c 'model_provider="muyuan"' \
  -c 'model_providers.muyuan.base_url="http://127.0.0.1:18765/v1"' \
  -c 'features.image_generation=false' \
  -c 'features.web_search=false'
```

## 环境变量

需要时可以通过这些环境变量覆盖默认值：

```sh
export CODEX_REAL_BIN=/path/to/extension/bin/linux-x86_64/codex
export CODEX_STRIP_TOOLS_UPSTREAM=https://muyuan.do/v1
export CODEX_STRIP_TOOLS_PROXY_HOST=127.0.0.1
export CODEX_STRIP_TOOLS_PROXY_PORT=18765
export CODEX_STRIP_TOOLS_PROXY_LOG_FILE=/tmp/codex_strip_tools_proxy.log
export STRIP_RESPONSE_TOOLS=image_generation,web_search,web_search_preview
```

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
