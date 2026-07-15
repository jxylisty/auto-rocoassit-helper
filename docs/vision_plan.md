# 视觉识别模块规划

## 当前识别目标

1. `damage_reader`
   作用：读取飘出的伤害数字。
   方案：固定 ROI + 二值化 + 单字符模板匹配。

2. `energy_reader`
   作用：读取当前能量值。
   方案：固定 ROI + 数字模板匹配。

3. `avatar_matcher`
   作用：根据敌方头像给出候选精灵。
   方案：头像 ROI + 模板相似度 Top-K。

4. `element_matcher`
   作用：识别属性图标，在头像不稳定时用于排除。
   方案：属性图标 ROI + 模板匹配。

5. `battle_detector`
   作用：只在战斗中开启高频识别，平时低频巡检。
   方案：检测左下角聚能图标和右下角战斗功能区图标。

## 目录约定

视觉资源统一放到 `data/vision`：

- `data/vision/digits`
  放 `0.png` 到 `9.png` 的数字模板。
- `data/vision/avatars`
  每个精灵头像一个模板，文件名建议直接用精灵唯一 ID。
- `data/vision/elements`
  每个属性图标一个模板，文件名建议用属性英文键，例如 `fire.png`。
- `data/vision/samples`
  存原始战斗截图，用于调 ROI 和做标注。
- `data/vision/battle/left`
  放左下角战斗图标模板，例如聚能图标。
- `data/vision/battle/right`
  放右下角战斗功能区模板，例如逃跑、背包、技能区图标。

## 训练建议

短期不训练整图 OCR，先做模板法。

推荐采样顺序：

1. 收集 50 到 100 张战斗截图。
2. 固定一套 ROI，先裁出：
   - 敌方头像
   - 敌方属性图标
   - 能量数字
   - 伤害数字
   - 左下角战斗图标
   - 右下角战斗功能区
3. 从裁剪结果中挑干净样本做模板。
4. 当模板法错误率高于可接受范围时，再补字符级小模型。

## 标注建议

如果后续要训练字符分类器，建议生成以下结构：

- `data/vision/train/digits/0`
- `data/vision/train/digits/1`
- `data/vision/train/digits/2`
- ...
- `data/vision/train/digits/9`

每张图只保留单个字符，不要整串数字直接喂分类器。

## 与伤害反推的衔接

视觉层只负责给出“候选观察值”，不要在识别层直接写死战斗逻辑。

推荐下游流程：

1. `avatar_matcher` 给出精灵候选集。
2. `element_matcher` 用属性过滤候选集。
3. `damage_reader` 给出实际伤害值。
4. `energy_reader` 给出能量状态。
5. 将这些结果交给伤害计算与反推模块做概率排序。

这样后面换模型或换模板时，不会影响推理层。
存储过程语法：使用 CREATE PROCEDURE 定义，通过 @ 符号声明输入/输出参数，通过 EXEC 命令调用。

触发器机制：触发器是特殊的存储过程，在执行 INSERT、UPDATE、DELETE 时由系统自动触发。AFTER 触发器在操作完成后触发；INSTEAD OF 触发器跳过触发语句转而执行触发器自身。

临时表机制：理解触发器执行过程中，系统自动在内存中创建的两个临时逻辑表 inserted（存放插入或更新后的新数据）和 deleted（存放删除或更新前的旧数据）。



SPJ 数据库模式：熟悉 $S$（供应商）、$P$（零件）、$J$（工程项目）及 $SPJ$（供应情况）四张表的字段含义和主外键关联关系 。