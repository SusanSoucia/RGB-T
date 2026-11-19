# ml/ —— 算法目录

## 约定

这个目录**不依赖 FastAPI、不依赖数据库**，必须能脱离 Web 系统独立跑。
后端只通过一个稳定接口调用它（见 `README.md` §8）：

```
输入: 帧(RGB[, IR]) + 模式 ∈ {rgb, ir, fusion, auto}
输出: {boxes, scores, mode_actual, reason, elapsed_ms}
```

## 目录规划

```
ml/
├── requirements.txt
├── datasets/        # 数据加载与划分（固定划分，产物落 json）
├── models/
│   ├── rgb/         # 可见光单模态
│   ├── ir/          # 红外单模态
│   └── fusion/      # 双模态协同（先结果级，后特征级）
├── selector/        # 自适应模式选择策略 + 阈值配置
├── infer.py         # ← 对外统一推理入口（后端只认这个）
├── train.py
└── evaluate.py      # 四组对比实验：rgb / ir / fusion / auto
```

## 两条环境路线

| 场景 | 用什么 | 原因 |
|---|---|---|
| 日常调参、炼丹 | **主机 venv** 直连 GPU | 最快，没有 bind mount 的 I/O 损耗 |
| 复现、交付、上服务器 | **Docker（`--profile ml`）** | 环境一致，别人能跑出同样结果 |

两条路线**共用同一份 `requirements.txt` 和同一份代码**，所以结果不会打架。

详见 `../docs/docker-dev.md`。
