# AGENTS.md — AI 会话工作约定

洛克王国 PVP 助手：pywebview 桌面应用（anaconda Python），入口 `main.py`。

## Git 约定（必须遵守）

- **每次修改完成并验证后，必须 `git commit` 并 `git push origin main`**，不要只改不推。
- 提交信息用 conventional commits 风格（`fix(scope):` / `feat(scope):` / `chore:` / `refactor:`），正文中文，写清背景与验证方式。
- 提交信息含引号/中文时用 `git commit -F <临时文件>`，避免 shell 转义问题。
- 分两笔提交：代码修复一笔；`data/`（rounds 对战记录、history.db、状态 json）单独一笔 `chore(data):`。
- `.vscode/` 被 gitignore，机器相关配置改动无法入库，告知用户即可。

## 验证底线

- 改动 `main.py` / `src/gui/` 后：`python -m py_compile` 必过；涉及启动流程的实机启动一次验证（跑完用 `python main.py --kill-ghosts` 清理）。
- 启动问题先看 `data/logs/startup.log`（崩溃转储也在这里）。
