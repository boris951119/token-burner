import pytest
import json
from line_parser import parse_line, detect_encoding, register_custom_pattern


class TestDetectEncoding:
    def test_utf8_detection(self):
        raw_bytes = "Hello 世界".encode('utf-8')
        assert detect_encoding(raw_bytes) == 'utf-8'

    def test_gbk_detection(self):
        raw_bytes = "你好世界".encode('gbk')
        # Since UTF-8 will fail first, GBK should be detected
        result = detect_encoding(raw_bytes)
        assert result in ['gbk', 'latin-1']

    def test_latin1_fallback(self):
        # Raw bytes that are invalid in both UTF-8 and GBK but valid in Latin-1
        raw_bytes = bytes(range(128, 256))  # Non-ASCII bytes
        assert detect_encoding(raw_bytes) == 'latin-1'

    def test_empty_bytes(self):
        assert detect_encoding(b'') == 'utf-8'

    def test_ascii_bytes(self):
        raw_bytes = b"Hello World"
        assert detect_encoding(raw_bytes) == 'utf-8'


class TestParseLine:
    def test_rfc3164_valid(self):
        raw_bytes = b'<13>Oct 11 22:14:15 myhost myapp[1234]: Hello world'
        result = parse_line(raw_bytes)
        assert result is not None
        assert result['format'] == 'rfc3164'
        assert result['pri'] == 13
        assert result['facility'] == 1
        assert result['severity'] == 5
        assert result['timestamp'] == 'Oct 11 22:14:15'
        assert result['hostname'] == 'myhost'
        assert result['message'] == 'myapp[1234]: Hello world'

    def test_rfc5424_valid(self):
        raw_bytes = b'<34>1 2023-10-10T12:00:00Z myhost myapp 1234 ID47 [meta@123 key="value"] Test message'
        result = parse_line(raw_bytes)
        assert result is not None
        assert result['format'] == 'rfc5424'
        assert result['pri'] == 34
        assert result['facility'] == 4
        assert result['severity'] == 2
        assert result['version'] == 1
        assert result['timestamp'] == '2023-10-10T12:00:00Z'
        assert result['hostname'] == 'myhost'
        assert result['appname'] == 'myapp'
        assert result['procid'] == '1234'
        assert result['msgid'] == 'ID47'
        assert result['structured_data'] == '[meta@123 key="value"]'
        assert result['message'] == 'Test message'

    def test_json_valid(self):
        data = {"timestamp": "2023-10-10T12:00:00Z", "message": "json log"}
        raw_bytes = json.dumps(data).encode('utf-8')
        result = parse_line(raw_bytes)
        assert result is not None
        assert result['format'] == 'json'
        assert result['timestamp'] == '2023-10-10T12:00:00Z'
        assert result['message'] == 'json log'

    def test_invalid_json(self):
        raw_bytes = b'{"invalid": json}'
        result = parse_line(raw_bytes)
        assert result is None

    def test_invalid_rfc3164(self):
        raw_bytes = b'<999>Invalid format here'
        result = parse_line(raw_bytes)
        assert result is None

    def test_invalid_rfc5424(self):
        raw_bytes = b'<999>Invalid format here too'
        result = parse_line(raw_bytes)
        assert result is None

    def test_empty_bytes(self):
        result = parse_line(b'')
        assert result is None

    def test_non_matching_bytes(self):
        raw_bytes = b'Totally invalid log format'
        result = parse_line(raw_bytes)
        assert result is None

    def test_unicode_in_rfc3164(self):
        raw_bytes = '<13>Oct 11 22:14:15 myhost myapp[1234]: Hello 世界'.encode('utf-8')
        result = parse_line(raw_bytes)
        assert result is not None
        assert result['format'] == 'rfc3164'


class TestRegisterCustomPattern:
    def test_register_valid_pattern_with_named_groups(self):
        success = register_custom_pattern("test_pattern", r'^TEST:(?P<msg>.*)$', 40)
        assert success is True

        raw_bytes = b'TEST:This is a test message'
        result = parse_line(raw_bytes)
        assert result is not None
        assert 'msg' in result
        assert result['msg'] == 'This is a test message'

    def test_register_valid_pattern_without_named_groups(self):
        success = register_custom_pattern("simple_pattern", r'^SIMPLE:(.*)$', 50)
        assert success is True

        raw_bytes = b'SIMPLE:Simple message'
        result = parse_line(raw_bytes)
        assert result is not None
        assert 'message' in result
        assert result['message'] == 'SIMPLE:Simple message'

    def test_register_invalid_regex(self):
        success = register_custom_pattern("bad_pattern", r'[unclosed', 60)
        assert success is False

    def test_priority_ordering(self):
        # Register a high-priority custom parser
        success = register_custom_pattern("high_priority", r'^HP:(?P<hp_msg>.*)$', 100)
        assert success is True

        raw_bytes = b'HP:High priority message'
        result = parse_line(raw_bytes)
        assert result is not None
        assert 'hp_msg' in result
        assert result['hp_msg'] == 'High priority message'

    def test_custom_pattern_after_builtin(self):
        # Register a lower priority pattern
        success = register_custom_pattern("low_priority", r'^LP:(?P<lp_msg>.*)$', 5)
        assert success is True

        # Use an RFC3164 formatted string - should match RFC3164 since it has higher priority
        raw_bytes = b'<13>Oct 11 22:14:15 myhost LP:should_not_match'
        result = parse_line(raw_bytes)
        assert result is not None
        assert result['format'] == 'rfc3164'
        assert 'lp_msg' not in result
