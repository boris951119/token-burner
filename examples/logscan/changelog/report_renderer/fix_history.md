- [2026-09-06 10:19:22] ### 第 1 次修复
失败报告: 接口门禁失败：[missing] 契约声明导出 'RenderResult' 但代码未实现——修改指导: 请在模块顶层定义常量 RenderResult = ...
时间: 2026-09-06 10:19:22


- [2026-09-06 10:19:57] ### 第 2 次修复
失败报告: exit_code=1 stderr= stdout=F..FF..FFFF.FFFFFF                                                       [100%]
================================== FAILURES ===================================
_____ TestRenderReport.test_basic_functionality_with_parsed_line_objects ______

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0EB70>

    def test_basic_functionality_with_parsed_line_objects(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = {
            'total_errors': 2,
            'by_level': {'ERROR': 1, 'WARNING': 1},
            'by_module': {'auth': 1, 'network': 1}
        }
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Connection failed'),
            ParsedLine(seq_no=2, timestamp='2025-01-01 10:05:00', level='WARNING', message='Slow response')
        ]
        config = {'ascii_only': True, 'include_stats': True}
    
        # Act
        result = render_report(data, errors, config)
    
        # Assert
        assert hasattr(result, 'markdown')
        assert hasattr(result, 'stats')
        assert 'Error Report' in result.markdown
>       assert 'Total Errors: 2' in result.markdown
E       AssertionError: assert 'Total Errors: 2' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 2\n- **By Level:**\n  - ERROR: 1\n  - WARNING: 1\n- **By Module:**\n  - auth: 1\n  - network: 1\n\n## Error Timeline\n\n*No errors recorded.*\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 2\n- **By Level:**\n  - ERROR: 1\n  - WARNING: 1\n- **By Module:**\n  - auth: 1\n  - network: 1\n\n## Error Timeline\n\n*No errors recorded.*\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 2\n- **By Level:**\n  - ERROR: 1\n  - WARNI...corded.*\n', stats={'total_errors': 2, 'by_level': {'ERROR': 1, 'WARNING': 1}, 'by_module': {'auth': 1, 'network': 1}}).markdown

test_report_renderer.py:29: AssertionError
_______________ TestRenderReport.test_ascii_conversion_enabled ________________

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0CBF0>

    def test_ascii_conversion_enabled(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = {}
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Test ñ message')
        ]
        config = {'ascii_only': True}
    
        # Act
        result = render_report(data, errors, config)
    
        # Assert
>       assert '?' in result.markdown  # Non-ASCII character replaced with ?
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       AssertionError: assert '?' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 0\n\n## Error Timeline\n\n*No errors recorded.*\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 0\n\n## Error Timeline\n\n*No errors recorded.*\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 0\n\n## Error Timeline\n\n*No errors recorded.*\n', stats={'total_errors': 0, 'by_level': {}, 'by_module': {}}).markdown

test_report_renderer.py:76: AssertionError
_______________ TestRenderReport.test_ascii_conversion_disabled _______________

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0CE90>

    def test_ascii_conversion_disabled(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = {}
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Test ñ message')
        ]
        config = {'ascii_only': False}
    
        # Act
        result = render_report(data, errors, config)
    
        # Assert
>       assert 'ñ' in result.markdown  # Non-ASCII character preserved
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       AssertionError: assert 'ñ' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 0\n\n## Error Timeline\n\n*No errors recorded.*\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 0\n\n## Error Timeline\n\n*No errors recorded.*\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 0\n\n## Error Timeline\n\n*No errors recorded.*\n', stats={'total_errors': 0, 'by_level': {}, 'by_module': {}}).markdown

test_report_renderer.py:91: AssertionError
___ TestRenderReport.test_calculate_by_level_from_errors_when_not_provided ____

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0D700>

    def test_calculate_by_level_from_errors_when_not_provided(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = {}  # No by_level provided
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Error 1'),
            ParsedLine(seq_no=2, timestamp='2025-01-01 10:05:00', level='WARNING', message='Warning 1'),
            ParsedLine(seq_no=3, timestamp='2025-01-01 10:10:00', level='ERROR', message='Error 2')
        ]
        config = {'ascii_only': True, 'include_stats': True}
    
        # Act
        result = render_report(data, errors, config)
    
        # Assert
