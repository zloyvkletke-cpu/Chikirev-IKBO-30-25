"""Базовые проверки эмулятора."""

import unittest

from src.main import main, norm, parse, vfs_hash


class TestParser(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(parse("ls /tmp"), ("ls", ["/tmp"]))

    def test_quotes(self):
        self.assertEqual(parse('echo "a b"'), ("echo", ["a b"]))

    def test_comment(self):
        self.assertEqual(parse("ls # comment"), ("ls", []))

    def test_empty(self):
        self.assertEqual(parse("   "), ("", []))


class TestPaths(unittest.TestCase):
    def test_up(self):
        self.assertEqual(norm("/sub", ".."), "/")

    def test_down(self):
        self.assertEqual(norm("/", "sub"), "/sub")

    def test_absolute(self):
        self.assertEqual(norm("/sub", "/"), "/")


class TestVfsHash(unittest.TestCase):
    def test_stable(self):
        tree = {"/": {"is_dir": True, "content": b"", "owner": "user"}}
        self.assertEqual(vfs_hash(tree), vfs_hash(tree))

    def test_changes_with_owner(self):
        tree = {"/": {"is_dir": True, "content": b"", "owner": "user"}}
        before = vfs_hash(tree)
        tree["/"]["owner"] = "alice"
        self.assertNotEqual(before, vfs_hash(tree))


if __name__ == "__main__":
    unittest.main()