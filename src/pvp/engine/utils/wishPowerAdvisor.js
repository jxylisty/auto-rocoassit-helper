/**
 * 愿力冲击推荐器（纯规则计算，零人工维护数据）
 *
 * 机制口径（对齐 roco-cal will_power.py 与社区攻略）：
 * - 愿力基础威力 80，成功应对对方状态技能后按 200（即 80×2.5）结算
 * - 物攻/魔攻由精灵自身攻击/魔攻面板较高项决定
 * - 属性随血脉自选（18 系）；愿力属性 ≠ 自身属性时无本系 1.25 加成
 *
 * 评分模型：
 * score(W) = 反克收益 + 打击面收益 − 抵抗面惩罚
 * 1. 反克收益：找出"打我方 >1 倍"的威胁属性集合，W 克制其中之一即高收益（实战中对手大概率带克制你的属性）
 * 2. 打击面收益：对当前全精灵池，W 能压制（>1 倍）的比例——龙愿力仅克龙系所以垫底
 * 3. 抵抗面惩罚：对当前全精灵池，W 被抵抗（<1 倍）的比例
 */
import { typeEffectChart, normalizeAttr, normalizeAttrList, getAttrMultiplier } from '../data/config/typeChart.js'
import { petDetail } from '../data/pet/pet_detail.js'
import { calculateDamageFull } from './pvpDamageEngine.js'

const WISH_BASE_POWER = 80
const WISH_RESPOND_POWER = 200

/** 18 系愿力属性（与 roco-cal WILLPOWER_ELEMENTS 一致） */
export const WISH_ELEMENTS = Object.keys(typeEffectChart)

/** 精灵池属性组合（主形态），构建一次缓存 */
let poolCache = null
function typePool() {
  if (poolCache) return poolCache
  const pool = []
  for (const variants of Object.values(petDetail)) {
    if (!Array.isArray(variants) || !variants.length) continue
    const types = normalizeAttrList(variants[0].type || [])
    if (types.length) pool.push(types)
  }
  poolCache = pool
  return pool
}

/**
 * 打我方精灵的威胁属性集合（倍率 >1 的全部攻击属性）
 */
export function threatTypesTo(myAttrs = []) {
  const defense = normalizeAttrList(myAttrs)
  if (!defense.length) return []
  return WISH_ELEMENTS.filter((atk) => getAttrMultiplier(atk, defense) > 1)
}

/**
 * 愿力属性对我方的完整分析（按分数降序）
 * @param {Object} pet 精灵（需 types）
 * @returns {Array<{attr, score, counterThreats, strongCount, resistedCount, total, strongShare, resistedShare, reasons}>}
 */
export function analyzeWishOptions(pet) {
  const myTypes = normalizeAttrList((pet && pet.types) || [])
  if (!myTypes.length) return []
  const threats = threatTypesTo(myTypes)
  const pool = typePool()

  const rows = WISH_ELEMENTS.map((wish) => {
    // 1. 反克：该愿力克制哪些"打我"的威胁属性
    const counterThreats = threats.filter((t) => getAttrMultiplier(wish, [t]) > 1)

    // 2/3. 全池打击面
    let strongCount = 0
    let resistedCount = 0
    for (const types of pool) {
      const mult = getAttrMultiplier(wish, types)
      if (mult > 1) strongCount += 1
      else if (mult < 1) resistedCount += 1
    }
    const total = pool.length || 1
    const strongShare = strongCount / total
    const resistedShare = resistedCount / total

    const score = counterThreats.length * 22 + strongShare * 100 * 0.9 - resistedShare * 100 * 0.8

    const reasons = []
    if (counterThreats.length) {
      reasons.push(`反克打你的 ${counterThreats.join('/')} 系`)
    }
    reasons.push(`压制全池 ${strongCount} 只（${Math.round(strongShare * 100)}%）`)
    if (resistedCount) reasons.push(`被 ${resistedCount} 只抵抗`)

    return {
      attr: wish,
      score: Math.round(score * 10) / 10,
      counterThreats,
      strongCount,
      resistedCount,
      total,
      strongShare,
      resistedShare,
      reasons
    }
  })

  return rows.sort((a, b) => b.score - a.score)
}

/**
 * 愿力伤害预估
 * @param {Object} params
 * @returns {{damage, skillType, attrMultiplier, sameTypeBonus, power}}
 */
export function estimateWishDamage({
  wishAttr,
  respond = false,
  myPet,
  myPanel,
  defender,
  defenderPanel,
  hits = 1
}) {
  const myTypes = normalizeAttrList((myPet && myPet.types) || [])
  const defTypes = normalizeAttrList((defender && defender.types) || [])
  // 物/魔走自身较高攻
  const attack = Number(myPanel && myPanel.attack) || 0
  const mattack = Number(myPanel && myPanel.mattack) || 0
  const skillType = mattack > attack ? '魔攻' : '物攻'
  const power = respond ? WISH_RESPOND_POWER : WISH_BASE_POWER
  const result = calculateDamageFull({
    attackerPanel: myPanel,
    defenderPanel: defenderPanel,
    skillPower: power,
    skillType,
    skillAttr: wishAttr,
    attackerAttrs: myTypes,
    defenderAttrs: defTypes,
    hits,
    skipAttrAndStab: false
  })
  return {
    damage: result.damage,
    skillType,
    attrMultiplier: result.attrMultiplier,
    sameTypeBonus: result.sameTypeBonus,
    power
  }
}

export default {
  WISH_ELEMENTS,
  threatTypesTo,
  analyzeWishOptions,
  estimateWishDamage
}
