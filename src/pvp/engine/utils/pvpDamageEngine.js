import { PVP_RULES } from '../config/pvpRuleConfig.js'
import { normalizeAttr, normalizeAttrList, getAttrMultiplier } from '../data/config/typeChart.js'
import { dynamicPowerRules } from '../data/skill/dynamicPowerRules.js'

export { normalizeAttr, normalizeAttrList, getAttrMultiplier }

const DAMAGE_SKILL_TYPES = ['物攻', '魔攻']
const PANEL_BUFF_KEY_MAP = {
  attack: ['atkBuff', 'attackBuff'],
  mattack: ['matkBuff', 'mattackBuff'],
  defense: ['defBuff', 'defenseBuff'],
  mdefense: ['mdefBuff', 'mdefenseBuff'],
  speed: ['speedBuff'],
  hp: ['hpBuff']
}

function countChineseChars(text = '') {
  const matches = String(text).match(/[\u4e00-\u9fff]/g)
  return matches ? matches.length : 0
}

export function repairText(value = '') {
  const source = String(value ?? '')
  if (!source) return ''
  if (countChineseChars(source) > 0) return source
  if (typeof TextDecoder === 'undefined') return source

  try {
    const bytes = new Uint8Array(Array.from(source).map((char) => char.charCodeAt(0) & 0xff))
    const decoded = new TextDecoder('utf-8').decode(bytes)
    return countChineseChars(decoded) >= countChineseChars(source) ? decoded : source
  } catch (error) {
    return source
  }
}

