"""`ww_engine.util.config.Config` 的持久化契约（2026-11-22 后端审查 B12）。

旧行为（三条都实测过）：
  ① 磁盘上是 `"True"`（字符串）→ 类型不匹配 → **静默换成默认 False 并覆写文件**；
  ② 空/半截 JSON → `read_json_file` 返回 None → 整份配置重置为默认（用户设置静默归零）；
  ③ `write_json_file` 先截断再写，崩在中间就得到空文件（于是触发 ②）。

跑法（项目根目录）：
    python -m unittest tests.test_engine_config -v
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ww_engine.util.config import Config, _MISSING, _coerce  # noqa: E402


class CoerceTest(unittest.TestCase):
    def test_strings_are_coerced_not_reset(self):
        self.assertIs(_coerce("True", False), True)
        self.assertIs(_coerce("false", True), False)
        self.assertEqual(_coerce("3", 1), 3)
        self.assertEqual(_coerce("2.5", 1.0), 2.5)
        self.assertEqual(_coerce(3.0, 1), 3)

    def test_uncoercible_falls_back(self):
        self.assertIs(_coerce(3.5, 1), _MISSING)      # 1.5 不是整数
        self.assertIs(_coerce("x", 1), _MISSING)
        self.assertIs(_coerce(None, "aa"), _MISSING)
        self.assertIs(_coerce(1, True), _MISSING)     # 1 不能悄悄当 True
        self.assertIs(_coerce(True, 1), _MISSING)

    def test_same_type_passes_through(self):
        self.assertEqual(_coerce({"a": 1}, {"b": 2}), {"a": 1})
        self.assertEqual(_coerce("text", "s"), "text")


class ConfigPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, text):
        path = os.path.join(self.dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def _read(self, path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_string_bool_is_converted_and_persisted(self):
        """B12 的核心回归：`"True"` 不能被静默改成 False。"""
        path = self._write("cfg", json.dumps({"flag": "True", "count": "3"}))
        cfg = Config("cfg", {"flag": False, "count": 1}, folder=self.dir)
        self.assertIs(cfg["flag"], True)
        self.assertEqual(cfg["count"], 3)
        on_disk = self._read(path)
        self.assertIs(on_disk["flag"], True)           # 归一化后的值已落盘
        self.assertEqual(on_disk["count"], 3)

    def test_uncoercible_value_falls_back_to_default(self):
        self._write("cfg2", json.dumps({"ratio": "abc"}))
        cfg = Config("cfg2", {"ratio": 1.5}, folder=self.dir)
        self.assertEqual(cfg["ratio"], 1.5)

    def test_broken_file_is_backed_up_not_silently_lost(self):
        path = self._write("cfg3", '{"a": ')
        cfg = Config("cfg3", {"a": 1}, folder=self.dir)
        self.assertEqual(cfg["a"], 1)                  # 回默认
        self.assertTrue(os.path.exists(path + ".bad"), "坏文件没有备份 —— 用户设置就这么没了")
        with open(path + ".bad", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"a": ')       # 备份是**原样**的坏文件, 便于人工抢救
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"a": 1})   # 新文件是合法默认配置

    def test_write_is_atomic_and_leaves_no_tmp(self):
        path = os.path.join(self.dir, "cfg4.json")
        cfg = Config("cfg4", {"n": 1}, folder=self.dir)
        cfg["n"] = 2
        self.assertFalse(os.path.exists(path + ".tmp"), "临时文件没清掉")
        self.assertEqual(self._read(path), {"n": 2})

    def test_validator_still_gates(self):
        def validator(key, value):
            return (value < 10, None)                  # 与 Config.validate 的 (valid, message) 对齐

        cfg = Config("cfg5", {"n": 1}, folder=self.dir, validator=validator)
        cfg["n"] = 99                                  # 校验不过 → 不生效
        self.assertEqual(cfg["n"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
