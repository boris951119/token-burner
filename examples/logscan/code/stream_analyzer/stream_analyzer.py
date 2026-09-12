import threading
from typing import Dict, List
from _shared.parsed_line import ParsedLine


class _StreamAccumulator:
    """线程安全的流累加器，聚合文件级统计与错误日志。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.stats: Dict[str, int] = {"INFO": 0, "WARN": 0, "ERROR": 0}
        self.errors: List[dict] = []

    def push(self, line: ParsedLine) -> bool:
        with self.lock:
            level = line.level
            if level in self.stats:
                self.stats[level] += 1
            if level == "ERROR":
                self.errors.append(
                    {
                        "timestamp": line.timestamp,
                        "level": line.level,
                        "message": line.message,
                        "seq_no": line.seq_no,
                    }
                )
            return True

    def get_stats(self) -> Dict[str, int]:
        with self.lock:
            return self.stats.copy()

    def flush_errors(self) -> List[dict]:
        with self.lock:
            sorted_errors = sorted(
                self.errors, key=lambda e: e["seq_no"]
            )
            self.errors = []
            return sorted_errors

    def reset(self) -> None:
        with self.lock:
            self.stats = {"INFO": 0, "WARN": 0, "ERROR": 0}
            self.errors = []


StreamAccumulator = _StreamAccumulator


def create_accumulator() -> StreamAccumulator:
    """创建一个新的累加器实例。"""
    return _StreamAccumulator()


def push_parsed_line(accum: StreamAccumulator, line: ParsedLine) -> bool:
    """向累加器推送一条解析后的日志行。"""
    return accum.push(line)


def get_file_stats(accum: StreamAccumulator) -> Dict[str, int]:
    """返回当前累积的文件级统计快照。"""
    return accum.get_stats()


def flush_errors(accum: StreamAccumulator) -> List[dict]:
    """提取并清空错误日志，返回按全局序列号排序的错误时间线。"""
    return accum.flush_errors()


def reset_state(accum: StreamAccumulator) -> None:
    """重置累加器状态（清空统计与错误列表）。"""
    accum.reset()


if __name__ == "__main__":
    import datetime
    import threading

    # 演示多线程推送
    acc = create_accumulator()

    # 准备一组模拟数据（包含乱序时间戳以验证排序）
    lines = [
        ParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 0),
            level="INFO",
            message="Start",
            seq_no=1,
        ),
        ParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 1),
            level="WARN",
            message="Low memory",
            seq_no=2,
        ),
        ParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 2),
            level="ERROR",
            message="Crash",
            seq_no=3,
        ),
        ParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 3),
            level="INFO",
            message="Retry",
            seq_no=4,
        ),
        ParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 4),
            level="ERROR",
            message="Fail again",
            seq_no=5,
        ),
        ParsedLine(
            timestamp=datetime.datetime(2025, 1, 1, 10, 0, 1),
            level="ERROR",
            message="Prior error",
            seq_no=0,
        ),
    ]

    def worker(subset):
        for line in subset:
            push_parsed_line(acc, line)

    chunk_size = 2
    threads = []
    for i in range(0, len(lines), chunk_size):
        t = threading.Thread(target=worker, args=(lines[i : i + chunk_size],))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    print("File stats:", get_file_stats(acc))
    print("Error timeline:")
    for e in flush_errors(acc):
        print(f"  {e['timestamp']} | seq={e['seq_no']} | {e['message']}")

    reset_state(acc)
    print("After reset, stats:", get_file_stats(acc), "errors:", flush_errors(acc))
