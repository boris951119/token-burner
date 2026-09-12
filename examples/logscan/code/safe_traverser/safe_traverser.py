import os
import gzip
import bz2
from pathlib import Path


def safe_traverse(
    directory_path: Path | str,
    extensions: list[str] | None = None,
    max_depth: int | None = None,
) -> dict[int, Path]:
    """
    Recursively traverse a directory tree, collecting regular files.

    - Uses inode deduplication to prevent infinite loops from symlinks/hardlinks.
    - Respects `max_depth` (None = unlimited).
    - Filters by file extensions (case‑insensitive) if `extensions` is provided.
    - Returns a mapping ``{inode: path}`` for the first encountered path of each file.
    """
    root = Path(directory_path).resolve()
    if not root.is_dir():
        return {}

    # Normalize extensions to lowercase with a leading dot
    if extensions is not None:
        exts = {ext.lower() if ext.startswith('.') else '.' + ext.lower() for ext in extensions}
    else:
        exts = None

    result: dict[int, Path] = {}
    visited_inodes: set[int] = set()

    # Start with the root directory itself to avoid cycles involving the root
    try:
        root_stat = root.stat()
        visited_inodes.add(root_stat.st_ino)
    except OSError:
        return {}

    # Stack for iterative depth‑first traversal: (directory, current_depth)
    stack: list[tuple[Path, int]] = [(root, 0)]

    while stack:
        current_dir, depth = stack.pop()
        try:
            entries = list(current_dir.iterdir())
        except (PermissionError, OSError):
            continue

        for entry in entries:
            # Stat the entry (follows symlinks) to obtain inode
            try:
                stat = entry.stat()
            except OSError:
                continue
            inode = stat.st_ino

            # Skip already visited inode (prevents loops)
            if inode in visited_inodes:
                continue
            visited_inodes.add(inode)

            # Determine entry type (symlink resolution is already done by stat)
            if entry.is_dir():
                # Recurse into subdirectory only if depth allows (depth+1 <= max_depth)
                if max_depth is None or depth < max_depth:
                    stack.append((entry, depth + 1))
            else:
                # Regular file (or symlink to a file):
                # collect only if depth allows (depth+1 <= max_depth)
                if max_depth is None or depth < max_depth:
                    if exts is None or entry.suffix.lower() in exts:
                        result[inode] = entry

    return result


def read_file_content(file_path: Path | str) -> bytes:
    """
    Read file contents, transparently decompressing when the path ends with
    ``.gz`` or ``.bz2`` (case‑insensitive).
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == '.gz':
        with gzip.open(path, 'rb') as f:
            return f.read()
    elif suffix == '.bz2':
        with bz2.open(path, 'rb') as f:
            return f.read()
    else:
        return path.read_bytes()


if __name__ == '__main__':
    print("Safe Traverser Demo")
    cwd = Path.cwd()
    print(f"Traversing {cwd} with max_depth=1 …")
    traversed = safe_traverse(cwd, max_depth=1)
    print(f"Found {len(traversed)} files.")
    for ino, p in list(traversed.items())[:5]:
        print(f"  inode {ino}: {p}")

    # Try reading this script itself
    self = Path(__file__).resolve()
    if self.exists():
        content = read_file_content(self)
        print(f"\nFirst 50 bytes of this script: {content[:50]}")
    else:
        print("Self file not found (unexpected).")