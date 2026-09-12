import sys
from collections import namedtuple, defaultdict
from _shared.parsed_line import ParsedLine

# 顶层导出 RenderResult，符合接口契约
RenderResult = namedtuple("RenderResult", ["markdown", "stats"])

def _ascii_safe(text, ascii_only=True):
    """将文本转换为纯ASCII，替换非ASCII字符为'?'"""
    if not isinstance(text, str):
        text = str(text)
    if ascii_only:
        return text.encode('ascii', 'replace').decode('ascii')
    return text

def _column_widths(headers, rows):
    """计算每列最大显示宽度"""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            width = len(cell)
            if i < len(widths) and width > widths[i]:
                widths[i] = width
    return widths

def _pad_cell(cell, width):
    """右填充单元格，留一个空格"""
    return cell + ' ' * (width - len(cell) + 1)

def _build_markdown_table(headers, rows):
    """生成对齐的Markdown表格"""
    widths = _column_widths(headers, rows)
    # 标题行
    header_line = '| ' + '| '.join(_pad_cell(h, widths[i]) for i, h in enumerate(headers)) + '|'
    # 分隔行
    sep_line = '|' + '|'.join('-' * (widths[i] + 2) for i in range(len(headers))) + '|'
    # 数据行
    data_lines = []
    for row in rows:
        line = '| ' + '| '.join(_pad_cell(cell, widths[i]) if i < len(widths) else cell for i, cell in enumerate(row)) + '|'
        data_lines.append(line)
    return '\n'.join([header_line, sep_line] + data_lines)

def render_report(data, errors, config=None):
    """
    根据聚合数据和错误列表生成Markdown报告。
    
    Args:
        data: 聚合统计字典，包含 total_errors, by_level, by_module 等键
        errors: 错误时间线列表，元素为 ParsedLine 或字典
        config: 配置字典，可包含:
            - ascii_only: 是否强制ASCII兼容（默认True）
            - include_stats: 是否包含统计摘要（默认True）
            - max_message_length: 消息截断长度（暂未实现）
    
    Returns:
        RenderResult: 包含 markdown 报告文本和统计字典
    """
    if config is None:
        config = {}
    ascii_only = config.get('ascii_only', True)
    
    # 标准化输入
    if not isinstance(data, dict):
        data = {}
    
    # 记录原始 errors 是否为有效列表，以便后续正确处理 total_errors
    if not isinstance(errors, list):
        errors = []
        invalid_errors = True
    else:
        invalid_errors = False
    
    # 标准化错误列表，转换为字典列表
    normalized_errors = []
    for err in errors:
        if isinstance(err, ParsedLine):
            normalized_errors.append({
                'seq_no': str(err.seq_no) if err.seq_no is not None else '',
                'timestamp': err.timestamp if err.timestamp else '',
                'level': err.level if err.level else '',
                'message': err.message if err.message else ''
            })
        elif isinstance(err, dict):
            normalized_errors.append({
                'seq_no': str(err.get('seq_no', '')),
                'timestamp': err.get('timestamp', ''),
                'level': err.get('level', ''),
                'message': err.get('message', '')
            })
        # 忽略其他格式
    
    # 应用ASCII转换
    if ascii_only:
        for item in normalized_errors:
            for key in item:
                item[key] = _ascii_safe(item[key], ascii_only)
    
    # 构建统计摘要
    stats = {}
    
    # 根据错误输入有效性决定 total_errors
    if invalid_errors:
        total_errors = 0
    else:
        total_errors = data.get('total_errors', len(normalized_errors))
    stats['total_errors'] = total_errors
    
    by_level = data.get('by_level', {})
    if not by_level:
        # 从错误列表计算
        level_counts = defaultdict(int)
        for item in normalized_errors:
            level_counts[item['level']] += 1
        by_level = dict(level_counts)
    stats['by_level'] = by_level
    
    by_module = data.get('by_module', {})
    stats['by_module'] = by_module
    
    # 生成Markdown报告
    report_lines = []
    report_lines.append("# Error Report")
    report_lines.append("")
    
    # 统计部分
    if config.get('include_stats', True):
        report_lines.append("## Summary")
        report_lines.append("")
        report_lines.append(f"- Total Errors: {total_errors}")
        if by_level:
            report_lines.append("- **By Level:**")
            for level, count in sorted(by_level.items()):
                report_lines.append(f"  - {_ascii_safe(level, ascii_only)}: {count}")
        if by_module:
            report_lines.append("- **By Module:**")
            for mod, count in sorted(by_module.items()):
                report_lines.append(f"  - {_ascii_safe(mod, ascii_only)}: {count}")
        report_lines.append("")
    
    # 错误时间线表格
    if normalized_errors:
        report_lines.append("## Error Timeline")
        report_lines.append("")
        headers = ["Seq", "Timestamp", "Level", "Message"]
        rows = []
        for item in normalized_errors:
            rows.append([item['seq_no'], item['timestamp'], item['level'], item['message']])
        table = _build_markdown_table(headers, rows)
        report_lines.append(table)
        report_lines.append("")
    else:
        report_lines.append("## Error Timeline")
        report_lines.append("")
        report_lines.append("*No errors recorded.*")
        report_lines.append("")
    
    markdown = '\n'.join(report_lines)
    return RenderResult(markdown=markdown, stats=stats)

# 演示入口
if __name__ == "__main__":
    # 示例数据
    sample_data = {
        'total_errors': 5,
        'by_level': {'ERROR': 3, 'WARNING': 2},
        'by_module': {'auth': 2, 'network': 3}
    }
    # 模拟错误列表
    from _shared.parsed_line import ParsedLine
    sample_errors = [
        ParsedLine(timestamp='2025-01-01 10:00:00', level='ERROR', message='Connection timeout', seq_no=1),
        ParsedLine(timestamp='2025-01-01 10:05:00', level='WARNING', message='Disk space low', seq_no=2),
        ParsedLine(timestamp='2025-01-01 10:10:00', level='ERROR', message='Invalid user input', seq_no=3),
        ParsedLine(timestamp='2025-01-01 10:15:00', level='ERROR', message='Null pointer', seq_no=4),
        ParsedLine(timestamp='2025-01-01 10:20:00', level='WARNING', message='Memory usage high', seq_no=5),
    ]
    config = {'ascii_only': True}
    result = render_report(sample_data, sample_errors, config)
    print("=== Markdown Report ===")
    print(result.markdown)
    print("\n=== Stats ===")
    print(result.stats)
