# Codex VS Code 图片生成绕过方案

Codex VS Code 扩展当前会启动 `codex app-server`。在某些版本里，即使本地配置里已经关闭：

```toml
[features]
image_generation = false
```

`app-server` 这条路径发出的请求里仍然可能带上 `image_generation` 这类 Responses 内置工具。
如果自定义 Responses 兼容服务提供方不支持这些内置工具，可以通过本地代理在转发请求前把它们删掉。

这个绕过方案只应该影响中转站模式。账号模式下，如果 `~/.codex/config.toml` 没有 active
`model_provider`，封装脚本会直接运行真实 Codex，不启动代理。

## 本地命令

从 `tools/codex-vscode-strip-tools-proxy/` 安装后，可以使用下面这些命令。

手动启动：

```sh
~/.codex/bin/codex-strip-tools-start
```

停止：

```sh
~/.codex/bin/codex-strip-tools-stop
```

查看状态：

```sh
~/.codex/bin/codex-strip-tools-status
```

查看日志：

```sh
tail -f /tmp/codex_strip_tools_proxy.log
```

查看进程号文件：

```sh
cat /tmp/codex_strip_tools_proxy.pid
```

配合 VS Code Codex 扩展使用时，在 VS Code 全局 `settings.json` 中设置。Linux 默认配置文件路径是
`~/.config/Code/User/settings.json`。`chatgpt.cliExecutable` 需要写绝对路径，不要在 JSON 里写 `~`。

```json
"chatgpt.cliExecutable": "/home/<user>/.codex/bin/codex-vscode-wrapper"
```

修改后重载 VS Code。如果 VS Code 使用了自定义 `--user-data-dir` 或独立 Profile，需要在对应用户数据目录下找 `User/settings.json`。

## 默认配置

默认使用：

```text
封装脚本: /home/<user>/.codex/bin/codex-vscode-wrapper
代理地址: http://127.0.0.1:18765/v1
上游地址: 从 ~/.codex/config.toml 当前 active provider 的 base_url 读取
日志文件: /tmp/codex_strip_tools_proxy.log
进程号文件: /tmp/codex_strip_tools_proxy.pid
```

封装脚本只会在检测到中转站 provider 时自动启动代理。账号模式下不会启动代理。

## 移除绕过方案

1. 从 VS Code 全局 `settings.json` 中移除 `chatgpt.cliExecutable`。Linux 默认路径是 `~/.config/Code/User/settings.json`。
2. 停止代理：

```sh
~/.codex/bin/codex-strip-tools-stop
```

3. 可选：删除已安装脚本：

```sh
rm -f ~/.codex/bin/codex-strip-tools-proxy.py ~/.codex/bin/codex-vscode-wrapper
```
