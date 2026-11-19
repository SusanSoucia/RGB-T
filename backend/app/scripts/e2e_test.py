"""端到端接口自测。

用合成的图片把整条业务链跑一遍，**不需要真实数据集、不需要训练好的模型**：

    登录 → 上传（明/暗两组成对图）→ 建区域 → 检测
         → 校验自适应选模态 → 校验侵入与告警 → 确认告警 → 清理

它的价值在于：模型换成真的之后，这个脚本仍然能跑，用来快速确认
"接口和链路没被改坏"。建议每次动完 api/services 都跑一遍。

用法（容器内）：
    docker compose exec api python -m app.scripts.e2e_test
    # 也可以指定地址：--base http://localhost:8000
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import cv2
import httpx
import numpy as np


def make_bright_image(path: Path) -> None:
    """亮场景：高亮度 + 高对比 + 高锐度 → 应该选 RGB。"""
    h, w = 480, 640
    xx = np.linspace(0, 255, w, dtype=np.float32)[None, :]
    yy = np.linspace(0, 255, h, dtype=np.float32)[:, None]
    base = (xx * 0.5 + yy * 0.5)  # 对角线渐变，保证对比度高
    noise = np.random.default_rng(0).normal(0, 6, (h, w)).astype(np.float32)
    gray = np.clip(base + noise, 0, 255).astype(np.uint8)
    img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.imwrite(str(path), img)


def make_dark_image(path: Path) -> None:
    """暗场景：亮度远低于阈值(40) → 有成对红外时应选热红外。"""
    h, w = 480, 640
    img = np.random.default_rng(1).normal(12, 3, (h, w, 3))
    img = np.clip(img, 0, 255).astype(np.uint8)
    # 加一点点结构，避免完全平坦导致清晰度指标为 0 干扰判断
    cv2.rectangle(img, (w // 3, h // 3), (w // 2, h // 2), (60, 60, 60), -1)
    cv2.imwrite(str(path), img)


class Fail(Exception):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise Fail(msg)
    print(f"  [ok] {msg}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="Admin@12345")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    client = httpx.Client(base_url=base, timeout=120.0)
    created_media: list[int] = []

    def hdr() -> dict:
        return {"Authorization": f"Bearer {token}"}

    try:
        # ---------------- 1. 登录 ----------------
        print("\n[1] 登录")
        r = client.post("/api/auth/login", json={"username": args.username, "password": args.password})
        check(r.status_code == 200, f"登录返回 200（实际 {r.status_code}）")
        token = r.json()["access_token"]
        me = client.get("/api/auth/me", headers=hdr())
        check(me.status_code == 200 and me.json()["username"] == args.username, "获取当前用户")

        # 错误密码应当 401
        bad = client.post("/api/auth/login", json={"username": args.username, "password": "wrong-pwd"})
        check(bad.status_code == 401 and bad.json()["code"] == "AUTH_INVALID_CREDENTIALS",
              "错误密码返回 401 + AUTH_INVALID_CREDENTIALS")

        tmp = Path(tempfile.mkdtemp(prefix="e2e_"))
        bright_rgb = tmp / "bright_rgb.png"
        bright_ir = tmp / "bright_ir.png"
        dark_rgb = tmp / "dark_rgb.png"
        make_bright_image(bright_rgb)
        make_bright_image(bright_ir)
        make_dark_image(dark_rgb)

        # ---------------- 2. 上传：亮场景成对 ----------------
        print("\n[2] 上传亮场景（RGB + 红外）")
        with bright_rgb.open("rb") as f1, bright_ir.open("rb") as f2:
            r = client.post(
                "/api/media",
                headers=hdr(),
                files={"file": ("bright.png", f1, "image/png"),
                       "ir_file": ("bright_ir.png", f2, "image/png")},
            )
        check(r.status_code == 201, f"上传返回 201（实际 {r.status_code} {r.text[:120]}）")
        bright = r.json()
        created_media.append(bright["id"])
        check(bright["has_ir"] is True, "识别出成对（has_ir=true）")
        check(bright["status"] == "ready", "媒体状态 ready")

        # ---------------- 3. 上传：暗场景成对 ----------------
        print("\n[3] 上传暗场景（低照度 + 红外）")
        with dark_rgb.open("rb") as f1, bright_ir.open("rb") as f2:
            r = client.post(
                "/api/media",
                headers=hdr(),
                files={"file": ("dark.png", f1, "image/png"),
                       "ir_file": ("bright_ir.png", f2, "image/png")},
            )
        dark = r.json()
        created_media.append(dark["id"])
        check(r.status_code == 201, "上传返回 201")

        # ---------------- 4. 上传：仅有可见光 ----------------
        print("\n[4] 上传仅可见光（用于测手动模式校验）")
        with bright_rgb.open("rb") as f1:
            r = client.post(
                "/api/media",
                headers=hdr(),
                files={"file": ("rgb_only.png", f1, "image/png")},
            )
        rgb_only = r.json()
        created_media.append(rgb_only["id"])
        check(rgb_only["has_ir"] is False, "has_ir=false")

        # ---------------- 5. 自适应选择：亮 → rgb ----------------
        print("\n[5] 自适应选模态（亮场景应选 rgb）")
        r = client.post("/api/detect-tasks", headers=hdr(),
                        json={"media_id": bright["id"], "requested_mode": "auto"})
        check(r.status_code == 201, f"检测返回 201（实际 {r.status_code} {r.text[:160]}）")
        t_bright = r.json()
        check(t_bright["status"] == "succeeded", "任务成功")
        check(t_bright["actual_mode"] == "rgb",
              f"选了 rgb（实际 {t_bright['actual_mode']}，理由：{t_bright['decision_reason']}）")
        check(bool(t_bright["decision_reason"]), f"记录选择原因：{t_bright['decision_reason']}")

        # ---------------- 6. 自适应选择：暗 → ir ----------------
        print("\n[6] 自适应选模态（暗场景应选 ir）")
        r = client.post("/api/detect-tasks", headers=hdr(),
                        json={"media_id": dark["id"], "requested_mode": "auto"})
        t_dark = r.json()
        check(t_dark["actual_mode"] == "ir",
              f"选了 ir（实际 {t_dark['actual_mode']}，理由：{t_dark['decision_reason']}）")
        check(t_dark["ref_modality"] == "ir" or t_dark["ref_modality"] == "rgb",
              f"参考模态 = {t_dark['ref_modality']}")

        # ---------------- 7. 手动模式不匹配 → 422 ----------------
        print("\n[7] 手动指定 ir 但无红外通道，应拒绝")
        r = client.post("/api/detect-tasks", headers=hdr(),
                        json={"media_id": rgb_only["id"], "requested_mode": "ir"})
        check(r.status_code == 422 and r.json()["code"] == "MODE_INPUT_MISMATCH",
              f"返回 422 + MODE_INPUT_MISMATCH（实际 {r.status_code} {r.text[:120]}）")

        # ---------------- 8. 建区域 ----------------
        print("\n[8] 创建警戒区域（覆盖画面中部）")
        r = client.post("/api/regions", headers=hdr(), json={
            "media_id": bright["id"], "name": "核心区", "shape_type": "rect",
            "points": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        })
        check(r.status_code == 201, f"建区域返回 201（实际 {r.status_code} {r.text[:120]}）")
        region = r.json()
        check(len(region["points"]) == 4, "区域存了 4 个顶点")

        # 非法区域应被拒
        r = client.post("/api/regions", headers=hdr(), json={
            "media_id": bright["id"], "shape_type": "rect",
            "points": [[0.5, 0.5], [0.5, 0.5], [0.5, 0.5]],
        })
        check(r.status_code == 422, "退化区域被拒（422）")

        # ---------------- 9. 带区域重跑 → 应有侵入与告警 ----------------
        print("\n[9] 带区域重跑检测，应产生侵入与告警")
        r = client.post("/api/detect-tasks", headers=hdr(),
                        json={"media_id": bright["id"], "requested_mode": "rgb"})
        t2 = r.json()
        check(t2["status"] == "succeeded", "任务成功")

        frames = client.get(f"/api/detect-tasks/{t2['id']}/frames", headers=hdr()).json()
        check(len(frames) > 0, f"有帧级记录（{len(frames)} 条）")
        check(any(f["intrusion_count"] > 0 for f in frames),
              f"至少一帧判定为侵入（各帧侵入数：{[f['intrusion_count'] for f in frames]}）")

        dets = client.get(f"/api/detect-tasks/{t2['id']}/detections", headers=hdr()).json()
        check(len(dets) > 0, f"有检测框（{len(dets)} 个）")
        check(all(0 <= d["x1"] <= 1 and 0 <= d["y1"] <= 1 for d in dets), "框坐标是归一化的")

        alerts = client.get("/api/alerts?page=1&page_size=50", headers=hdr()).json()
        mine = [a for a in alerts["items"] if a["media_id"] == bright["id"]]
        check(len(mine) > 0, f"生成了告警（{len(mine)} 条）")

        # ---------------- 10. 确认告警 ----------------
        print("\n[10] 确认告警（重复确认应 409）")
        aid = mine[0]["id"]
        r = client.post(f"/api/alerts/{aid}/confirm", headers=hdr())
        check(r.status_code == 200 and r.json()["status"] == "confirmed", "确认成功")
        r2 = client.post(f"/api/alerts/{aid}/confirm", headers=hdr())
        check(r2.status_code == 409 and r2.json()["code"] == "ALERT_ALREADY_CONFIRMED",
              "重复确认返回 409")

        # ---------------- 11. 越权与未授权 ----------------
        print("\n[11] 鉴权")
        r = client.get("/api/media")
        check(r.status_code == 401, f"未带 token 返回 401（实际 {r.status_code}）")
        r = client.get("/api/media", headers={"Authorization": "Bearer not-a-real-token"})
        check(r.status_code == 401, "伪造 token 返回 401")

        # ---------------- 12. 前端页面可达 ----------------
        print("\n[12] MVP 前端")
        r = client.get("/ui/")
        check(r.status_code == 200 and "反无人机" in r.text, "/ui/ 可访问")

        print("\n全部通过 ✅")
        return 0

    except Fail as e:
        print(f"\n[FAIL] {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        return 1
    finally:
        # ---------------- 清理 ----------------
        try:
            for mid in created_media:
                client.delete(f"/api/media/{mid}", headers=hdr())
            print(f"\n[clean] 已删除测试媒体 {created_media}")
        except Exception as e:  # noqa: BLE001
            print(f"\n[clean] 清理失败（手动删吧）：{e}")
        client.close()


if __name__ == "__main__":
    sys.exit(main())