>       assert result.stats['by_level']['ERROR'] == 2
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'ERROR'

test_report_renderer.py:138: KeyError
___________________ TestRenderReport.test_mixed_error_types ___________________

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0DA30>

    def test_mixed_error_types(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = {'total_errors': 2}
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Object error'),
            {'seq_no': 2, 'timestamp': '2025-01-01 10:05:00', 'level': 'INFO', 'message': 'Dict error'}
        ]
        config = {'ascii_only': True, 'include_stats': True}
    
        # Act
        result = render_report(data, errors, config)
    
        # Assert
>       assert 'Object error' in result.markdown
E       AssertionError: assert 'Object error' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 2\n- **By Level:**\n  - INFO: 1\n\n## Error Timeline\n\n| Seq | T...Message    |\n|-----|---------------------|-------|------------|\n| 2   | 2025-01-01 10:05:00 | INFO  | Dict error |\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 2\n- **By Level:**\n  - INFO: 1\n\n## Error Timeline\n\n| Seq | T...Message    |\n|-----|---------------------|-------|------------|\n| 2   | 2025-01-01 10:05:00 | INFO  | Dict error |\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 2\n- **By Level:**\n  - INFO: 1\n\n## Error...  | 2025-01-01 10:05:00 | INFO  | Dict error |\n', stats={'total_errors': 2, 'by_level': {'INFO': 1}, 'by_module': {}}).markdown

