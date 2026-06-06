# Codex VS Code 中转站 API 配置

本文说明如何让 VS Code 中的 Codex/ChatGPT 扩展使用 OpenAI 兼容的中转站 API。配置分为三部分：

- 在本机保存 API Key。
- 在 Codex 配置中增加 provider。
- 确保 VS Code 启动的 `codex app-server` 能读取同一组环境变量。

工具过滤代理是另一个独立问题。只有当扩展错误发送不受支持的 Responses 内置工具时，才需要额外接入 `tools/codex-vscode-strip-tools-proxy/`。该代理的 wrapper 会读取当前 active provider，不需要在 wrapper 里写死某个中转站。

## 1. 保存 API Key

把 API Key 放在本机 shell 环境中，例如 `~/.zshenv`：

```sh
export MY_RELAY_API_KEY="<api-key>"
```

`MY_RELAY_API_KEY` 可以替换成团队约定的变量名，但必须和 Codex provider 中的 `env_key` 保持一致。

## 2. 配置 Codex Provider

编辑本机 `~/.codex/config.toml`，增加一个 OpenAI 兼容 provider：

```toml
[model_providers.my-relay]
name = "My Relay"
base_url = "https://relay.example.com/v1"
env_key = "MY_RELAY_API_KEY"
wire_api = "responses"
```

启用该 provider：

```toml
model_provider = "my-relay"
```

如果只是预置配置，不想立即切换，把 `model_provider` 保持为原值即可。

## 3. 处理 VS Code 环境继承

从终端启动 VS Code 时，扩展通常能继承当前 shell 的环境变量。通过桌面入口、远程窗口或已运行的 VS Code 进程启动时，`codex app-server` 可能读不到后来写入 `~/.zshenv` 的 API Key。

更稳定的做法是包装 VS Code 扩展内置的 `codex` 二进制：

1. 在扩展目录中把原 `codex` 重命名为 `codex.real`。
2. 在原 `codex` 路径写入下面的 wrapper。
3. 重新加载 VS Code，使扩展重新启动 `codex app-server`。

```sh
#!/usr/bin/env bash
set -e

if [ -f "${HOME}/.zshenv" ]; then
  . "${HOME}/.zshenv"
fi

exec "$(dirname "$0")/codex.real" "$@"
```

这个 wrapper 只解决环境变量继承问题，不负责改写请求地址或请求体。需要改写请求的场景应单独使用对应工具。

## 4. 验证

先确认 shell 能读到 API Key：

```sh
zsh -lc 'test -n "$MY_RELAY_API_KEY" && echo env_ok'
```

再用 Codex CLI 验证 provider：

```sh
codex exec -c model_provider="my-relay" "hello"
```

如果 VS Code 中仍未生效，检查运行中的 `codex app-server` 启动参数：

```sh
ps -eo pid,ppid,comm,args | rg -i 'codex|code'
```

重点确认：

- `codex app-server` 是否已经重启。
- `model_provider` 是否被命令行参数覆盖。
- `base_url` 是否指向预期中转站。
- `env_key` 对应的环境变量是否存在于启动链路中。
- 如果启用了工具过滤代理，命令行里的 `base_url` 会先指向本地代理地址；真实上游由代理从 active provider 读取。

## 注意事项

- 不要把真实 API Key 写入仓库文件、脚本模板或 issue。
- 不要在公共文档中记录内部中转站域名、账号名或本机绝对路径。
- VS Code 扩展升级后可能覆盖扩展目录中的 `codex` wrapper，升级后需要重新检查。
