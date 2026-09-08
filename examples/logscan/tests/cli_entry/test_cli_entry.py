import pytest
import tempfile
import os
import sys
from unittest.mock import patch, MagicMock
from io import StringIO
from cli_entry import parse_args, main


class TestParseArgs:
    def test_empty_args(self):
        result = parse_args([])
        expected = {
            'input': None,
            'output': None,
            'verbose': False,
            'version': False
        }
        assert result == expected

    def test_input_short_flag(self):
        result = parse_args(['-i', 'input.txt'])
        expected = {
            'input': 'input.txt',
            'output': None,
            'verbose': False,
            'version': False
        }
        assert result == expected

    def test_input_long_flag(self):
        result = parse_args(['--input', 'input.txt'])
        expected = {
            'input': 'input.txt',
            'output': None,
            'verbose': False,
            'version': False
        }
        assert result == expected

    def test_output_short_flag(self):
        result = parse_args(['-o', 'output_dir'])
        expected = {
            'input': None,
            'output': 'output_dir',
            'verbose': False,
            'version': False
        }
        assert result == expected

    def test_output_long_flag(self):
        result = parse_args(['--output', 'output_dir'])
        expected = {
            'input': None,
            'output': 'output_dir',
            'verbose': False,
            'version': False
        }
        assert result == expected

    def test_verbose_short_flag(self):
        result = parse_args(['-v'])
        expected = {
            'input': None,
            'output': None,
            'verbose': True,
            'version': False
        }
        assert result == expected

    def test_verbose_long_flag(self):
        result = parse_args(['--verbose'])
        expected = {
            'input': None,
            'output': None,
            'verbose': True,
            'version': False
        }
        assert result == expected

    def test_version_flag(self):
        result = parse_args(['--version'])
        expected = {
            'input': None,
            'output': None,
            'verbose': False,
            'version': True
        }
        assert result == expected

    def test_all_flags_combined(self):
        result = parse_args(['-i', 'input.txt', '-o', 'output/', '-v', '--version'])
        expected = {
            'input': 'input.txt',
            'output': 'output/',
            'verbose': True,
            'version': True
        }
        assert result == expected

    def test_mixed_args(self):
        result = parse_args(['--input', 'test.txt', '-v', '--output', 'results'])
        expected = {
            'input': 'test.txt',
            'output': 'results',
            'verbose': True,
            'version': False
        }
        assert result == expected


class TestMain:
    def test_main_with_version_flag(self, capsys):
        with patch('sys.argv', ['cli_entry.py', '--version']):
            result = main(['--version'])
            captured = capsys.readouterr()
            assert result == 0
            assert "cli_entry v1.0" in captured.out

    def test_main_with_no_args(self, capsys):
        result = main([])
        captured = capsys.readouterr()
        assert result == 0
        assert "任务完成。" in captured.out

    def test_main_with_verbose_flag(self, capsys):
        result = main(['-v'])
        captured = capsys.readouterr()
        assert result == 0
        assert "正在执行任务..." in captured.out
        assert "任务完成。" in captured.out

    def test_main_with_output_dir_exists_and_writable(self, tmp_path, capsys):
        output_dir = str(tmp_path)
        result = main(['--output', output_dir])
        captured = capsys.readouterr()
        assert result == 0
        assert "任务完成。" in captured.out

    def test_main_creates_output_dir_if_not_exists(self, tmp_path, capsys):
        new_dir = tmp_path / "new_dir"
        result = main(['--output', str(new_dir)])
        captured = capsys.readouterr()
        assert result == 0
        assert new_dir.exists()
        assert new_dir.is_dir()
        assert "任务完成。" in captured.out

    def test_main_with_input_flag_only(self, capsys):
        result = main(['--input', 'test.txt'])
        captured = capsys.readouterr()
        assert result == 0
        assert "任务完成。" in captured.out

    def test_main_with_input_and_verbose(self, capsys):
        result = main(['--input', 'test.txt', '-v'])
        captured = capsys.readouterr()
        assert result == 0
        assert "正在执行任务..." in captured.out
        assert "任务完成。" in captured.out

    def test_main_with_all_flags(self, tmp_path, capsys):
        result = main(['--input', 'test.txt', '--output', str(tmp_path), '-v', '--version'])
        captured = capsys.readouterr()
        # If --version is present, it should take precedence and return version info only
        assert result == 0
        assert "cli_entry v1.0" in captured.out
        # The other outputs should not appear when version flag is set
        assert "正在执行任务..." not in captured.out
        assert "任务完成。" not in captured.out

    @patch('os.access', return_value=False)
    def test_main_output_dir_not_writable(self, mock_access, tmp_path, capsys):
        # Simulate a case where directory exists but is not writable
        # Note: This is a simplified test since we can't actually make a dir unwritable on all platforms easily
        # We're mocking os.access to return False
        result = main(['--output', str(tmp_path)])
        captured = capsys.readouterr()
        assert result == 1
        assert f"错误：输出目录 '{str(tmp_path)}' 不可写" in captured.err

    def test_main_exception_handling(self, capsys):
        # Test exception handling by mocking something that raises an exception
        with patch('cli_entry.parse_args', side_effect=Exception("Test error")):
            result = main(['--input', 'test.txt'])
            captured = capsys.readouterr()
            assert result == 1
            assert "致命错误：Test error" in captured.err

    def test_main_none_argv_uses_sys_argv(self, capsys):
        with patch('sys.argv', ['cli_entry.py', '--version']):
            result = main(None)
            captured = capsys.readouterr()
            assert result == 0
            assert "cli_entry v1.0" in captured.out
