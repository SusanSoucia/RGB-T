"""算法包。

之所以有这个文件：让 `python -m ml.datasets.inspect_dataset` 这类命令能跑。
没有 __init__.py 时 Python 会退化成命名空间包，某些情况下 `-m` 执行会出问题，
显式建一个更稳。
"""