test_report_renderer.py:155: AssertionError
______________ TestRenderReport.test_none_values_in_parsed_line _______________

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0D970>

    def test_none_values_in_parsed_line(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = {}
        errors = [
            ParsedLine(seq_no=None, timestamp=None, level=None, message=None)
        ]
        config = {'ascii_only': True, 'include_stats': True}
    
        # Act
        result = render_report(data, errors, config)
    
        # Assert
>       assert result.stats['total_errors'] == 1
E       assert 0 == 1

test_report_renderer.py:171: AssertionError
______________ TestRenderReport.test_invalid_data_type_handling _______________

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0D490>

    def test_invalid_data_type_handling(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = "invalid_data"  # String instead of dict
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Test')
        ]
        config = {}
    
        # Act
        result = render_report(data, errors, config)
    
        # Assert
>       assert result.stats['total_errors'] == 1  # Calculated from errors length
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       assert 0 == 1

test_report_renderer.py:187: AssertionError
________________ TestRenderReport.test_large_number_of_errors _________________

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0CCB0>

    def test_large_number_of_errors(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = {}
        errors = [
            ParsedLine(seq_no=i, timestamp=f'2025-01-01 10:{i:02d}:00', level='INFO', message=f'Message {i}')
            for i in range(100)
        ]
        config = {'ascii_only': True, 'include_stats': True}
    
        # Act
        result = render_report(data, errors, config)
    
        # Assert
>       assert result.stats['total_errors'] == 100
E       assert 0 == 100

test_report_renderer.py:216: AssertionError
_____________ TestRenderReport.test_special_characters_in_content _____________

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0C620>

    def test_special_characters_in_content(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = {}
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='|SEPARATOR|', message='Contains | pipe char')
        ]
        config = {'ascii_only': True, 'include_stats': True}
    
        # Act
        result = render_report(data, errors, config)
    
        # Assert
>       assert result.stats['total_errors'] == 1
E       assert 0 == 1

test_report_renderer.py:233: AssertionError
_______________ TestRenderReport.test_unicode_level_and_message _______________

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0DF40>

    def test_unicode_level_and_message(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = {}
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ÉRRÖR', message='Méssägë wîth ünïcödé')
        ]
        config = {'ascii_only': True}
    
        # Act
        result = render_report(data, errors, config)
    
        # Assert
>       assert '?' in result.markdown  # Unicode chars should be replaced
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       AssertionError: assert '?' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 0\n\n## Error Timeline\n\n*No errors recorded.*\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 0\n\n## Error Timeline\n\n*No errors recorded.*\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 0\n\n## Error Timeline\n\n*No errors recorded.*\n', stats={'total_errors': 0, 'by_level': {}, 'by_module': {}}).markdown

test_report_renderer.py:249: AssertionError
_______ TestRenderReport.test_unicode_level_and_message_ascii_disabled ________

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0DF10>

    def test_unicode_level_and_message_ascii_disabled(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = {}
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ÉRRÖR', message='Méssägë wîth ünïcödé')
        ]
        config = {'ascii_only': False}
    
        # Act
        result = render_report(data, errors, config)
    
        # Assert
>       assert 'ÉRRÖR' in result.markdown  # Unicode chars should be preserved
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       AssertionError: assert 'ÉRRÖR' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 0\n\n## Error Timeline\n\n*No errors recorded.*\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 0\n\n## Error Timeline\n\n*No errors recorded.*\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 0\n\n## Error Timeline\n\n*No errors recorded.*\n', stats={'total_errors': 0, 'by_level': {}, 'by_module': {}}).markdown

test_report_renderer.py:264: AssertionError
_______________ TestRenderReport.test_all_none_fields_in_error ________________

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0E270>

    def test_all_none_fields_in_error(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = {}
        errors = [
            ParsedLine(seq_no=None, timestamp=None, level=None, message=None),
            {'seq_no': None, 'timestamp': None, 'level': None, 'message': None}
        ]
        config = {'ascii_only': True, 'include_stats': True}
    
        # Act
        result = render_report(data, errors, config)
    
        # Assert
>       assert result.stats['total_errors'] == 2
E       assert 1 == 2

test_report_renderer.py:281: AssertionError
_________________ TestRenderReport.test_default_config_values _________________

self = <test_report_renderer.TestRenderReport object at 0x0000021BCBA0E5D0>

    def test_default_config_values(self):
        # Arrange
        ParsedLine = namedtuple('ParsedLine', ['seq_no', 'timestamp', 'level', 'message'])
        data = {'total_errors': 1}
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Test')
        ]
        # No config passed
    
        # Act
        result = render_report(data, errors)
    
        # Assert
        assert 'Summary' in result.markdown  # Default include_stats is True
>       assert '?' in result.markdown  # Default ascii_only is True
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       AssertionError: assert '?' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 1\n\n## Error Timeline\n\n*No errors recorded.*\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 1\n\n## Error Timeline\n\n*No errors recorded.*\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 1\n\n## Error Timeline\n\n*No errors recorded.*\n', stats={'total_errors': 1, 'by_level': {}, 'by_module': {}}).markdown

test_report_renderer.py:298: AssertionError
=========================== short test summary info ===========================
FAILED test_report_renderer.py::TestRenderReport::test_basic_functionality_with_parsed_line_objects
FAILED test_report_renderer.py::TestRenderReport::test_ascii_conversion_enabled
FAILED test_report_renderer.py::TestRenderReport::test_ascii_conversion_disabled
FAILED test_report_renderer.py::TestRenderReport::test_calculate_by_level_from_errors_when_not_provided
FAILED test_report_renderer.py::TestRenderReport::test_mixed_error_types - As...
FAILED test_report_renderer.py::TestRenderReport::test_none_values_in_parsed_line
FAILED test_report_renderer.py::TestRenderReport::test_invalid_data_type_handling
FAILED test_report_renderer.py::TestRenderReport::test_large_number_of_errors
FAILED test_report_renderer.py::TestRenderReport::test_special_characters_in_content
FAILED test_report_renderer.py::TestRenderReport::test_unicode_level_and_message
FAILED test_report_renderer.py::TestRenderReport::test_unicode_level_and_message_ascii_disabled
FAILED test_report_renderer.py::TestRenderReport::test_all_none_fields_in_error
FAILED test_report_renderer.py::TestRenderReport::test_default_config_values
13 failed, 5 passed in 0.25s
 timeout=30s
时间: 2026-09-06 10:19:57


- [2026-09-06 10:21:13] ### 第 3 次修复
失败报告: exit_code=1 stderr= stdout=FF.F..FFF.....F...                                                       [100%]
================================== FAILURES ===================================
______ TestRenderReport.test_basic_functionality_with_parsedline_objects ______

self = <test_report_renderer.TestRenderReport object at 0x00000206EE0DC470>

    def test_basic_functionality_with_parsedline_objects(self):
        data = {
            'total_errors': 2,
            'by_level': {'ERROR': 1, 'WARNING': 1},
            'by_module': {'auth': 1, 'network': 1}
        }
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Connection failed'),
            ParsedLine(seq_no=2, timestamp='2025-01-01 10:05:00', level='WARNING', message='Slow response')
        ]
        result = render_report(data, errors)
    
        assert isinstance(result, RenderResult)
        assert 'Error Report' in result.markdown
