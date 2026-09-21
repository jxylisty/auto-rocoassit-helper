/**
 * PVP 伤害计算回归测试
 * 运行: node scripts/run-pvp-breakpoint-tests.mjs
 *
 * 覆盖: 克制表口径、面板截断顺序、连击、伤害下限、满配配置
 */
import {
  getAttrMultiplier,
  calculatePanelValue,
  calculateAllPanels,
  calculateDamageFull,
  normalizeBattleSkill,
  starfallPowerForStacks,
  calculateStarfallDamage,
  getDynamicPowerRule,
  resolveStatDiffTierPower,
  canActBeforeEnemy
} from '../utils/pvpDamageEngine.js'
import { buildOpponentFullConfig } from '../utils/buildOpponentFullConfig.js'
import { buildSuggestedIvs } from '../utils/buildSuggestedIvs.js'

// 参考实现：项目规定的面板口径（先截断基础面板 → 乘性格 → 加星级裸加成）
// 独立于引擎实现，用于交叉验证；不 import game_math.js 是因为它引入了 JSON（Node 需要 import attribute）
const NATURE_KEY = { '生命': 'hp', '物攻': 'attack', '魔攻': 'mattack', '物防': 'defense', '魔防': 'mdefense', '速度': 'speed' }

function referencePanel(raceValue, ivInput, level, star, attrKey, natureUpName, natureDownName) {
  const iv = Math.max(0, Math.min(10, Number(ivInput) || 0)) * (star + 1)
  const race = Number(raceValue) || 0
  const base = race * 0.5 + iv * 0.25 + 10
  const growth = attrKey === 'hp' ? (race + iv * 0.5) * 0.02 + 1 : (race + iv * 0.5) * 0.01
  const raw = base + level * growth
  let mod = 1
  if (NATURE_KEY[natureUpName] === attrKey) mod = 1.2
  else if (NATURE_KEY[natureDownName] === attrKey) mod = 0.9
  // 基础面板四舍五入（对齐 roco-cal normal_round = floor(x+0.5)）
  return Math.round(Math.floor(raw + 0.5) * mod + 0.0000001) + (attrKey === 'hp' ? star * 20 : star * 10)
}

let passed = 0
let failed = 0

function assertEqual(actual, expected, label) {
  const ok = actual === expected
  if (ok) {
    passed += 1
    console.log(`  ✅ ${label}`)
  } else {
    failed += 1
    console.error(`  ❌ ${label}: 期望 ${expected}, 实际 ${actual}`)
  }
}

function assertClose(actual, expected, label, eps = 1e-9) {
  const ok = Math.abs(actual - expected) <= eps
  if (ok) {
    passed += 1
    console.log(`  ✅ ${label}`)
  } else {
    failed += 1
    console.error(`  ❌ ${label}: 期望 ${expected}, 实际 ${actual}`)
  }
}

function assertTrue(value, label) {
  if (value) {
    passed += 1
    console.log(`  ✅ ${label}`)
  } else {
    failed += 1
    console.error(`  ❌ ${label}`)
  }
}

console.log('\n== 克制表（data/config/typeChart.js 唯一来源） ==')
assertEqual(getAttrMultiplier('冰', ['地']), 2, '冰 打 地 = 2 倍')
assertEqual(getAttrMultiplier('冰', ['地系']), 2, '冰 打 地系(带系后缀) = 2 倍')
assertEqual(getAttrMultiplier('电', ['地']), 0.5, '电 打 地 = 0.5 倍')
assertEqual(getAttrMultiplier('地', ['火']), 2, '地 打 火 = 2 倍')
assertEqual(getAttrMultiplier('幽', ['光']), 2, '幽 打 光 = 2 倍')
assertEqual(getAttrMultiplier('恶', ['毒']), 2, '恶 打 毒 = 2 倍')
assertEqual(getAttrMultiplier('翼', ['草', '虫']), 3, '翼 打 草+虫 = 双克制 3 倍')
assertEqual(getAttrMultiplier('草', ['火', '龙']), 1 / 4, '草 打 火+龙 = 双抵抗 1/4')
assertEqual(getAttrMultiplier('草', ['火', '水']), 1, '草 打 火(抗)+水(克) = 1 倍')
assertEqual(getAttrMultiplier('火', ['水', '地']), 1 / 4, '火 打 水+地 = 双抵抗 1/4')
assertEqual(getAttrMultiplier('地', ['翼', '草', '虫']), 0.5, '混合 1克+2抗 = 2×0.5×0.5 = 0.5（连乘口径）')
assertEqual(getAttrMultiplier('不存在属性', ['火']), 1, '未知属性返回 1 倍')

