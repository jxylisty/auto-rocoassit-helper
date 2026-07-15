# 精灵小窝优化器

这是一个沿用现有网页的轻量精确求解器后端。

## 启动

```powershell
.\tools\nest_optimizer\.venv\Scripts\python.exe -m uvicorn tools.nest_optimizer.app:app --host 127.0.0.1 --port 8765
```

## 接口

- `GET /health`
- `POST /solve`

网页会向 `http://127.0.0.1:8765/solve` 发送当前输入。

## 说明

- 前端页面仍然是 `docs/roco_shiny_breeding_planner.html`
- 求解器使用 `OR-Tools CP-SAT`
- 当前建议直接使用 `tools/nest_optimizer/.venv`
- 当前实现是轻量 MVP，优先保证“小工具可运行”和“结果可验证”
- 若本地服务未启动，网页会回退到内置 JS 近似求解
