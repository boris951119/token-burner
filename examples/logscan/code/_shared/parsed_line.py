from collections import namedtuple

ParsedLine = namedtuple("ParsedLine", ["timestamp", "level", "message", "seq_no"])