console.log('\n== 面板公式：引擎与规范口径一致（先截断再乘性格） ==')
{
  const engineSpeed = calculatePanelValue({
    raceValue: 97, inputIv: 10, level: 60, star: 5,
    attrKey: 'speed', natureUp: '速度', natureDown: '物攻'
  })
  const refSpeed = referencePanel(97, 10, 60, 5, 'speed', '速度', '物攻')
  assertEqual(engineSpeed, refSpeed, `引擎速度面板(${engineSpeed}) === 参考值(${refSpeed})`)

  const engineSpeedEn = calculatePanelValue({
    raceValue: 97, inputIv: 10, level: 60, star: 5,
    attrKey: 'speed', natureUp: 'speed', natureDown: 'attack'
  })
  assertEqual(engineSpeedEn, engineSpeed, '引擎英文性格键与中文性格名结果一致')

  // 截断顺序验证：若先乘性格再截断，会得到不同结果
  const race = 113 // 选择一个截断顺序会产生差异的种族值
  const wrongOrder = Math.round(Math.floor((race * 0.5 + 60 * 0.25 + 10 + 60 * ((race + 60 * 0.5) * 0.01)) * 1.2)) + 50
  const rightOrder = referencePanel(race, 10, 60, 5, 'attack', '物攻', '魔攻')
  const engineAttack = calculatePanelValue({
    raceValue: race, inputIv: 10, level: 60, star: 5,
    attrKey: 'attack', natureUp: '物攻', natureDown: '魔攻'
  })
  assertEqual(engineAttack, rightOrder, `引擎物攻面板按先截断口径(${engineAttack})`)
  if (wrongOrder !== rightOrder) {
    console.log(`  ℹ️ 该用例下两种截断顺序结果不同（错误顺序=${wrongOrder}），测试有效`)
  }

  const hpPanel = calculatePanelValue({
    raceValue: 100, inputIv: 10, level: 60, star: 5,
    attrKey: 'hp', natureUp: '生命', natureDown: '无'
  })
  assertEqual(hpPanel, referencePanel(100, 10, 60, 5, 'hp', '生命', '无'), 'HP 面板与参考口径一致')
  assertTrue(Number.isInteger(hpPanel), `无 BUFF 面板应为整数(${hpPanel})`)
}

console.log('\n== 连击 ==')
{
  const attacker = { attack: 400, mattack: 400, defense: 200, mdefense: 200, hp: 1500, speed: 100 }
  const defender = { attack: 100, mattack: 100, defense: 150, mdefense: 150, hp: 1200, speed: 90 }
  const base = calculateDamageFull({
    attackerPanel: attacker, defenderPanel: defender,
    skillPower: 90, skillType: '物攻', skillAttr: '普通',
    attackerAttrs: ['普通'], defenderAttrs: ['普通'], hits: 1
  })
  const multi = calculateDamageFull({
    attackerPanel: attacker, defenderPanel: defender,
    skillPower: 90, skillType: '物攻', skillAttr: '普通',
    attackerAttrs: ['普通'], defenderAttrs: ['普通'], hits: 5
  })
  assertClose(multi.damage, base.damage * 5, '5 连击总伤害 = 单发 × 5')

  const skill = normalizeBattleSkill({ name: '测试', type: '物攻', power: 25, describe: '攻击敌方精灵，5连击。' })
  assertEqual(skill.baseHits, 5, '从描述解析 5 连击')
  const skill2 = normalizeBattleSkill({ name: '测试2', type: '物攻', power: 90, describe: '对敌方造成伤害。' })
  assertEqual(skill2.baseHits, 1, '无连击描述默认 1 击')
}

