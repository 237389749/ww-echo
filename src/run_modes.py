"""运行模式常量（local / cloud）。

放在 domain 层是为了让 `ui.settings_tab` 与 `config` 共用同一份字符串，
避免 UI 为了两个常量去 import 入口模块 `config`（那会形成 ui→entry 的反向依赖）。
"""

MODE_LOCAL = "local"
MODE_CLOUD = "cloud"
