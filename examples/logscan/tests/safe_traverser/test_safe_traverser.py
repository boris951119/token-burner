import os
import tempfile
from pathlib import Path
import pytest
import gzip
import bz2
from safe_traverser import safe_traverse, read_file_content


def test_safe_traverse_empty_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = safe_traverse(tmpdir)
        assert result == {}


def test_safe_traverse_nonexistent_directory():
    result = safe_traverse("/nonexistent/directory/path")
    assert result == {}


def test_safe_traverse_regular_files_only():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        # Create some files
        file1 = tmpdir_path / "file1.txt"
        file2 = tmpdir_path / "file2.py"
        file1.write_text("content1")
        file2.write_text("content2")
        
        result = safe_traverse(tmpdir)
        
        # Should contain both files
        paths = [p.name for p in result.values()]
        assert len(result) == 2
        assert "file1.txt" in paths
        assert "file2.py" in paths


def test_safe_traverse_with_extensions_filter():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        # Create files with different extensions
        file1 = tmpdir_path / "file1.txt"
        file2 = tmpdir_path / "file2.py"
        file3 = tmpdir_path / "file3.js"
        file1.write_text("content1")
        file2.write_text("content2")
        file3.write_text("content3")
        
        result = safe_traverse(tmpdir, extensions=["txt", ".py"])
        
        paths = [p.name for p in result.values()]
        assert len(result) == 2
        assert "file1.txt" in paths
        assert "file2.py" in paths
        assert "file3.js" not in paths


def test_safe_traverse_case_insensitive_extensions():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        # Create files with uppercase extensions
        file1 = tmpdir_path / "file1.TXT"
        file2 = tmpdir_path / "file2.PY"
        file1.write_text("content1")
        file2.write_text("content2")
        
        result = safe_traverse(tmpdir, extensions=["txt", ".py"])
        
        paths = [p.name for p in result.values()]
        assert len(result) == 2
        assert "file1.TXT" in paths
        assert "file2.PY" in paths


def test_safe_traverse_max_depth():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        # Create nested structure
        subdir1 = tmpdir_path / "subdir1"
        subdir1.mkdir()
        subdir2 = subdir1 / "subdir2"
        subdir2.mkdir()
        
        file_root = tmpdir_path / "file_root.txt"
        file_sub1 = subdir1 / "file_sub1.txt"
        file_sub2 = subdir2 / "file_sub2.txt"
        file_root.write_text("root")
        file_sub1.write_text("sub1")
        file_sub2.write_text("sub2")
        
        # Max depth 0 should only include root dir itself (no files)
        result_0 = safe_traverse(tmpdir, max_depth=0)
        assert len(result_0) == 0
        
        # Max depth 1 should include root and first level
        result_1 = safe_traverse(tmpdir, max_depth=1)
        paths_1 = [p.name for p in result_1.values()]
        assert len(result_1) == 1  # Only file_root.txt
        assert "file_root.txt" in paths_1
        assert "file_sub1.txt" not in paths_1
        
        # Max depth 2 should include up to second level
        result_2 = safe_traverse(tmpdir, max_depth=2)
        paths_2 = [p.name for p in result_2.values()]
        assert len(result_2) == 2  # file_root.txt and file_sub1.txt
        assert "file_root.txt" in paths_2
        assert "file_sub1.txt" in paths_2
        assert "file_sub2.txt" not in paths_2


def test_safe_traverse_unlimited_depth():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        # Create nested structure
        subdir1 = tmpdir_path / "subdir1"
        subdir1.mkdir()
        file_sub1 = subdir1 / "file_sub1.txt"
        file_sub1.write_text("sub1")
        
        # With max_depth=None (unlimited), should find all files
        result = safe_traverse(tmpdir, max_depth=None)
        paths = [p.name for p in result.values()]
        assert len(result) == 1
        assert "file_sub1.txt" in paths


def test_safe_traverse_with_string_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a file
        file_path = Path(tmpdir) / "test.txt"
        file_path.write_text("test content")
        
        # Pass string instead of Path object
        result = safe_traverse(str(tmpdir))
        paths = [p.name for p in result.values()]
        assert len(result) == 1
        assert "test.txt" in paths


def test_read_file_content_regular_file():
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(b"hello world")
        tmp.flush()
        
        content = read_file_content(tmp.name)
        assert content == b"hello world"


def test_read_file_content_gz_compressed():
    with tempfile.NamedTemporaryFile(suffix=".gz", delete=False) as tmp:
        with gzip.open(tmp.name, 'wb') as gz_file:
            gz_file.write(b"compressed content")
        
        content = read_file_content(tmp.name)
        assert content == b"compressed content"


def test_read_file_content_bz2_compressed():
    with tempfile.NamedTemporaryFile(suffix=".bz2", delete=False) as tmp:
        with bz2.open(tmp.name, 'wb') as bz2_file:
            bz2_file.write(b"bzip2 compressed content")
        
        content = read_file_content(tmp.name)
        assert content == b"bzip2 compressed content"


def test_read_file_content_case_insensitive_suffix():
    # Test .GZ and .BZ2 with uppercase
    with tempfile.NamedTemporaryFile(suffix=".GZ", delete=False) as tmp:
        with gzip.open(tmp.name, 'wb') as gz_file:
            gz_file.write(b"uppercase gz content")
        
        content = read_file_content(tmp.name)
        assert content == b"uppercase gz content"
    
    with tempfile.NamedTemporaryFile(suffix=".BZ2", delete=False) as tmp:
        with bz2.open(tmp.name, 'wb') as bz2_file:
            bz2_file.write(b"uppercase bz2 content")
        
        content = read_file_content(tmp.name)
        assert content == b"uppercase bz2 content"


def test_read_file_content_nonexistent_file():
    with pytest.raises(OSError):
        read_file_content("/nonexistent/file")


def test_safe_traverse_nested_directories():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        # Create nested directories with files
        d1 = tmpdir_path / "d1"
        d2 = d1 / "d2"
        d1.mkdir()
        d2.mkdir()
        
        f1 = tmpdir_path / "f1.txt"
        f2 = d1 / "f2.txt"
        f3 = d2 / "f3.txt"
        f4 = d2 / "f4.log"
        
        f1.write_text("content1")
        f2.write_text("content2")
        f3.write_text("content3")
        f4.write_text("content4")
        
        result = safe_traverse(tmpdir, extensions=["txt"])
        paths = [p.name for p in result.values()]
        assert len(result) == 3  # f1, f2, f3
        assert "f1.txt" in paths
        assert "f2.txt" in paths
        assert "f3.txt" in paths
        assert "f4.log" not in paths


def test_safe_traverse_with_dot_extension_format():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        file1 = tmpdir_path / "file1.txt"
        file2 = tmpdir_path / "file2.py"
        file3 = tmpdir_path / "file3.js"
        file1.write_text("content1")
        file2.write_text("content2")
        file3.write_text("content3")
        
        # Use extension format with dots
        result = safe_traverse(tmpdir, extensions=[".txt", ".py"])
        
        paths = [p.name for p in result.values()]
        assert len(result) == 2
        assert "file1.txt" in paths
        assert "file2.py" in paths
        assert "file3.js" not in paths
