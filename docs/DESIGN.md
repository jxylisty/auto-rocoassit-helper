# 洛克王国异色繁育规划器 - 视觉重构设计方案

## 一、现状问题分析

### 1.1 当前痛点
- **空间失衡**：左侧控制面板（Controls）在宽屏下过于空旷，大量垂直和水平空白未被利用
- **右侧过载**：右侧承载了"状态、方案选择、结论摘要、核心计数、库存表、SVG沙盘图、明细列表"等大量内容，形成冗长单列流水账
- **视觉重心失衡**：左边轻、右边重的呆板结构

### 1.2 重构目标
- 打破"左边轻、右边重"的布局
- 创建"控制中心"式的左侧面板
- 右侧专注于大宽幅动态内容展示

---

## 二、空间解耦与重新分配

### 2.1 响应式网格布局

#### 宽屏模式（> 1100px）- 非对称三栏布局
```
┌─────────────────────────────────────────────────────────────────┐
│                         顶部导航区                               │
├──────────────┬──────────────────────────┬─────────────────────┤
│   控制面板     │     左侧摘要区           │    右侧主内容区       │
│   (控制中心)   │   (Stats + Picker)      │   (SVG + 库存 + 明细)│
│   380-400px   │     弹性宽度             │      弹性宽度         │
└──────────────┴──────────────────────────┴─────────────────────┘
```

#### 平板模式（768px - 1100px）- 双栏布局
```
┌──────────────────────────┬──────────────────────────────────────┐
│     顶部导航 + 控制      │           摘要 + 统计                │
├──────────────────────────┼──────────────────────────────────────┤
│     SVG 沙盘图           │           库存表格                    │
├──────────────────────────┴──────────────────────────────────────┤
│                       明细列表                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 手机模式（< 768px）- 单栏堆叠
所有组件垂直堆叠，自适应宽度

### 2.2 左侧控制面板（控制中心）
- **宽度**：固定 380px
- **保留元素**：
  - 基础参数（公母数量、权重选择）
  - 计算按钮
- **新增迁移元素**：
  - 数据总览看板（Overview）
  - 核心计数块（Stats）
  - 方案精选器（Solution-Picker）
  - 状态显示

### 2.3 右侧主面板（内容展示）
- **专注内容**：
  - SVG 沙盘图（大宽幅展示）
  - 实时库存面板
  - 明细列表

---

## 三、模块化卡片设计（Bento Grid）

### 3.1 卡片设计规范

#### 毛玻璃质感
```css
background: rgba(255, 252, 246, 0.85);
backdrop-filter: blur(12px);
border: 1px solid rgba(255, 255, 255, 0.6);
```

#### 微阴影
```css
box-shadow: 
  0 4px 24px rgba(79, 61, 31, 0.08),
  0 1px 3px rgba(79, 61, 31, 0.04);
