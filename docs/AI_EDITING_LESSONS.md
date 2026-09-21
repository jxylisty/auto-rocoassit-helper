# AI 编辑避坑手册

> 面向后续在本仓库工作的 AI/开发者。这里记录的都是**踩过、查清根因、并已修复**的真实故障，
> 共同特点是：**表现像玄学（随机、时好时坏、看起来没道理），但根因完全确定且可复现**。
>
> 动手改窗口、线程、DPI、启动流程、打包入口相关代码前，**先读这份文档**。
> 事故复盘（按严重程度）：启动竞态闪退 → 悬浮窗飞出屏幕 → 主窗口尺寸失控 → 打包版双击无反应。

---

## 0. 一页速查

| 症状 | 根因 | 修复位置 |
|---|---|---|
| 启动时窗口**随机瞬闪即退**（无报错框，时好时坏） | 后台线程首次 `import win32ui` 撞上 `keyboard` 初始化触发的 GC | `src/gui/window_sizing.py::prewarm_c_extensions()` |
| 悬浮窗**跑到屏幕外**（如 2560 宽的屏出现在 x=3112） | 物理像素与逻辑像素混用，`move()` 被二次放大 1.5 倍 | `src/gui/bridge.py::_set_widget_pos()` |
| 主窗口**尺寸忽大忽小/超屏** | pywebview 建窗期 DPI 倍率不可控（实测 1.39~1.47） | `hidden=True` 建窗 + 物理像素定尺后 `show()` |
| 打包版 exe **双击没反应**（无窗口无报错） | `set_pvp_float_window(None)` 抛异常，被 `--noconsole` 吞掉 | `src/gui/bridge.py`（已 None 安全）+ `tools/app_entry.py` |

**铁律：这个项目里所有窗口几何，一律只用「物理像素」思考和计算。**
任何要传给 pywebview 创建参数的尺寸，都必须明确换算，不能想当然。

---

## 1. 启动随机闪退（access violation）

### 症状
- 双击启动，窗口一闪就没了，**没有错误弹窗、没有 traceback**
- 重开又好了，或者连开几次挂一次 —— "时好时坏"
- `data/logs/startup.log` 里有 `Windows fatal exception: access violation`

### 根因（已由 6 次崩溃转储确认，签名完全一致）

启动时两件事几乎同时发生：

```
主线程                     后台 BattleWatch 线程
  │                              │
  ├─ enable_hotkeys()            │
  │   └─ keyboard 首次初始化      │
  │       └─ _setup_name_tables  │
  │           ctypes 扫描全部按键  │
  │           分配风暴 → 触发 GC   │
  │                              ├─ _watch_loop → _find_game_window
  │                              │   └─ 首次 import src.capture.window_capture
  │                              │       └─ 第 13 行 import win32ui  ← 死亡现场
  └──────── 两者在 GC 期间同时初始化 C 扩展 ────────┘
                     → access violation
```

转储里的两行关键证据（每次都一样）：
- `Current thread ... Garbage-collecting` / `keyboard/_winkeyboard.py ... _setup_name_tables`
- 另一线程 `src/capture/window_capture.py, line 13 in <module>` → `create_module`

### 为什么"修过又坏了"
这个修复**依赖"预热代码真的在启动路径上被执行"**。曾经修好过，但后来
`main.py` 被改动/回滚时预热语句丢了，故障就复发了 —— 而崩溃是随机的，
所以很容易误判成"没修好"或"玄学"。

⚠️ **改动 `main.py` / `tools/app_entry.py` 的启动流程时，务必保留 `prewarm_c_extensions()`，
且必须在 `set_window()`（启动后台线程）和 `enable_hotkeys()`（GC 风暴）之前。**

### 修复
```python
# main.py / tools/app_entry.py 启动最早处
from src.gui.window_sizing import prewarm_c_extensions
prewarm_c_extensions()      # 任何线程启动之前，单线程先导入一遍
```
`src/gui/bridge.py::AppBridge.__init__` 里也兜了一次，任何入口都受保护。
要预热的模块清单见 `_PREWARM_MODULES`（win32ui/win32gui/cv2/numpy/window_capture…）。

### 自查方法
```bash
python -c "
import sys; sys.path.insert(0,'.')
from src.gui.window_sizing import prewarm_c_extensions, _PREWARM_MODULES
prewarm_c_extensions()
missing = [m for m in _PREWARM_MODULES if m not in sys.modules]
print('缺失 =', missing or '无(全部已就绪)')
"
```
应为 `无(全部已就绪)`。