>       assert 'Total Errors: 2' in result.markdown
E       AssertionError: assert 'Total Errors: 2' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 2\n- **By Level:**\n  - ERROR: 1\n  - WARNING: 1\n- **By Module:*...  | 2025-01-01 10:00:00 | ERROR   | Connection failed |\n| 2   | 2025-01-01 10:05:00 | WARNING | Slow response     |\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 2\n- **By Level:**\n  - ERROR: 1\n  - WARNING: 1\n- **By Module:*...  | 2025-01-01 10:00:00 | ERROR   | Connection failed |\n| 2   | 2025-01-01 10:05:00 | WARNING | Slow response     |\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 2\n- **By Level:**\n  - ERROR: 1\n  - WARNI...se     |\n', stats={'total_errors': 2, 'by_level': {'ERROR': 1, 'WARNING': 1}, 'by_module': {'auth': 1, 'network': 1}}).markdown

test_report_renderer.py:23: AssertionError
_________ TestRenderReport.test_basic_functionality_with_dict_objects _________

self = <test_report_renderer.TestRenderReport object at 0x00000206EE0DC740>

    def test_basic_functionality_with_dict_objects(self):
        data = {
            'total_errors': 2,
            'by_level': {'ERROR': 1, 'WARNING': 1},
            'by_module': {'auth': 1, 'network': 1}
        }
        errors = [
            {'seq_no': 1, 'timestamp': '2025-01-01 10:00:00', 'level': 'ERROR', 'message': 'Connection failed'},
            {'seq_no': 2, 'timestamp': '2025-01-01 10:05:00', 'level': 'WARNING', 'message': 'Slow response'}
        ]
        result = render_report(data, errors)
    
        assert isinstance(result, RenderResult)
        assert 'Error Report' in result.markdown
>       assert 'Total Errors: 2' in result.markdown
E       AssertionError: assert 'Total Errors: 2' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 2\n- **By Level:**\n  - ERROR: 1\n  - WARNING: 1\n- **By Module:*...  | 2025-01-01 10:00:00 | ERROR   | Connection failed |\n| 2   | 2025-01-01 10:05:00 | WARNING | Slow response     |\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 2\n- **By Level:**\n  - ERROR: 1\n  - WARNING: 1\n- **By Module:*...  | 2025-01-01 10:00:00 | ERROR   | Connection failed |\n| 2   | 2025-01-01 10:05:00 | WARNING | Slow response     |\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 2\n- **By Level:**\n  - ERROR: 1\n  - WARNI...se     |\n', stats={'total_errors': 2, 'by_level': {'ERROR': 1, 'WARNING': 1}, 'by_module': {'auth': 1, 'network': 1}}).markdown

test_report_renderer.py:45: AssertionError
_____________ TestRenderReport.test_missing_config_uses_defaults ______________

self = <test_report_renderer.TestRenderReport object at 0x00000206EE0DD250>

    def test_missing_config_uses_defaults(self):
        data = {
            'total_errors': 1,
            'by_level': {'ERROR': 1},
            'by_module': {}
        }
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Test error')
        ]
        result = render_report(data, errors)  # No config provided
    
        assert isinstance(result, RenderResult)
        assert 'Error Report' in result.markdown
