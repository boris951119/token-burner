import re
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

# 类型别名（内部使用）
_LogEntry = Dict[str, Any]

# 全局模式链：每个元素为 (name, priority, parse_func)
_patterns: List[Tuple[str, int, Callable[[str], Optional[_LogEntry]]]] = []

def _build_rfc3164_parser() -> Callable[[str], Optional[_LogEntry]]:
    """RFC3164 解析器工厂"""
    regex = re.compile(r'^<(\d{1,3})>\s*(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(.*)$')
    def parse(s: str) -> Optional[_LogEntry]:
        m = regex.match(s)
        if not m:
            return None
        pri = int(m.group(1))
        facility = pri >> 3
        severity = pri & 0x07
        return {
            'pri': pri,
            'facility': facility,
            'severity': severity,
            'timestamp': m.group(2),
            'hostname': m.group(3),
            'message': m.group(4),
            'format': 'rfc3164'
        }
    return parse

def _build_rfc5424_parser() -> Callable[[str], Optional[_LogEntry]]:
    """RFC5424 解析器工厂"""
    regex = re.compile(
        r'^<(\d{1,3})>\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\[.*?\])\s*(.*)$'
    )
    def parse(s: str) -> Optional[_LogEntry]:
        m = regex.match(s)
        if not m:
            return None
        pri = int(m.group(1))
        facility = pri >> 3
        severity = pri & 0x07
        return {
            'pri': pri,
            'facility': facility,
            'severity': severity,
            'version': int(m.group(2)),
            'timestamp': m.group(3),
            'hostname': m.group(4),
            'appname': m.group(5),
            'procid': m.group(6),
            'msgid': m.group(7),
            'structured_data': m.group(8),
            'message': m.group(9),
            'format': 'rfc5424'
        }
    return parse

def _json_parser(s: str) -> Optional[_LogEntry]:
    """JSON 解析器"""
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            data['format'] = 'json'
            return data
        return None
    except json.JSONDecodeError:
        return None

# 初始化内置模式
_patterns.append(('rfc3164', 10, _build_rfc3164_parser()))
_patterns.append(('rfc5424', 20, _build_rfc5424_parser()))
_patterns.append(('json', 30, _json_parser))

def detect_encoding(raw_bytes: bytes) -> str:
    """
    检测给定字节串的编码，采用 UTF-8 → GBK → Latin-1 降级策略。
    返回编码名称字符串。
    """
    # 尝试 UTF-8 严格解码
    try:
        raw_bytes.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        pass
    # 尝试 GBK
    try:
        raw_bytes.decode('gbk')
        return 'gbk'
    except UnicodeDecodeError:
        pass
    # 最后回退到 Latin-1（绝不会失败）
    return 'latin-1'

def parse_line(raw_bytes: bytes) -> Optional[_LogEntry]:
    """
    解析原始日志字节串，返回标准化 LogEntry 字典，解析失败返回 None。
    内部先进行编码检测与降级解码，再按优先级降序应用所有已注册模式。
    """
    if not raw_bytes:
        return None
    encoding = detect_encoding(raw_bytes)
    try:
        text = raw_bytes.decode(encoding)
    except UnicodeDecodeError:
        # 理论上不会发生，但防御性编程
        return None

    # 按优先级降序排序，高优先级先尝试
    sorted_patterns = sorted(_patterns, key=lambda x: x[1], reverse=True)
    for name, priority, parse_func in sorted_patterns:
        entry = parse_func(text)
        if entry is not None:
            return entry
    return None

def register_custom_pattern(name: str, regex: str, priority: int) -> bool:
    """
    注册自定义解析模式。成功返回 True，正则编译失败返回 False。
    自定义模式匹配时，若正则包含命名捕获组，则直接使用 groupdict；
    否则以整个匹配文本作为 message 字段。
    """
    try:
        compiled = re.compile(regex)
    except re.error:
        return False

    def custom_parse(s: str) -> Optional[_LogEntry]:
        m = compiled.match(s)
        if not m:
            return None
        # 优先使用命名组
        if compiled.groupindex:
            return dict(m.groupdict())
        # 否则返回整个匹配作为 message
        return {'message': m.group(0)}

    _patterns.append((name, priority, custom_parse))
    return True

if __name__ == '__main__':
    # 演示用法
    import sys

    # 测试 RFC3164
    raw1 = b'<13>Oct 11 22:14:15 myhost myapp[1234]: Hello world'
    print("RFC3164:", parse_line(raw1))

    # 测试 RFC5424
    raw2 = b'<34>1 2023-10-10T12:00:00Z myhost myapp 1234 ID47 [meta@123 key="value"] Test message'
    print("RFC5424:", parse_line(raw2))

    # 测试 JSON
    raw3 = b'{"timestamp": "2023-10-10T12:00:00Z", "message": "json log"}'
    print("JSON:", parse_line(raw3))

    # 注册自定义模式
    ok = register_custom_pattern("custom", r'^CUSTOM:(?P<msg>.*)$', 25)
    print("Custom registered:", ok)
    raw4 = b'CUSTOM:hello from custom'
    print("Custom pattern:", parse_line(raw4))

    # 编码检测演示
    print("Encoding of raw1:", detect_encoding(raw1))
    print("Encoding of raw4:", detect_encoding(raw4))
