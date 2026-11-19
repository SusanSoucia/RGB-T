"""业务服务层。

约定：
- **不 import `app.api`**，依赖方向只能是 api → services → models/schemas；
- 不直接依赖 FastAPI 的 Request/Response，只接 Session 和普通数据类型；
- 这样服务层可以被脚本、单元测试、后台任务直接复用。
"""