console.log('\n== 伤害下限与修饰符 ==')
{
  const attacker = { attack: 10, mattack: 10, defense: 999, mdefense: 999, hp: 100, speed: 1 }
  const defender = { attack: 1, mattack: 1, defense: 9999, mdefense: 9999, hp: 99999, speed: 1 }
  const result = calculateDamageFull({
    attackerPanel: attacker, defenderPanel: defender,
    skillPower: 1, skillType: '物攻', skillAttr: '普通',
    attackerAttrs: ['普通'], defenderAttrs: ['普通'], hits: 2, defenseReduction: 0.5
  })
  assertTrue(result.damage >= 1, `极端低伤害最终钳位 >= 1（实际 ${result.damage}）`)

  const buff = calculateDamageFull({
    attackerPanel: { attack: 400, mattack: 400, defense: 200, mdefense: 200, hp: 1500, speed: 100 },
    defenderPanel: { attack: 1, mattack: 1, defense: 150, mdefense: 150, hp: 1200, speed: 1 },
    skillPower: 90, skillType: '物攻', skillAttr: '普通',
    attackerAttrs: ['普通'], defenderAttrs: ['普通'],
    powerBuff: 1.5, defenseReduction: 0.3
  })
  const plain = calculateDamageFull({
    attackerPanel: { attack: 400, mattack: 400, defense: 200, mdefense: 200, hp: 1500, speed: 100 },
    defenderPanel: { attack: 1, mattack: 1, defense: 150, mdefense: 150, hp: 1200, speed: 1 },
    skillPower: 90, skillType: '物攻', skillAttr: '普通',
    attackerAttrs: ['普通'], defenderAttrs: ['普通']
  })
  assertClose(buff.damage, plain.damage * 1.5 * 0.7, '增伤50% × 减伤30% 为乘法叠加')
}

console.log('\n== 满配配置 ==')
{
  const pet = { race: { hp: 100, attack: 95, mattack: 47, defense: 67, mdefense: 42, speed: 97 } }
  const physical = buildOpponentFullConfig(pet, { skillType: '物攻' })
  assertEqual(physical.natureUp, '物攻', '物理技能满配性格提升物攻')
  assertEqual(physical.natureDown, '魔攻', '物理技能满配性格降低魔攻')
  assertEqual(physical.level, 60, '满配默认 60 级')
  assertEqual(physical.star, 5, '满配默认 5 星')
  const highIvCount = Object.values(physical.ivs).filter((v) => v > 0).length
  assertEqual(highIvCount, 3, '满配个体值为三项 10')
  assertTrue(Object.values(physical.ivs).every((v) => v === 0 || v === 10), '个体值只含 0 或 10')

  const magic = buildOpponentFullConfig(pet, { skillType: '魔攻' })
  assertEqual(magic.natureUp, '魔攻', '魔法技能满配性格提升魔攻')
  assertEqual(magic.ivs.mattack, 10, '魔法满配魔攻个体 10')
  assertEqual(magic.ivs.attack, 0, '魔法满配物攻（性格下降项）个体为 0')
}

console.log('\n== 伤害常量（对齐 roco-cal） ==')
{
  const attacker = { attack: 410, mattack: 200, defense: 100, mdefense: 100, hp: 1000, speed: 1 }
  const defender = { attack: 100, mattack: 100, defense: 200, mdefense: 200, hp: 1000, speed: 1 }
  const result = calculateDamageFull({
    attackerPanel: attacker, defenderPanel: defender,
    skillPower: 100, skillType: '物攻', skillAttr: '普通',
    attackerAttrs: ['普通'], defenderAttrs: ['普通']
  })
  // 手工复算: 410/200 × ((60*0.45+10)/41) × 100 × 1.25(本系) = 2.05 × 0.90244 × 125 ≈ 231.25
  const expected = (410 / 200) * ((60 * 45 / 100 + 10) / 41) * 100 * 1.25
  assertClose(result.damage, expected, `伤害 = 攻/防 × 常量((lv*0.45+10)/41) × 威力 × 本系（${result.damage.toFixed(2)}）`)
}