function toNumber(value, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function parseLooseNumber(value, fallback = 0) {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  const text = repairText(value ?? '').trim()
  if (!text) return fallback
  const match = text.match(/-?\d+(?:\.\d+)?/)
  if (match) {
    const parsed = Number(match[0])
    return Number.isFinite(parsed) ? parsed : fallback
  }
  return toNumber(text, fallback)
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

function getPercentBuffMultiplier(attrKey, buffs = {}) {
  const keys = PANEL_BUFF_KEY_MAP[attrKey] || []
  const buffPercent = keys.reduce((total, key) => total + toNumber(buffs?.[key], 0), 0)
  return 1 + buffPercent / 100
}

// normalizeAttr / normalizeAttrList / getAttrMultiplier 统一来自 data/config/typeChart.js（见顶部 re-export）

// 性格名（中文）→ 属性键，兼容中英文两种传入
const NATURE_NAME_TO_KEY = {
  '生命': 'hp',
  '物攻': 'attack',
  '魔攻': 'mattack',
  '物防': 'defense',
  '魔防': 'mdefense',
  '速度': 'speed',
  hp: 'hp',
  attack: 'attack',
  mattack: 'mattack',
  defense: 'defense',
  mdefense: 'mdefense',
  speed: 'speed'
}

// 性格提升倍率随星级变化（与 game_math.js 口径一致，5星=1.2）
function natureUpBonus(star) {
  const s = toNumber(star, 0)
  return s === 0 ? 0 : s === 1 ? 0.12 : s === 2 ? 0.14 : s === 3 ? 0.16 : s === 4 ? 0.18 : 0.2
}

export function calculatePanelValue({
  raceValue,
  inputIv,
  level = PVP_RULES.level,
  star = PVP_RULES.star,
  attrKey,
  natureUp = null,
  natureDown = null,
  buffs = {}
}) {
  const actualIv = clamp(toNumber(inputIv, 0), 0, 10) * (toNumber(star, 0) + 1)
  const race = toNumber(raceValue, 0)
  const baseValue = race * 0.5 + actualIv * 0.25 + 10
  const growth = attrKey === 'hp'
    ? (race + actualIv * 0.5) * 0.02 + 1
    : (race + actualIv * 0.5) * 0.01

  const rawPanel = baseValue + toNumber(level, 0) * growth

  // 与 game_math.js 对齐：先截断基础面板，再乘性格系数，再加星级裸加成
  const natureUpKey = natureUp ? NATURE_NAME_TO_KEY[natureUp] || natureUp : ''
  const natureDownKey = natureDown ? NATURE_NAME_TO_KEY[natureDown] || natureDown : ''
  let natureMod = 1
  if (natureUpKey && natureUpKey === attrKey) natureMod = 1 + natureUpBonus(star)
  else if (natureDownKey && natureDownKey === attrKey) natureMod = PVP_RULES.nature.down

  // 基础面板四舍五入（对齐 roco-cal normal_round = floor(x+0.5)），再乘性格
  const preNaturePanel = Math.floor(rawPanel + 0.5)
  const postNaturePanel = Math.round(preNaturePanel * natureMod + 0.0000001)
  const starBonus = attrKey === 'hp' ? toNumber(star, 0) * 20 : toNumber(star, 0) * 10

  let panel = postNaturePanel + starBonus

  panel *= getPercentBuffMultiplier(attrKey, buffs)
  if (attrKey === 'speed') panel += toNumber(buffs?.speedFlat, 0)
  return panel
}

export function calculateAllPanels({
  race = {},
  ivs = {},
  level = PVP_RULES.level,
  star = PVP_RULES.star,
  natureUp = null,
  natureDown = null,
  buffs = {}
}) {
  return {
    hp: calculatePanelValue({ raceValue: race.hp, inputIv: ivs.hp, level, star, attrKey: 'hp', natureUp, natureDown, buffs }),
    attack: calculatePanelValue({ raceValue: race.attack, inputIv: ivs.attack, level, star, attrKey: 'attack', natureUp, natureDown, buffs }),
    mattack: calculatePanelValue({ raceValue: race.mattack, inputIv: ivs.mattack, level, star, attrKey: 'mattack', natureUp, natureDown, buffs }),
    defense: calculatePanelValue({ raceValue: race.defense, inputIv: ivs.defense, level, star, attrKey: 'defense', natureUp, natureDown, buffs }),
    mdefense: calculatePanelValue({ raceValue: race.mdefense, inputIv: ivs.mdefense, level, star, attrKey: 'mdefense', natureUp, natureDown, buffs }),
    speed: calculatePanelValue({ raceValue: race.speed, inputIv: ivs.speed, level, star, attrKey: 'speed', natureUp, natureDown, buffs })
  }
}

export function isDamageSkill(skill = {}) {
  const type = repairText(skill?.type || '').trim()
  return DAMAGE_SKILL_TYPES.includes(type) && toNumber(skill?.power, 0) > 0
}

function parseBaseHits(describe = '') {
  const text = repairText(describe || '')
  const match = text.match(/(?:^|[^\d])([1-6]|10)连击/)
  return match ? Math.max(1, Number(match[1] || 1)) : 1
}

const DYNAMIC_POWER_KEYWORDS = [
  '连击', '连续攻击', '2连击', '3连击', '4连击', '5连击', '6连击', '10连击',
  '威力提升', '威力增加', '威力提高',
  '根据', '基于',
  '速度', '双防', '双攻', '攻击', '防御', '魔攻', '魔防',
  '越高', '越低', '越多',
  '追加', '随机', '随机威力',
  '每次', '永久', '叠加', '递增',
  '生命', 'HP', '血量',
  '条件威力', '条件增伤'
]

export function isDynamicPowerSkill(skill = {}) {
  const describe = repairText(skill?.describe || '')
  const powerText = String(skill?.power || '')
  const name = repairText(skill?.name || '')

  if (DYNAMIC_POWER_KEYWORDS.some((kw) => describe.includes(kw))) {
    return true
  }

  if (/(?:^|[^\d])([2-9]|10)连击/.test(describe)) {
    return true
  }

  if (/(?:先于|若|如果|当).*?威力/.test(describe)) {
    return true
  }

  if (/^\d+技能威力/.test(powerText) && !/^\d+$/.test(powerText.replace('技能威力', ''))) {
    return true
  }

  if (name && /(?:扫尾|撕裂|贯穿|暴击)/.test(name)) {
    return true
  }

  return false
}

function parsePriority(describe = '') {
  const text = repairText(describe || '')
  const directMatch = text.match(/(?:先手|先制)\s*([+-]\d+)/)
  if (directMatch) return Number(directMatch[1] || 0)
  const altMatch = text.match(/(?:先手|先制)\s*(\d+)/)
  return altMatch ? Number(altMatch[1] || 0) : 0
}

function parseConditionalEffects(describe = '') {
  const text = repairText(describe || '')
  const effects = []

  const powerRegex = /(?:若|如果|当).*?(?:先于敌方攻击|先手攻击|先于敌方|先手).*?(?:威力|技能威力)\+(\d+)%/g
  let powerMatch = powerRegex.exec(text)
  while (powerMatch) {
    effects.push({
      type: 'powerBuff',
      conditionType: 'acts_before_enemy',
      value: 1 + Number(powerMatch[1] || 0) / 100,
      text: `先于敌方时威力 +${powerMatch[1]}%`
    })
    powerMatch = powerRegex.exec(text)
  }

  const beforeHitsMatch = text.match(/(?:若|如果|当).*?(?:先于敌方攻击|先手攻击|先于敌方|先手).*?(?:改为|变为|变成)?([1-6]|10)连击/)
  if (beforeHitsMatch) {
    effects.push({
      type: 'hitsOverride',
      conditionType: 'acts_before_enemy',
      value: Number(beforeHitsMatch[1] || 1),
      text: `条件连击：改为 ${beforeHitsMatch[1]} 连击`
    })
  }

  const doubleHitsMatch = text.match(/(?:若|如果|当).*?连击数翻倍/)
  if (doubleHitsMatch) {
    effects.push({
      type: 'hitsMultiplier',
      conditionType: 'state',
      value: 2,
      text: '条件连击：本次技能连击数翻倍'
    })
  }

  const hpDeltaMatch = text.match(/(?:若|如果|当).*?生命低于50%.*?连击数\+(\d+)/)
  if (hpDeltaMatch) {
    effects.push({
      type: 'hitsDelta',
      conditionType: 'hp_below_50',
      value: Number(hpDeltaMatch[1] || 0),
      text: `条件连击：生命低于50%时连击数 +${hpDeltaMatch[1]}`
    })
  }

  return effects
}

export function normalizeBattleSkill(skill = {}) {
  const name = repairText(skill?.name || '')
  const type = repairText(skill?.type || '')
  const attr = repairText(skill?.attr || '')
  const power = parseLooseNumber(skill?.power, 0)
  const consume = parseLooseNumber(skill?.consume, 0)
  const describe = repairText(skill?.describe || '')
  const skillType = repairText(skill?.skillType || skill?.skill_type || skill?.skilltype || '')
  const baseHits = parseBaseHits(describe)
  const priority = parsePriority(describe)
  const isQuick = /迅捷/.test(describe)
  const damageSkill = DAMAGE_SKILL_TYPES.includes(type) && power > 0
  const mechanicTags = []
  const isDynamic = isDynamicPowerSkill(skill)

  if (/连击/.test(describe)) mechanicTags.push('连击')
  if (/(?:先手|先制)\s*[+-]?\d+/.test(describe)) mechanicTags.push('先手')
  if (/迅捷/.test(describe)) mechanicTags.push('迅捷')
  if (/威力\+\d+%/.test(describe)) mechanicTags.push('条件威力')
  if (/连击数|多段/.test(describe)) mechanicTags.push('条件连击')
  if (/脱离/.test(describe)) mechanicTags.push('脱离')
  if (/减伤/.test(describe)) mechanicTags.push('减伤')
  if (/增效|强化|提升|增加/.test(describe)) mechanicTags.push('强化')
  if (/吸血|回复.*生命/.test(describe)) mechanicTags.push('吸血')
  if (/应对/.test(describe)) mechanicTags.push('应对')
  if (/传动|啮合传递/.test(describe)) mechanicTags.push('传动')

  return {
    name,
    type,
    attr,
    power,
    consume,
    describe,
    skillType,
    baseHits,
    priority,
    isQuick,
    isDynamic,
    isDamageSkill: damageSkill,
    mechanicTags: Array.from(new Set(mechanicTags)),
    conditionalEffects: parseConditionalEffects(describe)
  }
}

export function canActBeforeEnemy({
  myPanel = {},
  enemyPanel = {},
  selectedSkill = {},
  enemySelectedSkill = {}
}) {
  const myPriority = toNumber(selectedSkill?.priority, 0)
  const enemyPriority = toNumber(enemySelectedSkill?.priority, 0)
  const mySpeed = toNumber(myPanel?.speed, 0)
  const enemySpeed = toNumber(enemyPanel?.speed, 0)

  if (myPriority > enemyPriority) {
    return {
      result: true,
      reason: '我方技能先制值更高',
      compare: { myPriority, enemyPriority, mySpeed, enemySpeed }
    }
  }

  if (myPriority < enemyPriority) {
    return {
      result: false,
      reason: '敌方技能先制值更高',
      compare: { myPriority, enemyPriority, mySpeed, enemySpeed }
    }
  }

  if (mySpeed > enemySpeed) {
    return {
      result: true,
      reason: '双方先制相同，我方速度更高',
      compare: { myPriority, enemyPriority, mySpeed, enemySpeed }
    }
  }

  if (mySpeed < enemySpeed) {
    return {
      result: false,
      reason: '双方先制相同，敌方速度更高',
      compare: { myPriority, enemyPriority, mySpeed, enemySpeed }
    }
  }

  return {
    result: 'tie',
    reason: '双方先制和速度相同，同速随机先后（2026-09-10 版本规则）',
    compare: { myPriority, enemyPriority, mySpeed, enemySpeed }
  }
}

/**
 * 等级伤害常量：口径对齐 roco-cal damresult.py（60 级 ≈ 0.9024）
 */
export function damageConstant(level = PVP_RULES.level) {
  return (toNumber(level, PVP_RULES.level) * 45 / 100 + 10) / 41
}

export function calculateDamageFull({
  attackerPanel = {},
  defenderPanel = {},
  skillPower = 0,
  skillType = '',
  skillAttr = '',
  attackerAttrs = [],
  defenderAttrs = [],
  powerBuff = PVP_RULES.defaultScenario.powerBuff,
  weatherMod = PVP_RULES.defaultScenario.weatherMod,
  defenseReduction = PVP_RULES.defaultScenario.defenseReduction,
  level = PVP_RULES.level,
  hits = PVP_RULES.defaultScenario.hits,
  skipAttrAndStab = false
}) {
  const normalizedSkillType = repairText(skillType).trim()
  const isPhysical = normalizedSkillType === '物攻'
  const atkUsed = isPhysical ? toNumber(attackerPanel.attack, 1) : toNumber(attackerPanel.mattack, 1)
  const rawDefense = isPhysical ? toNumber(defenderPanel.defense, 1) : toNumber(defenderPanel.mdefense, 1)
  const defUsed = Math.max(1, rawDefense)
  const normalizedSkillAttr = normalizeAttr(skillAttr)
  const normalizedAttackerAttrs = normalizeAttrList(attackerAttrs)
  const normalizedDefenderAttrs = normalizeAttrList(defenderAttrs)
  const sameTypeBonus = skipAttrAndStab ? 1 : (normalizedAttackerAttrs.includes(normalizedSkillAttr) ? PVP_RULES.damage.sameTypeBonus : 1)
  const attrMultiplier = skipAttrAndStab ? 1 : getAttrMultiplier(normalizedSkillAttr, normalizedDefenderAttrs)
  const levelConst = damageConstant(level)
  const hitCount = Math.max(1, toNumber(hits, 1))
  const reductionMultiplier = 1 - clamp(toNumber(defenseReduction, 0), 0, 1)

  // 总伤害 = 攻/防 × 常量 × 有效威力 × 修饰，下限 1 在最终结果上钳位
  // 口径对齐 roco-cal：damage = effectivePower × atk × ((lv*0.45+10)/41) / defense × 减伤连乘
  const damage = Math.max(
    1,
    (atkUsed / defUsed) * levelConst * toNumber(skillPower, 0) * toNumber(powerBuff, 1)
      * sameTypeBonus * attrMultiplier * toNumber(weatherMod, 1)
      * hitCount * reductionMultiplier
  )

  return {
    damage,
    atkUsed,
    defUsed,
    sameTypeBonus,
    attrMultiplier,
    hits: hitCount,
    formulaParts: {
      attackRatio: atkUsed / defUsed,
      baseConstant: levelConst,
      skillPower: toNumber(skillPower, 0),
      powerBuff: toNumber(powerBuff, 1),
      sameTypeBonus,
      attrMultiplier,
      weatherMod: toNumber(weatherMod, 1),
      hits: hitCount,
      defenseReduction: clamp(toNumber(defenseReduction, 0), 0, 1),
      skillType: normalizedSkillType
    }
  }
}

/* ================================================================
 * 星陨印记引爆（S4 现行社区公式）
 * 附加威力 = 层数² + 24×层数 − 24（180sans/roco-cal 同步 S4 实现，
 * 与 NGA 2026-04 实测拟合互证）；用非幻系技能攻击持有者时引爆全部层数，
 * 按幻系独立结算克制、不吃本系加成，攻防取触发技能同类口径。
 * ================================================================ */
export function starfallPowerForStacks(stacks = 0) {
  const n = Math.max(0, Math.floor(toNumber(stacks, 0)))
  if (n <= 0) return 0
  return n * n + 24 * n - 24
}

export function calculateStarfallDamage({
  attackerPanel = {},
  defenderPanel = {},
  skillType = '',
  skillAttr = '',
  stacks = 0,
  defenderAttrs = [],
  powerBuff = 1,
  defenseReduction = 0,
  level = PVP_RULES.level
}) {
  const n = Math.max(0, Math.floor(toNumber(stacks, 0)))
  if (n <= 0) {
    return { stacks: 0, power: 0, damage: 0, attrMultiplier: 1, triggered: false, blocked: false, reason: '' }
  }
  if (normalizeAttr(skillAttr) === '幻') {
    // 现行规则：幻系技能攻击不触发星陨引爆
    return { stacks: n, power: 0, damage: 0, attrMultiplier: 1, triggered: false, blocked: true, reason: '幻系技能不触发星陨引爆' }
  }
  const power = starfallPowerForStacks(n)
  const isPhysical = repairText(skillType).trim() === '物攻'
  const atkUsed = isPhysical ? toNumber(attackerPanel.attack, 1) : toNumber(attackerPanel.mattack, 1)
  const defUsed = Math.max(1, isPhysical ? toNumber(defenderPanel.defense, 1) : toNumber(defenderPanel.mdefense, 1))
  const attrMultiplier = getAttrMultiplier('幻', normalizeAttrList(defenderAttrs))
  const levelConst = damageConstant(level)
  const reductionMultiplier = 1 - clamp(toNumber(defenseReduction, 0), 0, 1)
  // 引爆按单次攻击动作结算一次，不随连击数放大（对齐 roco-cal 的附加项口径）
  const damage = Math.max(
    1,
    (atkUsed / defUsed) * levelConst * power * toNumber(powerBuff, 1) * attrMultiplier * reductionMultiplier
  )
  return { stacks: n, power, damage, attrMultiplier, triggered: true, blocked: false, reason: '', isPhysical }
}

/* ================================================================
 * 动态威力技能 · 分档查表（鸣沙陷阱/闪击等，S4 现行分档）
 * 规则表：data/skill/dynamicPowerRules.js
 * ================================================================ */
export function getDynamicPowerRule(skillName = '') {
  const name = repairText(skillName).trim()
  if (!name) return null
  return dynamicPowerRules[name] || null
}

export function resolveStatDiffTierPower(rule, diff = 0) {
  if (!rule || rule.kind !== 'statDiffTier' || !Array.isArray(rule.tiers)) return null
  const value = toNumber(diff, 0)
  for (let i = 0; i < rule.tiers.length; i += 1) {
    const tier = rule.tiers[i]
    const min = tier.min === null || tier.min === undefined ? -Infinity : Number(tier.min)
    const max = tier.max === null || tier.max === undefined ? Infinity : Number(tier.max)
    if (value >= min && value <= max) {
      const bonus = toNumber(tier.bonus, 0)
      return {
        bonus,
        power: toNumber(rule.base, 0) + bonus,
        tierIndex: i,
        diff: value
      }
    }
  }
  return null
}

export default {
  repairText,
  normalizeAttr,
  normalizeAttrList,
  normalizeBattleSkill,
  calculatePanelValue,
  calculateAllPanels,
  getAttrMultiplier,
  isDamageSkill,
  canActBeforeEnemy,
  calculateDamageFull,
  starfallPowerForStacks,
  calculateStarfallDamage,
  getDynamicPowerRule,
  resolveStatDiffTierPower
}
