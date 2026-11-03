"""Validated application settings and the deliberately small answer contract."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass
class AppSettings:
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    capture_dir: str = ""
    auto_cleanup: bool = True
    retention_minutes: int = 10
    explanation: bool = False
    question_type: str = "auto"
    reasoning: str = "low"
    request_timeout: int = 60
    capture_timeout: int = 5
    image_format: str = "PNG"
    jpeg_quality: int = 90
    max_image_edge: int = 0
    theme: str = "light"
    overlay_font_size: int = 24
    overlay_opacity: int = 95
    overlay_topmost: bool = True
    overlay_remember_position: bool = True
    overlay_position: list[int] | None = None
    overlay_mode: str = "target"
    hotkey_enabled: bool = True
    query_hotkey: str = "Ctrl+Alt+Q"
    answer_hide_seconds: int = 0
    proxy_mode: str = "system"
    proxy_url: str = ""
    log_level: str = "INFO"

    def validate(self) -> None:
        """Reject unsupported values before they become network or file actions."""
        if not isinstance(self.base_url, str) or any(c.isspace() for c in self.base_url):
            raise ValueError("接口地址不能包含空白字符。")
        try:
            endpoint = urlsplit(self.base_url)
            endpoint.port
        except ValueError as exc:
            raise ValueError("接口地址格式不正确。") from exc
        if not endpoint.hostname or endpoint.username or endpoint.password:
            raise ValueError("接口地址须包含主机名，不能包含用户名或密码。")
        loopback = endpoint.hostname.lower() == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(endpoint.hostname).is_loopback
        except ValueError:
            pass
        if endpoint.scheme != "https" and not (endpoint.scheme == "http" and loopback):
            raise ValueError("远程接口必须使用 HTTPS；仅本机回环接口允许 HTTP。")
        if endpoint.query or endpoint.fragment:
            raise ValueError("接口 Base URL 不能包含查询参数或片段。")
        if not isinstance(self.model, str) or not self.model.strip() or any(
            ord(c) < 32 for c in self.model
        ):
            raise ValueError("模型名称不能为空或包含控制字符。")
        if not isinstance(self.capture_dir, str):
            raise ValueError("截图目录必须为文本路径。")
        choices = {
            "question_type": {"auto", "single", "multiple", "boolean"},
            "reasoning": {"none", "low", "high", "max"},
            "image_format": {"PNG", "JPEG"},
            "theme": {"light", "dark"},
            "proxy_mode": {"system", "none", "custom"},
            "log_level": {"DEBUG", "INFO", "WARNING", "ERROR"},
            "overlay_mode": {"target", "free"},
        }
        for name, allowed in choices.items():
            value = getattr(self, name)
            if not isinstance(value, str) or value not in allowed:
                raise ValueError(f"设置项 {name} 的取值不受支持。")
        ranges = {
            "retention_minutes": (1, 43200),
            "request_timeout": (1, 600),
            "capture_timeout": (1, 60),
            "jpeg_quality": (1, 100),
            "max_image_edge": (0, 8192),
            "overlay_font_size": (12, 72),
            "overlay_opacity": (20, 100),
            "answer_hide_seconds": (0, 86400),
        }
        for name, (minimum, maximum) in ranges.items():
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"设置项 {name} 必须为 {minimum} 到 {maximum} 之间的整数。")
        if 0 < self.max_image_edge < 256:
            raise ValueError("图片最大边长须为 0（原图）或至少 256 像素。")
        for name in (
            "auto_cleanup", "explanation", "overlay_topmost", "overlay_remember_position", "hotkey_enabled"
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"设置项 {name} 必须为开关值。")
        if self.overlay_position is not None and (
            not isinstance(self.overlay_position, list)
            or len(self.overlay_position) != 2
            or any(type(value) is not int for value in self.overlay_position)
        ):
            raise ValueError("悬浮窗位置必须包含两个整数坐标。")
        if not isinstance(self.query_hotkey, str):
            raise ValueError("快捷键格式不正确。")
        if self.hotkey_enabled:
            parse_hotkey(self.query_hotkey)
        if not isinstance(self.proxy_url, str):
            raise ValueError("代理地址必须为文本。")
        if self.proxy_mode == "custom":
            try:
                proxy = urlsplit(self.proxy_url)
                port = proxy.port
            except ValueError as exc:
                raise ValueError("代理地址格式不正确。") from exc
            if (
                proxy.scheme not in {"http", "socks5"}
                or not proxy.hostname
                or port is None
                or proxy.username
                or proxy.password
                or proxy.query
                or proxy.fragment
                or proxy.path not in {"", "/"}
            ):
                raise ValueError("代理须为 http://主机:端口 或 socks5://主机:端口，不含凭据。")


def parse_hotkey(value: str) -> tuple[int, int, str]:
    """Return Win32 modifiers/key and a canonical, single-chord shortcut."""
    if not isinstance(value, str):
        raise ValueError("快捷键格式不正确。")
    parts = value.upper().replace(" ", "").split("+")
    modifiers = {"CTRL": 2, "ALT": 1, "SHIFT": 4}
    if not parts or len(set(parts[:-1])) != len(parts[:-1]) or any(p not in modifiers for p in parts[:-1]):
        raise ValueError("快捷键只支持 Ctrl、Alt、Shift 和一个字母、数字或 F1～F11。")
    key = parts[-1]
    if re.fullmatch(r"F(?:[1-9]|1[01])", key):
        virtual_key = 0x70 + int(key[1:]) - 1
    elif re.fullmatch(r"[A-Z0-9]", key) and any(p in {"CTRL", "ALT"} for p in parts[:-1]):
        virtual_key = ord(key)
    else:
        raise ValueError("字母或数字需搭配 Ctrl 或 Alt；功能键支持 F1～F11。")
    flags = sum(modifiers[p] for p in parts[:-1])
    ordered = [name.title() for name in ("CTRL", "ALT", "SHIFT") if name in parts[:-1]]
    return flags, virtual_key, "+".join(ordered + [key])


@dataclass(frozen=True)
class AnswerResult:
    status: str
    question_type: str
    answers: tuple[str, ...]
    explanation: str = ""

    @property
    def display_text(self) -> str:
        if self.status != "ok":
            return {
                "unreadable": "题目不完整或无法识别，请重新框选。",
                "multiple_questions": "检测到多道题，请仅框选一道题。",
                "uncertain": "暂时无法确定答案，请核对题目或提高思考强度。",
            }.get(self.status, "未获得有效答案。")
        if self.question_type == "boolean":
            return "正确" if self.answers == ("true",) else "错误"
        return "、".join(self.answers)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("AI 响应含重复字段。")
        result[key] = value
    return result


def parse_answer(
    content: str,
    expected_type: str = "auto",
    include_explanation: bool = False,
) -> AnswerResult:
    """Parse JSON only; never guess an answer from surrounding prose."""
    if expected_type not in {"auto", "single", "multiple", "boolean"}:
        raise ValueError("指定题型不受支持。")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("AI 返回空内容，请重新查询。")
    try:
        payload = json.loads(content, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("AI 未返回有效 JSON，请重新查询。") from exc
    if not isinstance(payload, dict):
        raise ValueError("AI 响应必须为 JSON 对象。")
    if set(payload) - {"status", "type", "answers", "explanation"}:
        raise ValueError("AI 响应含不受支持的字段。")
    status = payload.get("status")
    question_type = payload.get("type")
    answers = payload.get("answers")
    explanation = payload.get("explanation", "")
    if not isinstance(status, str) or status not in {
        "ok", "unreadable", "multiple_questions", "uncertain"
    }:
        raise ValueError("AI 响应状态不正确。")
    if not isinstance(question_type, str) or question_type not in {
        "single", "multiple", "boolean"
    }:
        raise ValueError("AI 响应题型不正确。")
    if not isinstance(answers, list) or any(not isinstance(item, str) for item in answers):
        raise ValueError("AI 答案须为字符串数组。")
    if not isinstance(explanation, str) or len(explanation) > 1000:
        raise ValueError("AI 简短解析格式不正确或过长。")
    if status != "ok":
        if answers:
            raise ValueError("无法确定答案的响应不得同时包含答案。")
        return AnswerResult(status, question_type, (), explanation if include_explanation else "")
    if expected_type != "auto" and question_type != expected_type:
        raise ValueError("AI 返回题型与指定题型不一致。")
    if question_type == "boolean":
        if len(answers) != 1 or answers[0] not in {"true", "false"}:
            raise ValueError("判断题答案必须为 true 或 false。")
    else:
        if not answers or any(re.fullmatch(r"[A-Z]", item) is None for item in answers):
            raise ValueError("选择题答案必须为大写单字母选项。")
        if len(answers) != len(set(answers)):
            raise ValueError("AI 返回了重复选项。")
        if question_type == "single" and len(answers) != 1:
            raise ValueError("单选题必须且只能返回一个选项。")
        answers = sorted(answers)
    return AnswerResult(status, question_type, tuple(answers), explanation if include_explanation else "")