console.log('\n== 愿力冲击推荐（wishPowerAdvisor） ==')
{
  const { analyzeWishOptions, threatTypesTo, estimateWishDamage, WISH_ELEMENTS } = await import('../utils/wishPowerAdvisor.js')

  assertEqual(WISH_ELEMENTS.length, 18, '愿力属性共 18 系')

  // 火系精灵：打它 >1 倍的威胁应含水/地（查表 火 weak 水地）
  const firePet = { types: ['火'] }
  const threats = threatTypesTo(['火'])
  assertTrue(threats.includes('水') && threats.includes('地'), `火系威胁集合含水/地（实际: ${threats.join(',')}）`)

  const options = analyzeWishOptions(firePet)
  assertTrue(options.length === 18, '返回全部 18 系分析')
  // 反克验证：电愿力克制水（打火系的威胁），应有反克命中
  const electric = options.find((o) => o.attr === '电')
  assertTrue(electric.counterThreats.includes('水'), '电愿力反克威胁属性"水"')
  assertTrue(electric.score > 0, `电愿力分数为正（${electric.score}）`)

  // 龙愿力应排在低位（仅克龙、被机械抵抗）
  const dragon = options.find((o) => o.attr === '龙')
  const rank = options.findIndex((o) => o.attr === '龙')
  assertTrue(rank >= 12, `龙愿力排名靠后（第 ${rank + 1} 位）`)
  assertTrue(dragon.strongCount <= 30, `龙愿力压制面小（${dragon.strongCount} 只）`)

  // 推荐首位应有理由文案
  assertTrue(options[0].reasons.length >= 1 && options[0].reasons[0].length > 0, 'Top1 推荐带理由')

  // 伤害预估：物/魔走较高攻；应对 200 威力 = 基础 80 的 2.5 倍
  const myPet = { types: ['火'] }
  const myPanel = { attack: 300, mattack: 400, defense: 100, mdefense: 100, hp: 1000, speed: 1 }
  const defender = { types: ['水', '翼'] }
  const defPanel = { attack: 100, mattack: 100, defense: 150, mdefense: 150, hp: 1000, speed: 1 }
  const base = estimateWishDamage({ wishAttr: '电', respond: false, myPet, myPanel: { ...myPanel, hp: 1000 }, defender, defenderPanel: defPanel })
  assertEqual(base.skillType, '魔攻', '魔攻较高时愿力走魔攻')
  const respond = estimateWishDamage({ wishAttr: '电', respond: true, myPet, myPanel: { ...myPanel, hp: 1000 }, defender, defenderPanel: defPanel })
  assertClose(respond.damage, base.damage * 2.5, '应对状态伤害 = 基础 × 2.5')
  // 电打水+翼 = 2×2 = 双克 (1+1+1)=... 电→水=2, 电→翼=2 → 连乘口径 (1+2)=3
  assertEqual(base.attrMultiplier, 3, '电愿力打 水+翼 = 三倍（1+2 个克制）')
}

