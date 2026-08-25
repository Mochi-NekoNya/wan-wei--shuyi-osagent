"""仓库根 conftest：保证 ``backend.app.*`` 绝对导入在任何 cwd 下都可用。

背景
----
测试套件统一使用 ``from backend.app...`` 绝对导入。仓库根目录必须在
``sys.path`` 上，pytest 的 rootdir 自动插值依赖 conftest 的所在位置。

pytest 会在收集任何测试模块**之前**自动加载本文件，因此在这里插入
仓库根路径即可让绝对导入成立，无需依赖调用者的 cwd。
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent

_entry = str(_REPO_ROOT)
if _entry not in sys.path:
    sys.path.insert(0, _entry)
