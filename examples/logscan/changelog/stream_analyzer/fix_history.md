- [2026-09-06 10:16:57] ### 第 1 次修复
失败报告: exit_code=1 stderr= stdout=.....F......                                                             [100%]
================================== FAILURES ===================================
_ TestStreamAnalyzer.test_flush_errors_returns_sorted_by_timestamp_and_seq_no _

self = <test_stream_analyzer.TestStreamAnalyzer object at 0x00000108638F8950>

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
>       assert actual_seq_nos == expected_order
E       assert [6, 7, 3, 4] == [3, 4, 6, 7]
E         
E         At index 0 diff: 6 != 3
E         Use -v to get more diff

test_stream_analyzer.py:129: AssertionError
============================== warnings summary ===============================
test_stream_analyzer.py:14
  C:\Users\admin\AppData\Local\Temp\token_burner_exec_fx709leq\test_stream_analyzer.py:14: PytestCollectionWarning: cannot collect test class 'TestParsedLine' because it has a __init__ constructor (from: test_stream_analyzer.py)
    class TestParsedLine:

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED test_stream_analyzer.py::TestStreamAnalyzer::test_flush_errors_returns_sorted_by_timestamp_and_seq_no
1 failed, 11 passed, 1 warning in 0.15s
 timeout=30s
时间: 2026-09-06 10:16:57