>       assert 'Total Errors: 1' in result.markdown
E       AssertionError: assert 'Total Errors: 1' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 1\n- **By Level:**\n  - ERROR: 1\n\n## Error Timeline\n\n| Seq | ...Message    |\n|-----|---------------------|-------|------------|\n| 1   | 2025-01-01 10:00:00 | ERROR | Test error |\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 1\n- **By Level:**\n  - ERROR: 1\n\n## Error Timeline\n\n| Seq | ...Message    |\n|-----|---------------------|-------|------------|\n| 1   | 2025-01-01 10:00:00 | ERROR | Test error |\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 1\n- **By Level:**\n  - ERROR: 1\n\n## Erro... | 2025-01-01 10:00:00 | ERROR | Test error |\n', stats={'total_errors': 1, 'by_level': {'ERROR': 1}, 'by_module': {}}).markdown

test_report_renderer.py:80: AssertionError
___________ TestRenderReport.test_include_stats_true_shows_summary ____________

self = <test_report_renderer.TestRenderReport object at 0x00000206EE0DDB50>

    def test_include_stats_true_shows_summary(self):
        data = {
            'total_errors': 1,
            'by_level': {'ERROR': 1},
            'by_module': {'auth': 1}
        }
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Test error')
        ]
        config = {'include_stats': True}
        result = render_report(data, errors, config)
    
        assert isinstance(result, RenderResult)
        assert 'Summary' in result.markdown
>       assert 'Total Errors: 1' in result.markdown
E       AssertionError: assert 'Total Errors: 1' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 1\n- **By Level:**\n  - ERROR: 1\n- **By Module:**\n  - auth: 1\n...Message    |\n|-----|---------------------|-------|------------|\n| 1   | 2025-01-01 10:00:00 | ERROR | Test error |\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 1\n- **By Level:**\n  - ERROR: 1\n- **By Module:**\n  - auth: 1\n...Message    |\n|-----|---------------------|-------|------------|\n| 1   | 2025-01-01 10:00:00 | ERROR | Test error |\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 1\n- **By Level:**\n  - ERROR: 1\n- **By Mo...1-01 10:00:00 | ERROR | Test error |\n', stats={'total_errors': 1, 'by_level': {'ERROR': 1}, 'by_module': {'auth': 1}}).markdown

test_report_renderer.py:128: AssertionError
_________ TestRenderReport.test_non_dict_data_defaults_to_empty_dict __________

self = <test_report_renderer.TestRenderReport object at 0x00000206EE0DDE20>

    def test_non_dict_data_defaults_to_empty_dict(self):
        data = "not a dict"
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Test error')
        ]
        result = render_report(data, errors)
    
        assert isinstance(result, RenderResult)
        # Stats should be calculated from the errors since data is invalid
>       assert 'Total Errors: 1' in result.markdown
E       AssertionError: assert 'Total Errors: 1' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 1\n- **By Level:**\n  - ERROR: 1\n\n## Error Timeline\n\n| Seq | ...Message    |\n|-----|---------------------|-------|------------|\n| 1   | 2025-01-01 10:00:00 | ERROR | Test error |\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 1\n- **By Level:**\n  - ERROR: 1\n\n## Error Timeline\n\n| Seq | ...Message    |\n|-----|---------------------|-------|------------|\n| 1   | 2025-01-01 10:00:00 | ERROR | Test error |\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 1\n- **By Level:**\n  - ERROR: 1\n\n## Erro... | 2025-01-01 10:00:00 | ERROR | Test error |\n', stats={'total_errors': 1, 'by_level': {'ERROR': 1}, 'by_module': {}}).markdown

test_report_renderer.py:139: AssertionError
________ TestRenderReport.test_non_list_errors_defaults_to_empty_list _________

self = <test_report_renderer.TestRenderReport object at 0x00000206EE0DE0C0>

    def test_non_list_errors_defaults_to_empty_list(self):
        data = {
            'total_errors': 999,  # This should be overridden by actual error count if errors were valid
            'by_level': {},
            'by_module': {}
        }
        errors = "not a list"
        result = render_report(data, errors)
    
        assert isinstance(result, RenderResult)
        assert 'No errors recorded.' in result.markdown