> ⚠️ **验证这个修复时不要用 import hook 测"谁 import 了它"**。
> `from src.capture.window_capture import find_window` 即使模块早就导入过，
> 也会记录成"当前线程调用了 import 语句"，看起来像没生效，容易得出错误结论。
> **正确的不变量是**：这些模块在**任何线程启动之前**就已存在于 `sys.modules`
> —— 已在 `sys.modules` 的模块，后续线程再 import 绝不会重新初始化，
> C 扩展的首次初始化竞态因此不可能发生。
>
> 另注：这个崩溃是**时序**竞态，用脚本强行复现并不可靠
> （实测跑 6 次"不预热"对照组也未崩）。别因为"复现不出来"就认为没 bug。

---

## 2. 悬浮窗飞出屏幕（DPI 二次缩放）

### 症状
日志里悬浮窗位置离谱，例如屏幕只有 2560 宽却报 `x=3112`：
```
[DEBUG] Widget window position: x=3112, y=712, w=477, h=418
```
窗口**完全看不见**，但代码逻辑"看起来"完全正确。

### 根因（数字可精确对上）

150% 缩放的机器上：物理宽 2560、逻辑宽 1707、缩放 1.5。

```
_compute_widget_position() 用【物理】工作区算：
    x = 2560 − 477(窗口物理宽) − 8 = 2075      ← 正确，物理像素

但 self._widget.move(2075, 475) 内部又乘了一次缩放：
    2075 × 1.5 = 3112     ← 日志里的值
    475  × 1.5 = 712      ← 日志里的值
```
**屏幕只有 2560 宽，窗口被推到 3112，自然整块飞出屏幕。**

pywebview winforms 后端的单位约定（实测确认）：

| 调用 | 入参单位 | 行为 |
|---|---|---|
| `move(x, y)` | **CSS/逻辑像素** | 后端内部**再乘一次**缩放 → 物理 |
| `resize(w, h)` | **物理像素** | 原样透传给 `SetWindowPos` |
| `window.x/.width` | 物理像素 | 读的是真实窗口矩形 |
| `SPI_GETWORKAREA` | **看进程 DPI 感知状态** | 不感知=逻辑，感知=物理 |
| `find_window()` | 物理像素 | `GetWindowRect` |

⚠️ **同一个项目里这两套单位是混着的**，直接混用必炸。

### 修复
`src/gui/bridge.py`：
- `_set_widget_pos()` —— 一律用 `SetWindowPos` 直传物理像素，绕开 `move()` 的隐式缩放
- `_window_rect()` / `_widget_physical_size()` / `_widget_physical_topleft()` —— 统一从真实窗口矩形读
- `_clamp_widget_pos()` —— 全部按物理像素夹取，保证窗口完整可见
- `_ensure_widget_on_screen()` —— 显示后自愈，越界就拉回
- `move_window_by()` —— 拖拽增量是 `e.screenX`（CSS 像素），**要乘缩放**才是物理位移

### 附带挖出的两个坑
1. **游戏最小化时坐标是垃圾值**：最小化的窗口矩形是 `(-32000, -32000)`，
   `find_window()` 照样返回它 → 落点算出 -32000 级别 → 窗口飞到几万像素外。
   现在会先用 `IsIconic()` 和坐标阈值剔除最小化窗口。
2. **`window.native_handle` 在 pywebview 6.1 不存在**（只有 `.native`），
   所以 `set_pvp_float_window` 里的防截屏 `SetWindowDisplayAffinity` **一直静默失效**
   （异常被 `except` 吞了）。现在从 `.native.Handle` 取句柄。

---

## 3. 主窗口尺寸失控

### 症状
窗口太小/太大/超出屏幕，且**不同机器表现不一致**。

### 根因
pywebview 创建窗口时，`width/height` 会被 WinForms 按当前 DPI 做一次倍率换算。
实测这个倍率**不是固定 1.5**，而是 **1.39 ~ 1.47 之间浮动**，取决于
进程何时变成 DPI 感知（而 `window_capture.py` 的 `enable_dpi_awareness()`
是导入副作用，时机又受预热影响）。

更隐蔽的连锁反应：**加了预热之后**，进程在计算尺寸前就已经是 DPI 感知，
于是 `SPI_GETWORKAREA` 从返回逻辑值(1707×912)变成返回物理值(2560×1368)——
如果尺寸公式还按老假设写，就会算出超屏尺寸（实测会到 2520 物理宽 + 偏移）。

