import argparse
import sys
import os
from typing import Optional

def parse_args(args_list: list[str]) -> dict:
    """解析命令行参数，返回解析后的字典。"""
    parser = argparse.ArgumentParser(
        description="CLI 入口 - 权限预判与任务协调"
    )
    parser.add_argument(
        "--input", "-i", type=str, help="输入文件路径"
    )
    parser.add_argument(
        "--output", "-o", type=str, help="输出目录路径"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="详细输出"
    )
    parser.add_argument(
        "--version", action="store_true", help="显示版本信息"
    )
    # 此处可扩展更多参数
    args = parser.parse_args(args_list)
    return vars(args)

def main(argv: Optional[list[str]] = None) -> int:
    """主函数：解析参数、权限预判、协调模块生命周期、返回退出码。"""
    if argv is None:
        argv = sys.argv[1:]

    try:
        params = parse_args(argv)

        # 版本信息快速返回
        if params.get("version"):
            print("cli_entry v1.0")
            return 0

        # 权限预判：检查输出目录是否可写（若指定）
        output_dir = params.get("output")
        if output_dir:
            # 如果输出目录不存在，尝试创建（安全操作，不涉及删除）
            if not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            if not os.access(output_dir, os.W_OK):
                print(f"错误：输出目录 '{output_dir}' 不可写", file=sys.stderr)
                return 1

        # 协调其他模块生命周期（示例：调用核心处理模块）
        # 实际项目中替换为业务模块的调用，例如：
        # from task_processor import process_task
        # process_task(params)
        # 这里仅演示流程
        if params.get("verbose"):
            print("正在执行任务...")
        print("任务完成。")
        return 0

    except Exception as e:
        print(f"致命错误：{e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
