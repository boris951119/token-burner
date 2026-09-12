import pytest
from unittest.mock import Mock
from report_renderer import render_report, RenderResult
from _shared.parsed_line import ParsedLine


class TestRenderReport:

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
        assert 'Total Errors: 2' in result.markdown
        assert 'ERROR: 1' in result.markdown
        assert 'WARNING: 1' in result.markdown
        assert 'Connection failed' in result.markdown
        assert result.stats['total_errors'] == 2
        assert result.stats['by_level']['ERROR'] == 1
        assert result.stats['by_level']['WARNING'] == 1

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
        assert 'Total Errors: 2' in result.markdown
        assert 'ERROR: 1' in result.markdown
        assert 'WARNING: 1' in result.markdown
        assert 'Connection failed' in result.markdown
        assert result.stats['total_errors'] == 2
        assert result.stats['by_level']['ERROR'] == 1
        assert result.stats['by_level']['WARNING'] == 1

    def test_empty_errors_list(self):
        data = {
            'total_errors': 0,
            'by_level': {},
            'by_module': {}
        }
        errors = []
        result = render_report(data, errors)
        
        assert isinstance(result, RenderResult)
        assert 'No errors recorded.' in result.markdown
        assert result.stats['total_errors'] == 0
        assert result.stats['by_level'] == {}

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
        assert 'Total Errors: 1' in result.markdown
        assert result.stats['total_errors'] == 1

    def test_ascii_only_false_in_config(self):
        data = {
            'total_errors': 1,
            'by_level': {'ERROR': 1},
            'by_module': {}
        }
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Test error with ümlaut')
        ]
        config = {'ascii_only': False}
        result = render_report(data, errors, config)
        
        assert isinstance(result, RenderResult)
        assert 'ümlaut' in result.markdown

    def test_include_stats_false_hides_summary(self):
        data = {
            'total_errors': 1,
            'by_level': {'ERROR': 1},
            'by_module': {'auth': 1}
        }
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Test error')
        ]
        config = {'include_stats': False}
        result = render_report(data, errors, config)
        
        assert isinstance(result, RenderResult)
        assert 'Summary' not in result.markdown
        assert 'Total Errors:' not in result.markdown

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
        assert 'Total Errors: 1' in result.markdown

    def test_non_dict_data_defaults_to_empty_dict(self):
        data = "not a dict"
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Test error')
        ]
        result = render_report(data, errors)
        
        assert isinstance(result, RenderResult)
        # Stats should be calculated from the errors since data is invalid
        assert 'Total Errors: 1' in result.markdown

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
        assert result.stats['total_errors'] == 0

    def test_mixed_error_types_in_list(self):
        data = {
            'total_errors': 6,  # Should match combined count of both types
            'by_level': {'ERROR': 3, 'WARNING': 3},
            'by_module': {}
        }
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='PL error 1'),
            {'seq_no': 2, 'timestamp': '2025-01-01 10:05:00', 'level': 'WARNING', 'message': 'Dict warning 1'},
            ParsedLine(seq_no=3, timestamp='2025-01-01 10:10:00', level='ERROR', message='PL error 2'),
            {'seq_no': 4, 'timestamp': '2025-01-01 10:15:00', 'level': 'ERROR', 'message': 'Dict error 1'},
            ParsedLine(seq_no=5, timestamp='2025-01-01 10:20:00', level='WARNING', message='PL warning 1'),
            {'seq_no': 6, 'timestamp': '2025-01-01 10:25:00', 'level': 'WARNING', 'message': 'Dict warning 2'}
        ]
        result = render_report(data, errors)
        
        assert isinstance(result, RenderResult)
        assert 'PL error 1' in result.markdown
        assert 'Dict warning 1' in result.markdown
        assert 'PL error 2' in result.markdown
        assert 'Dict error 1' in result.markdown
        assert 'PL warning 1' in result.markdown
        assert 'Dict warning 2' in result.markdown
        assert result.stats['total_errors'] == 6

    def test_unicode_handling_ascii_only_true(self):
        data = {
            'total_errors': 1,
            'by_level': {'ERROR': 1},
            'by_module': {}
        }
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Error with ñoñ-ascii')
        ]
        config = {'ascii_only': True}
        result = render_report(data, errors, config)
        
        assert isinstance(result, RenderResult)
        # Non-ASCII characters should be replaced with ?
        assert '?' in result.markdown or 'no-ascii' in result.markdown.lower()

    def test_unicode_handling_ascii_only_false(self):
        data = {
            'total_errors': 1,
            'by_level': {'ERROR': 1},
            'by_module': {}
        }
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Error with ñoñ-ascii')
        ]
        config = {'ascii_only': False}
        result = render_report(data, errors, config)
        
        assert isinstance(result, RenderResult)
        # Non-ASCII characters should be preserved
        assert 'ñ' in result.markdown

    def test_calculate_by_level_from_errors_when_not_in_data(self):
        data = {
            'total_errors': 3,
            'by_level': {},  # Empty, so it will be computed from errors
            'by_module': {}
        }
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Error 1'),
            ParsedLine(seq_no=2, timestamp='2025-01-01 10:05:00', level='WARNING', message='Warning 1'),
            ParsedLine(seq_no=3, timestamp='2025-01-01 10:10:00', level='ERROR', message='Error 2')
        ]
        result = render_report(data, errors)
        
        assert isinstance(result, RenderResult)
        assert result.stats['by_level']['ERROR'] == 2
        assert result.stats['by_level']['WARNING'] == 1

    def test_preserves_by_level_from_data_when_present(self):
        data = {
            'total_errors': 5,  # Different from actual error count
            'by_level': {'FATAL': 1, 'CRITICAL': 1},  # Should be preserved
            'by_module': {}
        }
        errors = [
            ParsedLine(seq_no=1, timestamp='2025-01-01 10:00:00', level='ERROR', message='Error 1'),
            ParsedLine(seq_no=2, timestamp='2025-01-01 10:05:00', level='WARNING', message='Warning 1')
        ]
        result = render_report(data, errors)
        
        assert isinstance(result, RenderResult)
        assert result.stats['by_level']['FATAL'] == 1
        assert result.stats['by_level']['CRITICAL'] == 1
        # The error levels from the errors list are not counted because by_level was already present in data

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
        assert 'Total Errors: 99' in result.markdown
        assert result.stats['total_errors'] == 99

    def test_empty_data_and_empty_errors(self):
        data = {}
        errors = []
        result = render_report(data, errors)
        
        assert isinstance(result, RenderResult)
        assert 'Error Report' in result.markdown
        assert 'Total Errors:' in result.markdown  # Will be 0 from empty errors
        assert 'No errors recorded.' in result.markdown
        assert result.stats['total_errors'] == 0
        assert result.stats['by_level'] == {}

    def test_none_values_in_parsedline_handled_properly(self):
        data = {
            'total_errors': 1,
            'by_level': {'ERROR': 1},
            'by_module': {}
        }
        errors = [
            ParsedLine(seq_no=None, timestamp=None, level=None, message=None)
        ]
        result = render_report(data, errors)
        
        assert isinstance(result, RenderResult)
        # None values should be converted to empty strings or similar
        assert isinstance(result.stats['total_errors'], int)

    def test_dict_error_with_missing_keys_gets_default_values(self):
        data = {
            'total_errors': 1,
            'by_level': {'': 1},  # Empty string level from missing key
            'by_module': {}
        }
        errors = [
            {'seq_no': 7}  # Only seq_no provided
        ]
        result = render_report(data, errors)
        
        assert isinstance(result, RenderResult)
        assert '7' in result.markdown  # seq_no should appear
        # Other fields should default to empty strings