### 修复
`src/gui/window_sizing.py`：

1. **`physical_metrics()`** —— 用 `DESKTOPHORZRES / SM_CXSCREEN` 的比例归一化，
   返回**永远物理像素**的工作区，不受进程 DPI 感知状态影响。
2. **`compute_main_window_size()`** —— 按工作区 96% × 94% 算目标（物理像素）。
3. **`apply_window_size_physical()`** —— 等 hwnd 就绪 →
   `SetWindowPos` 按物理像素定尺居中 → **再 `show()`**。

配套改动：`main.py` / `tools/app_entry.py` 建窗时用 `hidden=True`，
尺寸交给 `apply_window_size_physical`。这样用户**第一眼就是正确尺寸，不会闪**。

```
隐藏建窗 → SetWindowPos(物理像素) → show()
```

### 为什么不直接用 pywebview 的 resize()
`resize(w,h)` 虽然透传物理像素，但**会把隐藏窗口强制显示出来**，
而且它 `resize` 的实现里有 `self.Location.X` 读取——在 DPI 缩放下同样有单位混用风险。
定尺一律走 `SetWindowPos` 最稳。

---

## 4. 改窗口/DPI/线程代码时的检查清单

改完请逐条自检：

- [ ] 新增的窗口几何计算，用的是**物理像素**还是逻辑像素？两者有没有混算？
- [ ] 传给 `webview.create_window()` 的尺寸，是"目标物理值"还是"逻辑值"？要不要 ÷ 缩放？
- [ ] 调 `self._widget.move()` 了吗？**改用 `_set_widget_pos()`**。
- [ ] 启动路径里 `prewarm_c_extensions()` 还在吗？在 `set_window()`/`enable_hotkeys()` 之前吗？
- [ ] 新增了在**后台线程里懒加载**的重 C 扩展吗？→ 加进 `_PREWARM_MODULES`。
- [ ] 读 `SPI_GETWORKAREA` 的地方，考虑过进程 DPI 感知状态吗？（用 `physical_metrics()`）
- [ ] `SetWindowPos`/`GetWindowRect` 用的是独立 `WinDLL` 句柄吗？（见下节）
- [ ] 最小化窗口的 `(-32000,-32000)` 坐标处理了吗？
- [ ] 改动 `main.py` 后，跑一次 `python main.py` 确认不再闪退。
- [ ] 改了 `src/` 或 `tools/app_entry.py` 后，**重新打包并跑 `--smoke`**，
      再 `cat boot_error.log`（打包版报错只在这里，界面看不到）。

### 关于全局 argtypes 污染（隐藏地雷）
`auto_throw_ball.py` 在模块级做了：
```python
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
```
这**污染了全局** `ctypes.windll.user32`。之后任何传自建 `Structure` 的调用
都会抛 `ArgumentError`（而且常被 `except` 吞掉，表现为"功能静默失效"）。
**对策**：用独立的 `ctypes.WinDLL("user32")` 实例（argtypes 不共享），
或优先走 pywin32（不经过 ctypes）。参考 `window_sizing._u32()` / `bridge._u32()`。

---

## 4.5 打包（PyInstaller 冻结版）专属坑

### 坑 1：`set_pvp_float_window(None)` 会崩
打包入口 `tools/app_entry.py` 里曾有这段：
```python
# 打包版 WebView2 不支持第二个窗口 → bridge 降级: 用主窗口内浮层代替
bridge.set_widget_window(None)
bridge.set_pvp_float_window(None)
```
`set_pvp_float_window` 开头直接 `window.events.loaded += ...`，传 `None` 就
`AttributeError: 'NoneType' object has no attribute 'events'` —— 而它外面套着
`--noconsole`，用户看到的就是**双击没反应**（错误只在 `boot_error.log` 里）。

更关键的是**这个降级的理由是错的**：实测冻结版（`--onedir` + `--collect-all webview`）
**可以**正常创建第二个窗口。我用最小复现工程验证过：
```
主窗 hwnd = 3213408
浮窗 hwnd = 1247456
RESULT: 双窗口可用 OK
```
所以正确做法是**打包版照样创建悬浮窗**（与源码版一致），不要降级成 `None`。
若将来确实需要降级，`set_pvp_float_window` / `set_widget_window` 现已做 None 安全处理。