console.log('\n== 星陨印记引爆（S4：威力 = 层数² + 24×层数 − 24，roco-cal 拟合口径） ==')
{
  assertEqual(starfallPowerForStacks(0), 0, '0 层不产生附加威力')
  assertEqual(starfallPowerForStacks(1), 1, '1 层威力 = 1')
  assertEqual(starfallPowerForStacks(2), 28, '2 层威力 = 2²+48−24 = 28')
  assertEqual(starfallPowerForStacks(10), 316, '10 层威力 = 316')
  assertEqual(starfallPowerForStacks(20), 856, '20 层威力 = 856')

  const attacker = { attack: 400, mattack: 200, defense: 100, mdefense: 100, hp: 1000, speed: 1 }
  const defender = { attack: 100, mattack: 100, defense: 250, mdefense: 250, hp: 1000, speed: 1 }

  // 物攻技能触发：无本系加成，按幻系独立查克制，攻防取物攻/物防口径
  const sf = calculateStarfallDamage({
    attackerPanel: attacker, defenderPanel: defender,
    skillType: '物攻', skillAttr: '火', stacks: 2, defenderAttrs: ['普通']
  })
  assertTrue(sf.triggered, '非幻系攻击触发引爆')
  const expected = (400 / 250) * ((60 * 45 / 100 + 10) / 41) * 28 * getAttrMultiplier('幻', ['普通'])
  assertClose(sf.damage, expected, '附加伤害 = 物攻/物防 × 常量 × 28 × 幻系克制（无本系）')

  const blocked = calculateStarfallDamage({
    attackerPanel: attacker, defenderPanel: defender,
    skillType: '魔攻', skillAttr: '幻', stacks: 10, defenderAttrs: ['普通']
  })
  assertTrue(!blocked.triggered && blocked.blocked, '幻系技能攻击不触发引爆')
  assertEqual(blocked.damage, 0, '被拦阻时附加伤害为 0')

  const none = calculateStarfallDamage({
    attackerPanel: attacker, defenderPanel: defender,
    skillType: '物攻', skillAttr: '火', stacks: 0, defenderAttrs: ['普通']
  })
  assertTrue(!none.triggered, '0 层不触发')

  // 魔攻技能触发走魔攻/魔防口径
  const magic = calculateStarfallDamage({
    attackerPanel: attacker, defenderPanel: defender,
    skillType: '魔攻', skillAttr: '地', stacks: 5, defenderAttrs: ['普通']
  })
  const expectedMagic = (200 / 250) * ((60 * 45 / 100 + 10) / 41) * 121 * getAttrMultiplier('幻', ['普通'])
  assertClose(magic.damage, expectedMagic, '魔攻触发时取魔攻/魔防口径（5 层威力 121）')
}

console.log('\n== 动态威力分档（鸣沙陷阱=物防差 / 闪击=速度差，S4 现行表） ==')
{
  const mingsha = getDynamicPowerRule('鸣沙陷阱')
  const shanji = getDynamicPowerRule('闪击')
  assertTrue(!!mingsha && mingsha.stat === 'defense' && mingsha.base === 60, '鸣沙陷阱规则: 物防差 / 基础 60')
  assertTrue(!!shanji && shanji.stat === 'speed' && shanji.base === 60, '闪击规则: 速度差 / 基础 60')
  assertEqual(getDynamicPowerRule('不存在的技能'), null, '未知技能无规则')

  // 全档边界（S2 起满档门槛 136→271，现行 ≥271 → 200 封顶）
  const cases = [
    [-5, 60], [0, 60], [1, 80], [30, 80], [31, 100], [60, 100], [61, 120], [90, 120],
    [91, 140], [120, 140], [121, 150], [150, 150], [151, 160], [180, 160], [181, 170],
    [210, 170], [211, 180], [240, 180], [241, 190], [270, 190], [271, 200], [999, 200]
  ]
  cases.forEach(([diff, power]) => {
    const resolved = resolveStatDiffTierPower(mingsha, diff)
    assertEqual(resolved.power, power, `物防差 ${diff} → 威力 ${power}`)
  })
  assertEqual(resolveStatDiffTierPower(shanji, 300).power, 200, '速度差 300 → 威力 200（封顶）')
}

console.log('\n== 先后手判定（S4 同速随机） ==')
{
  const tie = canActBeforeEnemy({
    myPanel: { speed: 200 }, enemyPanel: { speed: 200 },
    selectedSkill: {}, enemySelectedSkill: {}
  })
  assertEqual(tie.result, 'tie', '同速返回 tie')
  assertTrue(/随机/.test(tie.reason), 'tie 文案标注同速随机（2026-09-10 版本规则）')

  const prio = canActBeforeEnemy({
    myPanel: { speed: 100 }, enemyPanel: { speed: 300 },
    selectedSkill: { priority: 1 }, enemySelectedSkill: {}
  })
  assertEqual(prio.result, true, '先制值高无视速度差')

  const speedWin = canActBeforeEnemy({
    myPanel: { speed: 300 }, enemyPanel: { speed: 200 },
    selectedSkill: {}, enemySelectedSkill: {}
  })
  assertEqual(speedWin.result, true, '同先制下速度高者先手')
}

console.log(`\n结果: ${passed} 通过, ${failed} 失败\n`)
process.exit(failed ? 1 : 0)
