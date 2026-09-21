/**
 * 动态威力技能 · 分档规则表（S4 现行口径）
 *
 * 数据来源：
 *  - BWIKI 新站 nrc 技能页（wiki.biligame.com/nrc，2026-09-09 编辑，S4 数据）：
 *    鸣沙陷阱「物防比敌方越高，威力越高」/ 闪击「速度比敌方越高，威力越高」
 *  - GitHub 180sans/roco-cal skills_database（2026-09-16 同步 S4，skill_power_by_count
 *    = [60,80,100,120,140,150,160,170,180,190,200]）交叉验证
 *  - S2（2026-05-21）平衡调整：满档门槛由"高出 136"翻倍为"高出 271"，中间档同步翻倍
 *
 * kind = statDiffTier：实际威力 = base + bonus(diff)，diff = 自身面板 − 敌方面板
 * （对局内按含 buff 的实时面板判定；本表按计算器当前配置面板查档）
 * min/max 为 null 表示该档无下界/无上界。
 */
export const dynamicPowerRules = {
  '鸣沙陷阱': {
    kind: 'statDiffTier',
    stat: 'defense',
    statLabel: '物防差',
    base: 60,
    tiers: [
      { min: null, max: 0, bonus: 0 },
      { min: 1, max: 30, bonus: 20 },
      { min: 31, max: 60, bonus: 40 },
      { min: 61, max: 90, bonus: 60 },
      { min: 91, max: 120, bonus: 80 },
      { min: 121, max: 150, bonus: 90 },
      { min: 151, max: 180, bonus: 100 },
      { min: 181, max: 210, bonus: 110 },
      { min: 211, max: 240, bonus: 120 },
      { min: 241, max: 270, bonus: 130 },
      { min: 271, max: null, bonus: 140 }
    ]
  },
  '闪击': {
    kind: 'statDiffTier',
    stat: 'speed',
    statLabel: '速度差',
    base: 60,
    tiers: [
      { min: null, max: 0, bonus: 0 },
      { min: 1, max: 30, bonus: 20 },
      { min: 31, max: 60, bonus: 40 },
      { min: 61, max: 90, bonus: 60 },
      { min: 91, max: 120, bonus: 80 },
      { min: 121, max: 150, bonus: 90 },
      { min: 151, max: 180, bonus: 100 },
      { min: 181, max: 210, bonus: 110 },
      { min: 211, max: 240, bonus: 120 },
      { min: 241, max: 270, bonus: 130 },
      { min: 271, max: null, bonus: 140 }
    ]
  }
}

export default dynamicPowerRules
