import unittest

from codex_flipper_monitor.task_label import thread_label


class TaskLabelTests(unittest.TestCase):
    def test_ascii_thread_name_is_preserved_not_directory_derived(self) -> None:
        self.assertEqual(thread_label("QDig research"), "QDIG_RE")

    def test_chinese_thread_name_uses_pinyin_initials(self) -> None:
        self.assertEqual(thread_label("交易重构"), "JYZG")

    def test_missing_thread_name_is_explicit(self) -> None:
        self.assertEqual(thread_label(None), "NO_NAME")


if __name__ == "__main__":
    unittest.main()
