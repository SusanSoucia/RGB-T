"""统一错误类型。

响应格式固定为 docs/api.md §2.2 约定的：

    {"code": "MODE_INPUT_MISMATCH", "message": "...", "detail": null}

前端**按 code 分支**，不靠 message 文本匹配（改文案就崩）。
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """业务异常。抛它就等于返回一个结构化错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


# ---- 常用错误的快捷构造，避免各处手写重复文案 ----

def not_found(what: str = "资源") -> ApiError:
    return ApiError("RESOURCE_NOT_FOUND", f"{what}不存在", 404)


def forbidden(message: str = "无权访问该资源") -> ApiError:
    return ApiError("FORBIDDEN_NOT_OWNER", message, 403)


def bad_request(code: str, message: str, detail: Any = None) -> ApiError:
    return ApiError(code, message, 422, detail)