>       assert result.stats['total_errors'] == 0
E       assert 999 == 0

test_report_renderer.py:152: AssertionError
_ TestRenderReport.test_total_errors_from_data_takes_precedence_over_actual_count _

self = <test_report_renderer.TestRenderReport object at 0x00000206EE0DD160>

    def test_total_errors_from_data_takes_precedence_over_actual_count(self):
        data = {
            'total_errors': 99,  # Intentionally different from actual count
            'by_level': {},
            'by_module': {}
        }
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Error 1'),
            ParsedLine(seq_no=2, timestamp='2025-01-01 10:05:00', level='WARNING', message='Warning 1')
        ]
        result = render_report(data, errors)
    
        assert isinstance(result, RenderResult)
>       assert 'Total Errors: 99' in result.markdown
E       AssertionError: assert 'Total Errors: 99' in '# Error Report\n\n## Summary\n\n- **Total Errors:** 99\n- **By Level:**\n  - ERROR: 1\n  - WARNING: 1\n\n## Error Tim...---------|\n| 1   | 2025-01-01 10:00:00 | ERROR   | Error 1   |\n| 2   | 2025-01-01 10:05:00 | WARNING | Warning 1 |\n'
E        +  where '# Error Report\n\n## Summary\n\n- **Total Errors:** 99\n- **By Level:**\n  - ERROR: 1\n  - WARNING: 1\n\n## Error Tim...---------|\n| 1   | 2025-01-01 10:00:00 | ERROR   | Error 1   |\n| 2   | 2025-01-01 10:05:00 | WARNING | Warning 1 |\n' = RenderResult(markdown='# Error Report\n\n## Summary\n\n- **Total Errors:** 99\n- **By Level:**\n  - ERROR: 1\n  - WARN...:05:00 | WARNING | Warning 1 |\n', stats={'total_errors': 99, 'by_level': {'ERROR': 1, 'WARNING': 1}, 'by_module': {}}).markdown

test_report_renderer.py:258: AssertionError
=========================== short test summary info ===========================
FAILED test_report_renderer.py::TestRenderReport::test_basic_functionality_with_parsedline_objects
FAILED test_report_renderer.py::TestRenderReport::test_basic_functionality_with_dict_objects
FAILED test_report_renderer.py::TestRenderReport::test_missing_config_uses_defaults
FAILED test_report_renderer.py::TestRenderReport::test_include_stats_true_shows_summary
FAILED test_report_renderer.py::TestRenderReport::test_non_dict_data_defaults_to_empty_dict
FAILED test_report_renderer.py::TestRenderReport::test_non_list_errors_defaults_to_empty_list
FAILED test_report_renderer.py::TestRenderReport::test_total_errors_from_data_takes_precedence_over_actual_count
7 failed, 11 passed in 0.19s
 timeout=30s
时间: 2026-09-06 10:21:13


- [2026-09-06 10:22:04] ### 第 4 次修复
失败报告: exit_code=1 stderr= stdout=........F.........                                                       [100%]
================================== FAILURES ===================================
________ TestRenderReport.test_non_list_errors_defaults_to_empty_list _________

self = <test_report_renderer.TestRenderReport object at 0x000001B29573E0F0>

    def test_non_list_errors_defaults_to_empty_list(self):
        data = {
            'total_errors': 999,  # This should be overridden by actual error count if errors were valid
            'by_level': {},
            'by_module': {}
        }
        errors = "not a list"
        result = render_report(data, errors)
    
        assert isinstance(result, RenderResult)
        assert 'No errors recorded.' in result.markdown
>       assert result.stats['total_errors'] == 0
E       assert 999 == 0

test_report_renderer.py:152: AssertionError
=========================== short test summary info ===========================
FAILED test_report_renderer.py::TestRenderReport::test_non_list_errors_defaults_to_empty_list
1 failed, 17 passed in 0.16s
 timeout=30s
时间: 2026-09-06 10:22:04