```

#### 圆角
```css
border-radius: 20px; /* 大卡片 */
border-radius: 14px; /* 小组件 */
```

### 3.2 卡片类型

| 卡片类型 | 用途 | 尺寸 |
|---------|------|------|
| 控制卡片 | 参数输入、按钮 | 固定宽度 380px |
| 统计卡片 | Stats 数据展示 | 横向并排，flex |
| 方案卡片 | 方案选择器 | 与统计卡片并排 |
| 沙盘卡片 | SVG 画布 | 全宽，min-height: 480px |
| 库存卡片 | 库存表格 | 全宽，max-height: 50vh |
| 明细卡片 | 巢穴明细+配对 | 左右分栏 |

### 3.3 Grid 布局组合

#### 左侧区域
```
┌────────────────────┐
│   控制面板          │  ← 380px 固定
│   (参数+按钮)       │
├────────────────────┤
│   状态+方案选择    │  ← 与下方统计并排
├────────┬───────────┤
│ 统计1  │  统计2   │  ← 2列 Grid
├────────┴───────────┤
│   统计3+4         │  ← 2列 Grid
└────────────────────┘
```

#### 右侧区域
```
┌─────────────────────────────────────┐
│           SVG 沙盘图                 │  ← 全宽，大卡片
├──────────────────┬──────────────────┤
│    库存表格      │    明细列表      │  ← 左右分栏
│                  │    (巢穴+配对)   │
└──────────────────┴──────────────────┘
```

---

## 四、游戏化温润色彩与微交互

### 4.1 色彩体系

#### 背景色
```css
/* 森林晨曦渐变 */
background: 
  radial-gradient(ellipse at 20% 0%, rgba(167, 213, 198, 0.4) 0%, transparent 50%),
  radial-gradient(ellipse at 80% 0%, rgba(255, 207, 160, 0.35) 0%, transparent 50%),
  radial-gradient(ellipse at 50% 100%, rgba(230, 200, 170, 0.3) 0%, transparent 60%),
  linear-gradient(180deg, #f8f4ed 0%, #efe6d8 100%);
```

#### 主题色
```css
:root {
  /* 雄性 - 薄荷蓝绿（天空与魔力） */
  --male: #56a7bb;
  --male-light: #7ec5d5;
  --male-glow: rgba(86, 167, 187, 0.3);
  
  /* 雌性 - 珊瑚粉橘（温暖与繁育） */
  --female: #e77f67;
  --female-light: #f0a090;
  --female-glow: rgba(231, 127, 103, 0.3);
  
  /* 异色/目标 - 金色（稀有度） */
  --shiny: #f5cd79;
  --shiny-glow: rgba(245, 205, 121, 0.4);
  
  /* 文字与 UI */
  --ink: #2d3e45;
  --muted: #6b7d85;
  --panel: rgba(255, 252, 246, 0.92);
  --panel-glass: rgba(255, 252, 246, 0.85);
  
  /* 功能色 */
  --good: #3a9d6e;
  --warning: #d97706;
  --error: #dc2626;
  
  /* 边框与阴影 */
  --line: rgba(45, 62, 69, 0.1);
  --shadow-soft: 0 8px 32px rgba(79, 61, 31, 0.1);
  --shadow-card: 0 4px 16px rgba(79, 61, 31, 0.08);
}
```

### 4.2 交互微动画

#### 全局过渡
```css
*, *::before, *::after {
  transition: 
    background-color 0.25s cubic-bezier(0.4, 0, 0.2, 1),
    border-color 0.25s cubic-bezier(0.4, 0, 0.2, 1),
    box-shadow 0.25s cubic-bezier(0.4, 0, 0.2, 1),
    transform 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
```

#### 输入框聚焦效果
```css
input:focus,
select:focus {
  outline: none;
  border-color: var(--male);
  box-shadow: 
    0 0 0 3px var(--male-glow),
    0 4px 12px rgba(86, 167, 187, 0.15);
}

input:focus[data-type="female"],
select:focus[data-type="female"] {
  border-color: var(--female);
  box-shadow: 
    0 0 0 3px var(--female-glow),
    0 4px 12px rgba(231, 127, 103, 0.15);
}
```

#### 按钮悬停效果
```css
button.primary {
  background: linear-gradient(135deg, #e88a6d 0%, #d4666e 100%);
  transform: translateY(-1px);
  box-shadow: 
    0 8px 24px rgba(212, 102, 110, 0.3),
    0 2px 8px rgba(212, 102, 110, 0.2);
}

button.primary:hover {
  transform: translateY(-2px);
  box-shadow: 
    0 12px 32px rgba(212, 102, 110, 0.35),
    0 4px 12px rgba(212, 102, 110, 0.25);
}

button.primary:active {
  transform: translateY(0);
}
```

### 4.3 呼吸灯效果（异色目标）
```css
@keyframes shimmer {
  0%, 100% { 
    box-shadow: 0 0 8px var(--shiny-glow);
  }
  50% { 
    box-shadow: 0 0 20px var(--shiny-glow), 0 0 40px rgba(245, 205, 121, 0.2);
  }
}

.stat.highlight strong {
  animation: shimmer 2s ease-in-out infinite;
  color: #c9a227;
}
```

---

## 五、响应式断点设计

### 5.1 断点定义
```css
/* 大桌面 */
@media (min-width: 1400px) {
  .layout {
    grid-template-columns: 380px 1fr 1fr;
  }
}

/* 桌面 */
@media (min-width: 1100px) and (max-width: 1399px) {
  .layout {
    grid-template-columns: 380px 1fr;
  }
}

/* 平板 */
@media (min-width: 768px) and (max-width: 1099px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .results-top {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
}

/* 手机 */
@media (max-width: 767px) {
  .shell {
    padding: 16px 12px;
  }
  .layout {
    grid-template-columns: 1fr;
  }
}
```

### 5.2 滚动条美化
```css
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: rgba(45, 62, 69, 0.05);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb {
  background: rgba(45, 62, 69, 0.15);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(45, 62, 69, 0.25);
}
```

---

## 六、DOM 节点兼容性清单

### 6.1 必须保留的 ID 和 Class

| 类型 | 节点 ID/Class | 用途 |
|------|--------------|------|
| Input | `#maleCount` | 雄性数量 |
| Input | `#femaleCount` | 雌性数量 |
| Input | `#nestCount` | 小窝总数 |
| Select | `#targetPriority` | 目标偏好 |
| Button | `#solveButton` | 计算按钮 |
| Button | `#presetButton` | 演示库存按钮 |
| Div | `#progressPanel` | 进度面板 |
| Div | `#progressFill` | 进度条填充 |
| Div | `#progressMeta` | 进度元信息 |
| Div | `#status` | 状态显示 |
| Div | `#overview` | 方案摘要 |
| Select | `#solutionSelect` | 方案选择 |
| Div | `#solutionNote` | 方案备注 |
| Div | `#stats` | 统计块 |
| Div | `#inventoryBody` | 库存表格 body |
| SVG | `#board` | SVG 画布 |
| Table | `#nestTableBody` | 巢穴明细 body |
| Div | `#pairList` | 配对列表 |

---

## 七、实现优先级

### 第一阶段：核心布局重构
1. 重构 HTML 结构，实现三栏布局
2. 实现响应式断点
3. 迁移 Stats 和 Solution-Picker 到左侧

### 第二阶段：视觉美化
1. 应用毛玻璃效果
2. 实现主题色彩
3. 添加微交互动画

### 第三阶段：细节优化
1. 滚动条美化
2. 移动端适配优化
3. 性能优化

---

## 八、验收标准

### 8.1 布局验收
- [ ] 宽屏下左侧控制面板充实，不再有过多空白
- [ ] 右侧内容分布均匀，不再是单列流水账
- [ ] Stats 和 Solution-Picker 成功迁移到左侧控制面板

### 8.2 视觉验收
- [ ] 毛玻璃效果正确应用
- [ ] 雄性/雌性主题色正确区分
- [ ] 输入框聚焦有柔和发光效果
- [ ] 按钮有悬停动画

### 8.3 功能验收
- [ ] 所有 JS 事件监听器正常工作
- [ ] 计算按钮可以正常触发
- [ ] 库存表格可以正常编辑
- [ ] 方案选择器正常工作
- [ ] 响应式布局在各断点正常工作
