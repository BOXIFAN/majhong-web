"""UI/UX 调研改造期间的增量文案分片。

设计目的：让多个页面改造可以并行进行，而不需要同时编辑 70KB 的 ``brml/i18n.py``。

每个分片模块导出一个 ``T`` 字典，结构与本项目既有的 ``TRANSLATIONS`` 一致：

    T = {
        "zh": {"home.next_meetup_title": "下一场活动"},
        "en": {"home.next_meetup_title": "Next meetup"},
    }

本包会自动发现同目录下的所有子模块并合并；后加载的分片可以覆盖既有文案
（用于「统一术语」这类全局改写）。主翻译表仍然优先，分片只补位/覆盖，
因此即使分片模块出错也不会让站点丢失原有文案。
"""

from __future__ import annotations

import importlib
import pkgutil

REPORT_TRANSLATIONS: dict[str, dict[str, str]] = {"zh": {}, "en": {}}


def _collect() -> None:
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        table = getattr(module, "T", None)
        if not isinstance(table, dict):
            continue
        for locale in ("zh", "en"):
            values = table.get(locale)
            if isinstance(values, dict):
                REPORT_TRANSLATIONS[locale].update(values)


_collect()
