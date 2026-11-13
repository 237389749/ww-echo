"""Minimal task manager (vendored from ok-script, trimmed).

只负责把 config 里的 onetime/trigger 任务实例化并挂到 TaskExecutor 上；
不加载 ok_tasks/ok_import 自定义任务、不做定时任务、不做文件监视、不做脚本打包。
"""

from ww_engine.util.clazz import init_class_by_name
from ww_engine.util.logger import Logger

logger = Logger.get_logger(__name__)


class TaskManager:
    def __init__(self, task_executor, app, trigger_tasks=None, onetime_tasks=None, scene=None):
        self.task_executor = task_executor
        self.app = app
        self.scene = init_class_by_name(scene[0], scene[1]) if scene else None
        self.task_executor.scene = self.scene
        self.task_executor.trigger_tasks = self.init_tasks(trigger_tasks or [])
        self.task_executor.onetime_tasks = self.init_tasks(onetime_tasks or [])
        for task in self.task_executor.trigger_tasks:
            task.post_init()
        for task in self.task_executor.onetime_tasks:
            task.post_init()

    def init_tasks(self, task_classes):
        tasks = []
        for task_class in task_classes:
            try:
                task = init_class_by_name(task_class[0], task_class[1],
                                          executor=self.task_executor, app=self.app)
                task.after_init(executor=self.task_executor, scene=self.scene)
                tasks.append(task)
            except Exception as e:
                logger.error(f'init task {task_class} failed: {e}', e)
        return tasks