### 坑 2：冻结版启动报错看不到
`--noconsole` 没有控制台，启动异常必须靠 `tools/app_entry.py::_boot_error()` 落到
`exe 同级/boot_error.log` 并弹窗。**打包后一定要跑一次实测**（见下）。

### 坑 3：`--smoke` 自测必须自己能退出
做冒烟测试时，窗口不会自动关就会一直挂着（`timeout` 只能等它超时）。
`app_entry.py` 的 `--smoke` 分支用 `Timer(10.0, window.destroy)` 兜底。

### 打包与验证流程
```bash
python tools/build_main_app.py                 # → dist/洛克王国助手/ + .zip
cd dist/洛克王国助手
./洛克王国助手.exe --smoke                      # 跑冒烟(跳过提权/驱动)
cat boot_error.log                             # 有内容=启动失败, 必须看完再发包
```
产物检查脚本会自动核对 7 项（主程序/驱动安装器/前端页面/ROI模板/精灵名单/
战斗角标模板/RapidOCR模型）。**另外建议手动确认新模块进包**：
```bash
python -c "
from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
import tempfile, os
c = CArchiveReader(r'dist/洛克王国助手/洛克王国助手.exe')
p = os.path.join(tempfile.gettempdir(),'_x.pyz')
open(p,'wb').write(c.extract('PYZ.pyz'))
z = ZlibArchiveReader(p)
for n in sorted(z.toc):
    if 'window_sizing' in n or 'window_capture' in n: print('✅', n)
"
```
纯 `.py` 模块会被打进 exe 内的 `PYZ.pyz`，**不会**以散文件出现在 `_internal/src/`，
所以别用"在 `_internal` 里找不到 .py"来判断模块没进包。

---

## 5. 复现/验证脚本模板

改完窗口相关代码，用这个模板实测（**不要只看代码就下结论**）：

```python
# 1) 先看 units: 各 API 到底返回什么
import ctypes
u = ctypes.WinDLL('user32'); g = ctypes.WinDLL('gdi32')
hdc = g.CreateDCW('DISPLAY', None, None, None)
phys_w = g.GetDeviceCaps(hdc, 118); g.DeleteDC(hdc)
sm_w = u.GetSystemMetrics(0)
print(f'物理宽={phys_w} 逻辑宽={sm_w} 缩放={phys_w/sm_w:.3f}')

# 2) 实测窗口最终矩形(不要信 pywebview 的自报值)
class R(ctypes.Structure):
    _fields_ = [('l',ctypes.c_long),('t',ctypes.c_long),
                ('r',ctypes.c_long),('b',ctypes.c_long)]
hwnd = int(window.native.Handle.ToInt32())
r = R(); u.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r))
print('真实物理矩形 =', (r.l, r.t, r.r-r.l, r.b-r.t))

# 3) 断言完整在屏内
wa = R(); u.SystemParametersInfoW(48, 0, ctypes.byref(wa), 0)
assert r.l >= wa.l and r.t >= wa.t and r.r <= wa.r and r.b <= wa.b, '越界!'
```

关键原则：**以 `GetWindowRect` 的真实物理矩形为唯一真相**，
pywebview 的 `.x/.width` 在 DPI 场景下可能与你传入的值不是同一个坐标系。

---

## 6. 已修复故障清单（便于回归）

| # | 故障 | 修复文件 |
|---|---|---|
| 1 | 启动随机闪退（线程导入竞态） | `src/gui/window_sizing.py`、`main.py`、`tools/app_entry.py`、`src/gui/bridge.py` |
| 2 | 悬浮窗 DPI 二次缩放飞出屏幕 | `src/gui/bridge.py` |
| 3 | 游戏最小化致落点算到 -32000 | `src/gui/bridge.py` |
| 4 | 防截屏因 `native_handle` 不存在而静默失效 | `src/gui/bridge.py` |
| 5 | 拖拽增量未按缩放换算（位移偏小/偏大 1.5 倍） | `src/gui/bridge.py` |
| 6 | 主窗口尺寸受建窗期 DPI 倍率影响而失控 | `src/gui/window_sizing.py`、`main.py` |
| 7 | 全局 `GetWindowRect.argtypes` 污染导致静默失败 | `src/gui/window_sizing.py`、`src/gui/bridge.py` |
| 8 | 打包版误降级致 `set_pvp_float_window(None)` 崩溃（双击无反应） | `tools/app_entry.py`、`src/gui/bridge.py` |

---
*最后更新：2026-09-21。修改窗口/DPI/线程/打包入口相关代码时请同步更新本文件。*
