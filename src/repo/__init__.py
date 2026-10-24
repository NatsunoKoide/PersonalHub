"""数据仓库层：手写 SQL，无 ORM。所有对外返回的都是普通字典。

子模块不在这里导入，避免循环：它们只依赖 rows.py。
"""

from .rows import row_to_dict, rows_to_dicts

__all__ = ["row_to_dict", "rows_to_dicts"]
