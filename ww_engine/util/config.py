## Config.py
import os
import shutil

from ww_engine.gui.Communicate import communicate
from ww_engine.util.file import get_relative_path, read_json_file, write_json_file
from ww_engine.util.logger import Logger

logger = Logger.get_logger("Config")

#: `_coerce` 的"转不了"，交给调用方回退默认值
_MISSING = object()


def _coerce(value, default):
    """把磁盘上的值转成默认值的类型；转不了返回 `_MISSING`。

    为什么要 coerce：配置是 JSON —— 用户手改/旧版本可能写 `"True"`、`"3"`。旧实现只要
    `isinstance` 不匹配就**静默换成默认值并覆写文件**：设置看起来"保存成功了"，下次启动全没了，
    而日志里一个字都没有（2026-11-22 后端审查 B12）。
    """
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        text = value.strip().lower() if isinstance(value, str) else value
        if text in ("true", "1", "yes", "on", "是"):
            return True
        if text in ("false", "0", "no", "off", "否"):
            return False
        return _MISSING
    if isinstance(default, int):            # bool 已在上面处理过
        if isinstance(value, bool):
            return _MISSING
        try:
            num = float(value) if isinstance(value, str) else value
            return int(num) if float(num).is_integer() else _MISSING
        except (TypeError, ValueError):
            return _MISSING
    if isinstance(default, float):
        try:
            return float(value) if not isinstance(value, bool) else _MISSING
        except (TypeError, ValueError):
            return _MISSING
    if isinstance(default, str):
        return value if isinstance(value, str) else _MISSING
    return value if isinstance(value, type(default)) else _MISSING


class ConfigOption:

    def __init__(self, name, default=None, description="", config_description=None, config_type=None,
                 validator=None, icon=None, show_at_tab=False):
        """`icon` 只给 ok-script 的原生 GUI 用；本项目自建 UI 不读它，默认 None。

        以前这里默认 `FluentIcon.INFO`，导致 `import ww_engine` 被迫拉起 qfluentwidgets（≈0.6 s）。
        """
        self.name = name
        self.description = description
        self.default_config = default or {}
        self.config_description = config_description or {}
        self.config_type = config_type
        self.validator = validator
        self.icon = icon
        self.show_at_tab = show_at_tab


class Config(dict):
    config_folder = 'configs'

    def __init__(self, name, default, folder=None, validator=None):
        """
        Initialize the Config object.

        :param default: Default configuration values.
        :param folder: Folder where the config file is stored.
        :param name: Name of the config file.
        :param validator: Optional function to validate key-value pairs.
        """
        self.default = default
        self.validator = validator
        if folder is None:
            folder = self.config_folder
        self.config_file = get_relative_path(folder, f"{name}.json")

        # Read the config file, if it exists, otherwise use default
        config = read_json_file(self.config_file)
        if config is None:
            if os.path.exists(self.config_file):
                # 文件在、但读不出来(空文件/半截 JSON/手改坏) → 先留一份 `.bad` 再重置,
                # 否则用户的设置就这么无声无息地没了(B12)。
                backup = f'{self.config_file}.bad'
                try:
                    shutil.copy2(self.config_file, backup)
                    logger.warning(f'配置文件解析失败, 已备份到 {backup} 并重置为默认: {self.config_file}')
                except OSError as e:
                    logger.error(f'配置文件解析失败且备份失败({e}), 重置为默认: {self.config_file}')
            self.reset_to_default()
        else:
            super().__init__()
            modified = self.verify_config(config, default)
            if modified:
                self.save_file()
        logger.debug(f'init self.config = {self}')

    def save_file(self):
        """
        Save the current configuration to the file.
        """
        try:
            write_json_file(self.config_file, self)
        except Exception as e:
            logger.error(f'save_file error: {e}')

    def get_default(self, key):
        return self.default.get(key)

    def reset_to_default(self):
        """
        Reset the configuration to the default values.
        """
        super().clear()
        self.update(self.default)
        self.save_file()
        logger.debug(f'reset_to_default self.config = {self}')

    def pop(self, key, default=None):
        """
        Remove and return a value from the configuration.

        :param key: The key to remove.
        :param default: The default value if the key does not exist.
        :return: The removed value.
        """
        result = super().pop(key, default)
        self.save_file()
        return result

    def popitem(self):
        """
        Remove and return the last key-value pair from the configuration.
        """
        result = super().popitem()
        self.save_file()
        return result

    def clear(self):
        """
        Clear all configuration values.
        """
        super().clear()
        self.save_file()

    def __setitem__(self, key, value):
        if value != self.get(key) and self.validate(key, value):
            old_value = self.get(key)
            super().__setitem__(key, value)
            if old_value != value:
                self.save_file()

    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError as e:
            logger.error(f'KeyError: {key} not found in config: {self}')
            raise e

    def has_user_config(self):
        return not all(key.startswith('_') for key in self)

    def validate(self, key, value):
        """
        Validate a configuration key-value pair.

        :param key: The key to validate.
        :param value: The value to validate.
        :return: True if valid, False otherwise.
        """
        if self.validator is not None:
            valid, message = self.validator(key, value)
            if not valid:
                communicate.config_validation.emit(message)
                return False
        return True

    def verify_config(self, current, default_config):
        """
        Verify the configuration against the default configuration.

        :param default_config: The default configuration.
        :return: True if the config was modified, False otherwise.
        """
        modified = False

        # Remove entries that do not exist in default_config
        for key in list(current.keys()):
            if key not in default_config:
                del current[key]
                modified = True

        for key in list(default_config.keys()):
            if key not in current:
                value = default_config[key]
                modified = True
            else:
                raw = current[key]
                coerced = _coerce(raw, default_config[key])
                if coerced is _MISSING:
                    if type(raw) is not type(default_config[key]):
                        logger.warning(f'配置项 {key}={raw!r} 转不成 {type(default_config[key]).__name__}, '
                                       f'已回退默认值 {default_config[key]!r}')
                    value = default_config[key]
                    modified = True
                else:
                    value = coerced
                    if coerced != raw or type(coerced) is not type(raw):
                        modified = True            # "True"→True 这类转换要落盘, 免得每次启动都再转
                    if self.validator is not None and not self.validate(key, value):
                        value = default_config[key]
                        modified = True
            self[key] = value

        return modified
