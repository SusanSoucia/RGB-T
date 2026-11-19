# 中文字体（可选）

导出标注视频时，区域名默认写 `Region 1` 这种英文占位。

原因：OpenCV 的 `cv2.putText` 用 Hershey 矢量字体，**只支持 ASCII**，
写中文会变成一串问号。页面上显示的**中文名不受影响**（那是浏览器 canvas 渲染的），
只有**导出的视频文件**里会退化成英文。

## 想让导出视频里显示中文？

把一个**开源授权**的中文字体文件放进这个目录即可，代码会自动发现它
（`backend/app/services/render.py` 的 `cjk_font_path()`）。

支持 `.ttf` / `.ttc` / `.otf`，文件名随意。推荐：

| 字体 | 授权 | 体积 |
|---|---|---|
| 文泉驿微米黑（`wqy-microhei.ttc`） | Apache 2.0 / GPLv3 + 字体例外 | ~4 MB |
| 思源黑体（`SourceHanSansCN-Regular.otf`） | SIL OFL 1.1 | ~8 MB |
| 思源黑体 / Noto Sans CJK（`NotoSansCJK-Regular.ttc`） | SIL OFL 1.1 | ~19 MB |

> ⚠️ **不要**放 Windows 自带字体（微软雅黑、黑体等）：那些**不允许再分发**，
> 而本仓库是公开的。只用上面这类开源字体。

放好之后不需要重建镜像（`backend/` 是 bind mount），
重新导出一次视频就会用上中文：

```powershell
# 重新渲染（带 refresh 强制忽略缓存）
curl.exe -H "Authorization: Bearer <token>" ^
  "http://localhost:8000/api/detect-tasks/25/render?refresh=true"
```
