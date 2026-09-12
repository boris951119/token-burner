import datetime
import threading
import pytest
from unittest.mock import Mock
from stream_analyzer import (
    create_accumulator,
    push_parsed_line,
    get_file_stats,
    flush_errors,
    reset_state,
)


class TestParsedLine:
    def __init__(self, timestamp, level, message, seq_no):
        self.timestamp = timestamp
        self.level = level
        self.message = message
        self.seq_no = seq_no


class TestStreamAnalyzer:

    def test_create_accumulator_initial_state(self):
        accum = create_accumulator()
        stats = get_file_stats(accum)
        assert stats == {"INFO": 0, "WARN": 0, "ERROR": 0}
        
        errors = flush_errors(accum)
        assert errors == []

    def test_push_info_line_updates_stats(self):
        accum = create_accumulator()
        line = TestParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 0),
            level="INFO",
            message="Test info",
            seq_no=1
        )
        
        result = push_parsed_line(accum, line)
        assert result is True
        
        stats = get_file_stats(accum)
        assert stats == {"INFO": 1, "WARN": 0, "ERROR": 0}
        
        errors = flush_errors(accum)
        assert errors == []

    def test_push_warn_line_updates_stats(self):
        accum = create_accumulator()
        line = TestParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 0),
            level="WARN",
            message="Test warning",
            seq_no=2
        )
        
        result = push_parsed_line(accum, line)
        assert result is True
        
        stats = get_file_stats(accum)
        assert stats == {"INFO": 0, "WARN": 1, "ERROR": 0}

    def test_push_error_line_updates_stats_and_errors(self):
        accum = create_accumulator()
        line = TestParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 0),
            level="ERROR",
            message="Test error",
            seq_no=3
        )
        
        result = push_parsed_line(accum, line)
        assert result is True
        
        stats = get_file_stats(accum)
        assert stats == {"INFO": 0, "WARN": 0, "ERROR": 1}
        
        errors = flush_errors(accum)
        assert len(errors) == 1
        assert errors[0]["timestamp"] == datetime.datetime(2025, 1, 1, 10, 0, 0)
        assert errors[0]["level"] == "ERROR"
        assert errors[0]["message"] == "Test error"
        assert errors[0]["seq_no"] == 3

    def test_multiple_pushes_accumulate_correctly(self):
        accum = create_accumulator()
        
        lines = [
            TestParsedLine(datetime.datetime(2025, 1, 1, 10, 0, 0), "INFO", "Info 1", 1),
            TestParsedLine(datetime.datetime(2025, 1, 1, 10, 0, 1), "WARN", "Warn 1", 2),
            TestParsedLine(datetime.datetime(2025, 1, 1, 10, 0, 2), "ERROR", "Error 1", 3),
            TestParsedLine(datetime.datetime(2025, 1, 1, 10, 0, 3), "INFO", "Info 2", 4),
            TestParsedLine(datetime.datetime(2025, 1, 1, 10, 0, 4), "ERROR", "Error 2", 5),
        ]
        
        for line in lines:
            push_parsed_line(accum, line)
        
        stats = get_file_stats(accum)
        assert stats == {"INFO": 2, "WARN": 1, "ERROR": 2}
        
        errors = flush_errors(accum)
        assert len(errors) == 2
        assert errors[0]["seq_no"] == 3
        assert errors[1]["seq_no"] == 5

    def test_flush_errors_returns_sorted_by_timestamp_and_seq_no(self):
        accum = create_accumulator()
        
        # Add errors with same timestamp but different seq_no to test seq_no sorting
        lines = [
            TestParsedLine(datetime.datetime(2025, 1, 1, 10, 0, 0), "ERROR", "Error 3", 6),
            TestParsedLine(datetime.datetime(2025, 1, 1, 10, 0, 1), "ERROR", "Error 1", 4),
            TestParsedLine(datetime.datetime(2025, 1, 1, 10, 0, 0), "ERROR", "Error 2", 7),
            TestParsedLine(datetime.datetime(2025, 1, 1, 10, 0, 1), "ERROR", "Error 4", 3),
        ]
        
        for line in lines:
            push_parsed_line(accum, line)
        
        errors = flush_errors(accum)
        assert len(errors) == 4
        
        # Should be sorted by (timestamp, seq_no)
        expected_order = [3, 4, 6, 7]  # seq_nos in order after sorting by (timestamp, seq_no)
        actual_seq_nos = [error["seq_no"] for error in errors]
        assert actual_seq_nos == expected_order

    def test_reset_clears_stats_and_errors(self):
        accum = create_accumulator()
        
        # Add some data
        info_line = TestParsedLine(datetime.datetime(2025, 1, 1, 10, 0, 0), "INFO", "Info", 1)
        error_line = TestParsedLine(datetime.datetime(2025, 1, 1, 10, 0, 1), "ERROR", "Error", 2)
        
        push_parsed_line(accum, info_line)
        push_parsed_line(accum, error_line)
        
        # Verify data exists
        stats = get_file_stats(accum)
        assert stats == {"INFO": 1, "WARN": 0, "ERROR": 1}
        
        errors = flush_errors(accum)
        assert len(errors) == 1
        
        # Reset and verify cleared
        reset_state(accum)
        
        stats_after_reset = get_file_stats(accum)
        assert stats_after_reset == {"INFO": 0, "WARN": 0, "ERROR": 0}
        
        errors_after_reset = flush_errors(accum)
        assert errors_after_reset == []

    def test_unknown_level_ignored_in_stats(self):
        accum = create_accumulator()
        line = TestParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 0),
            level="UNKNOWN_LEVEL",
            message="Unknown level",
            seq_no=99
        )
        
        result = push_parsed_line(accum, line)
        assert result is True
        
        stats = get_file_stats(accum)
        assert stats == {"INFO": 0, "WARN": 0, "ERROR": 0}  # No change
        
        errors = flush_errors(accum)
        assert errors == []  # No errors added even though level is unknown

    def test_concurrent_push_operations_thread_safe(self):
        accum = create_accumulator()
        results = []
        
        def worker(start_idx):
            local_results = []
            for i in range(50):
                line = TestParsedLine(
                    timestamp=datetime.datetime(2025, 1, 1, 10, 0, start_idx + i % 3),
                    level=["INFO", "WARN", "ERROR"][i % 3],
                    message=f"Message {start_idx}-{i}",
                    seq_no=start_idx * 100 + i
                )
                res = push_parsed_line(accum, line)
                local_results.append(res)
            results.extend(local_results)
        
        threads = []
        for i in range(3):  # Create 3 concurrent workers
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # All operations should succeed
        assert all(results)
        
        # Check final state makes sense
        stats = get_file_stats(accum)
        total_count = sum(stats.values())
        assert total_count == 150  # 3 workers * 50 items each
        
        # Errors count should match ERROR level count
        errors = flush_errors(accum)
        expected_error_count = stats["ERROR"]
        assert len(errors) == expected_error_count

    def test_flush_errors_clears_internal_list(self):
        accum = create_accumulator()
        
        error_line = TestParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 0),
            level="ERROR",
            message="Error message",
            seq_no=1
        )
        
        push_parsed_line(accum, error_line)
        
        # First flush should return the error
        errors1 = flush_errors(accum)
        assert len(errors1) == 1
        
        # Second flush should return empty list
        errors2 = flush_errors(accum)
        assert len(errors2) == 0

    def test_get_stats_returns_copy_not_reference(self):
        accum = create_accumulator()
        stats_original = get_file_stats(accum)
        
        # Modify returned dict - should not affect internal state
        stats_original["INFO"] = 999
        
        # Get stats again - should be original values
        stats_new = get_file_stats(accum)
        assert stats_new == {"INFO": 0, "WARN": 0, "ERROR": 0}

    def test_multiple_flush_operations_return_different_lists(self):
        accum = create_accumulator()
        
        error1 = TestParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 0),
            level="ERROR",
            message="First error",
            seq_no=1
        )
        error2 = TestParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 1),
            level="ERROR",
            message="Second error",
            seq_no=2
        )
        
        push_parsed_line(accum, error1)
        first_flush = flush_errors(accum)
        assert len(first_flush) == 1
        
        push_parsed_line(accum, error2)
        second_flush = flush_errors(accum)
        assert len(second_flush) == 1
        
        # The two flush operations should return different lists
        assert first_flush[0]["seq_no"] == 1
        assert second_flush[0]["seq_no"] == 2
