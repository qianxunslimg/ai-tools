#!/usr/bin/env python3
import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def parse_csv(value):
    return {item.strip() for item in value.split(",") if item.strip()}


class ToolStrippingProxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    upstream = urllib.parse.urlparse(os.environ.get("UPSTREAM_BASE_URL", "https://api.openai.com/v1"))
    strip_tools = parse_csv(
        os.environ.get(
            "STRIP_RESPONSE_TOOLS",
            "image_generation,web_search,web_search_preview",
        )
    )
    upstream_timeout_seconds = float(os.environ.get("UPSTREAM_TIMEOUT_SECONDS", "300"))

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def do_GET(self):
        self._proxy()

    def do_POST(self):
        self._proxy()

    def do_PUT(self):
        self._proxy()

    def do_PATCH(self):
        self._proxy()

    def do_DELETE(self):
        self._proxy()

    def _read_body(self):
        content_length = self.headers.get("Content-Length")
        if not content_length:
            return b""
        return self.rfile.read(int(content_length))

    def _filtered_body(self, body):
        if self.command != "POST" or not self.path.rstrip("/").endswith("/responses"):
            return body

        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            return body

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            self.log_message("无法解析请求 JSON，保持原样转发：%s", exc)
            return body

        tools = payload.get("tools")
        if not isinstance(tools, list):
            return body

        before = len(tools)
        payload["tools"] = [
            tool for tool in tools
            if not (isinstance(tool, dict) and tool.get("type") in self.strip_tools)
        ]
        removed = before - len(payload["tools"])
        if removed:
            self.log_message("已移除 %d 个 Responses 工具：%s", removed, ",".join(sorted(self.strip_tools)))

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _upstream_path(self):
        upstream_prefix = self.upstream.path.rstrip("/")
        request_path = self.path if self.path.startswith("/") else "/" + self.path
        if upstream_prefix and request_path.startswith(upstream_prefix + "/"):
            return request_path
        return upstream_prefix + request_path

    def _upstream_url(self):
        return f"{self.upstream.scheme}://{self.upstream.netloc}{self._upstream_path()}"

    @staticmethod
    def _curl_config_quote(value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    @classmethod
    def _curl_config(cls, headers):
        config_lines = []
        for key, value in headers.items():
            header_line = f"{key}: {value}"
            if "\r" in header_line or "\n" in header_line:
                raise ValueError(f"Unsupported newline in request header {key!r}")
            config_lines.append(f"header = {cls._curl_config_quote(header_line)}")
        if not config_lines:
            return b""
        return ("\n".join(config_lines) + "\n").encode("utf-8")

    def _curl_command(self, body, config_fd):
        curl_cmd = [
            "curl",
            "-sS",
            "-N",
            "--http1.1",
            "--connect-timeout",
            "30",
            "--suppress-connect-headers",
            "-i",
        ]
        if config_fd is not None:
            curl_cmd.extend(["--config", f"/dev/fd/{config_fd}"])
        curl_cmd.extend([
            "-X",
            self.command,
            self._upstream_url(),
        ])
        if self.upstream_timeout_seconds > 0:
            curl_cmd.extend(["--max-time", str(self.upstream_timeout_seconds)])
        if body or self.command in {"POST", "PUT", "PATCH"}:
            curl_cmd.extend(["--data-binary", "@-"])
        return curl_cmd

    def _start_curl(self, body, headers):
        curl_config = self._curl_config(headers)
        config_file = None
        config_fd = None
        pass_fds = ()
        if curl_config:
            config_file = tempfile.TemporaryFile()
            config_file.write(curl_config)
            config_file.flush()
            config_file.seek(0)
            config_fd = config_file.fileno()
            pass_fds = (config_fd,)

        try:
            proc = subprocess.Popen(
                self._curl_command(body, config_fd),
                stdin=subprocess.PIPE if body or self.command in {"POST", "PUT", "PATCH"} else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=pass_fds,
            )
        finally:
            if config_file is not None:
                config_file.close()
        if proc.stdin is not None:
            try:
                if body:
                    proc.stdin.write(body)
                proc.stdin.close()
            except BrokenPipeError:
                pass
        return proc

    @staticmethod
    def _split_first_header_block(buffer):
        candidates = []
        for delimiter in (b"\r\n\r\n", b"\n\n"):
            index = buffer.find(delimiter)
            if index >= 0:
                candidates.append((index, len(delimiter)))
        if not candidates:
            return None
        index, delimiter_size = min(candidates, key=lambda item: item[0])
        return buffer[:index], buffer[index + delimiter_size:]

    @staticmethod
    def _parse_header_lines(header_block):
        return header_block.decode("iso-8859-1", "replace").splitlines()

    @staticmethod
    def _parse_status(header_lines):
        status_line = next((line for line in header_lines if line.startswith("HTTP/")), "")
        status_parts = status_line.split(" ", 2)
        status = int(status_parts[1]) if len(status_parts) > 1 and status_parts[1].isdigit() else 502
        reason = status_parts[2] if len(status_parts) > 2 else ""
        return status, reason

    @staticmethod
    def _is_proxy_connect_header(status, reason):
        return status == 200 and reason.lower() == "connection established"

    @staticmethod
    def _terminate_process(proc):
        if proc is None:
            return
        if proc.poll() is None:
            proc.kill()
        proc.wait()

    def _read_response_header(self, proc):
        if proc.stdout is None:
            raise RuntimeError("curl stdout pipe is not available")

        buffer = b""
        while True:
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                return_code = proc.wait()
                stderr = proc.stderr.read() if proc.stderr is not None else b""
                message = stderr.decode("utf-8", "replace").strip()
                raise RuntimeError(
                    message
                    or f"curl exited before upstream response headers, code={return_code}"
                )
            buffer += chunk

            while True:
                split_result = self._split_first_header_block(buffer)
                if split_result is None:
                    break
                header_block, buffer = split_result
                header_lines = self._parse_header_lines(header_block)
                status, reason = self._parse_status(header_lines)
                if 100 <= status < 200 or self._is_proxy_connect_header(status, reason):
                    continue
                return header_lines, buffer

    def _stream_response_body(self, proc, first_body_chunk):
        try:
            if first_body_chunk:
                self.wfile.write(first_body_chunk)
                self.wfile.flush()

            if proc.stdout is None:
                return

            while True:
                chunk = os.read(proc.stdout.fileno(), 8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except BrokenPipeError:
            self._terminate_process(proc)
            return

        return_code = proc.wait()
        if return_code != 0:
            stderr = proc.stderr.read() if proc.stderr is not None else b""
            message = stderr.decode("utf-8", "replace").strip() or f"curl 退出码 {return_code}"
            self.log_message("上游流式响应异常结束：%s", message)

    @staticmethod
    def _last_header_block(header_bytes):
        normalized = header_bytes.replace(b"\r\n", b"\n")
        blocks = [block for block in normalized.split(b"\n\n") if block.startswith(b"HTTP/")]
        return blocks[-1] if blocks else normalized

    def _proxy(self):
        body = self._filtered_body(self._read_body())
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
            and key.lower()
            not in {
                "accept-encoding",
                "content-length",
                "host",
                "user-agent",
            }
        }
        if body:
            headers["Content-Length"] = str(len(body))
        else:
            headers.pop("Content-Length", None)

        proc = None
        try:
            proc = self._start_curl(body, headers)
            header_lines, first_body_chunk = self._read_response_header(proc)
            status, reason = self._parse_status(header_lines)

            self.send_response(status, reason)
            for line in header_lines:
                if not line or line.startswith("HTTP/") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                if key.lower() in HOP_BY_HOP_HEADERS or key.lower() == "content-length":
                    continue
                self.send_header(key, value.strip())
            self.send_header("Connection", "close")
            self.end_headers()
            self._stream_response_body(proc, first_body_chunk)
        except Exception as exc:
            self._terminate_process(proc)
            self.log_message("代理错误：%s", exc)
            error = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(error)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(error)
        finally:
            self.close_connection = True


def daemonize(log_path):
    pid = os.fork()
    if pid:
        return pid

    os.setsid()
    second_pid = os.fork()
    if second_pid:
        os._exit(0)

    with open("/dev/null", "rb", buffering=0) as stdin, open(log_path, "ab", buffering=0) as log:
        os.dup2(stdin.fileno(), sys.stdin.fileno())
        os.dup2(log.fileno(), sys.stdout.fileno())
        os.dup2(log.fileno(), sys.stderr.fileno())

    return None


def stop(pid_path):
    try:
        with open(pid_path, "r", encoding="utf-8") as pid_file:
            pid = int(pid_file.read().strip())
    except FileNotFoundError:
        print("代理未运行")
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        os.unlink(pid_path)
    except FileNotFoundError:
        pass
    print(f"已停止代理进程号 {pid}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--pid-file", default="/tmp/codex_strip_tools_proxy.pid")
    parser.add_argument("--log-file", default="/tmp/codex_strip_tools_proxy.log")
    args = parser.parse_args()

    if args.stop:
        stop(args.pid_file)
        return

    if args.daemon:
        parent_pid = daemonize(args.log_file)
        if parent_pid:
            print(f"已启动代理管理进程号 {parent_pid}；守护进程的进程号文件：{args.pid_file}")
            return

    server = ThreadingHTTPServer((args.host, args.port), ToolStrippingProxy)
    with open(args.pid_file, "w", encoding="utf-8") as pid_file:
        pid_file.write(str(os.getpid()))
    print(
        f"监听地址 http://{args.host}:{args.port}，上游地址={ToolStrippingProxy.upstream.geturl()}，"
        f"移除工具={','.join(sorted(ToolStrippingProxy.strip_tools))}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
