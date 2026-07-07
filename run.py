"""
无 GUI 启动入口 — 读取 JSON 配置, 直接跑声骸强化。
"""
import json
import sys
from config import config
from ok import OK

if __name__ == '__main__':
    # 加载套装配置
    config_path = "assets/echo_set_templates.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            echo_config = json.load(f)
        print(f"已加载 {len(echo_config.get('sets', {}))} 个套装模板")
    except Exception as e:
        print(f"加载套装配置失败: {e}")
        sys.exit(1)

    # 禁掉 GUI, 直接用命令行参数选任务
    config['use_gui'] = True  # 还是开着, 需要窗口消息循环
    config['debug'] = True
    ok = OK(config)
    ok.start()
