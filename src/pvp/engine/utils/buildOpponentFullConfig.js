/**
 * 对手满配配置生成器
 *
 * "满配"口径：60 级 / 5 星 / 三项个体值 10（按最优分配）/ 性格提升主攻项、降低副攻项。
 * 用于"对方技能打我"的实时伤害评估，默认按最坏情况（对方输出拉满）计算。
 */
import { PVP_RULES } from '../config/pvpRuleConfig.js'
import { buildSuggestedIvs } from './buildSuggestedIvs.js'

/**
 * @param {Object} pet 精灵对象（需含 race；兼容 {detail: {race}} 结构）
 * @param {Object} options
 * @param {string} [options.skillType] 技能类型 '物攻' | '魔攻'，优先据此选择性格提升项
 * @param {string} [options.prefer] 强制指定提升项：'attack' | 'mattack'
 * @returns {{level:number, star:number, ivs:Object, natureUp:string, natureDown:string}}
 */
export function buildOpponentFullConfig(pet, options = {}) {
  const race = pet?.race || pet?.detail?.race || {}

  let preferKey = options.prefer
  if (!preferKey) {
    if (options.skillType === '魔攻') preferKey = 'mattack'
    else if (options.skillType === '物攻') preferKey = 'attack'
    else {
      const attack = Number(race.attack) || 0
      const mattack = Number(race.mattack) || 0
      preferKey = mattack >= attack ? 'mattack' : 'attack'
    }
  }

  const natureUp = preferKey === 'mattack' ? '魔攻' : '物攻'
  // 下降项选副攻：对输出型配置价值最低
  const natureDown = preferKey === 'mattack' ? '物攻' : '魔攻'

  return {
    level: PVP_RULES.level,
    star: PVP_RULES.star,
    ivs: buildSuggestedIvs(race, natureUp, natureDown),
    natureUp,
    natureDown
  }
}

export default {
  buildOpponentFullConfig
}
