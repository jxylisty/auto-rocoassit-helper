/**
 * 属性克制表（全项目唯一来源）
 * 所有克制倍率计算必须复用本模块，禁止在各处复制克制表。
 * 数据口径与属性克制页一致：strong=攻击克制，resist=攻击被抵抗，
 * defenseResist/weak 供属性克制关系图使用。
 */

const rawTypeEffectChart = {
  '普通': { strong: [], resist: ['地', '幽', '机械'], defenseResist: ['幽'], weak: ['武'] },
  '火': { strong: ['草', '冰', '虫', '机械'], resist: ['水', '地', '龙'], defenseResist: ['草', '冰', '虫', '萌', '机械'], weak: ['水', '地'] },
  '水': { strong: ['火', '地', '机械'], resist: ['草', '冰', '龙'], defenseResist: ['火', '机械'], weak: ['草', '电'] },
  '电': { strong: ['水', '翼'], resist: ['草', '地', '龙', '电'], defenseResist: ['电', '翼', '机械'], weak: ['地'] },
  '草': { strong: ['水', '光', '地'], resist: ['火', '龙', '毒', '虫', '翼', '机械'], defenseResist: ['水', '地', '电', '光'], weak: ['火', '冰', '毒', '虫', '翼'] },
  '冰': { strong: ['草', '地', '龙', '翼'], resist: ['火', '冰', '机械'], defenseResist: ['水', '冰', '光'], weak: ['火', '地', '武', '机械'] },
  '武': { strong: ['普通', '地', '冰', '恶', '机械'], resist: ['毒', '虫', '翼', '萌', '幽', '幻'], defenseResist: ['地', '虫', '恶'], weak: ['翼', '萌', '幻'] },
  '毒': { strong: ['草', '萌'], resist: ['地', '毒', '幽', '机械'], defenseResist: ['草', '毒', '虫', '武', '萌'], weak: ['地', '恶', '幻'] },
  '地': { strong: ['火', '冰', '电', '毒'], resist: ['草', '武'], defenseResist: ['普通', '火', '电', '毒', '翼'], weak: ['草', '冰', '水', '武', '机械'] },
  '翼': { strong: ['草', '虫', '武'], resist: ['地', '龙', '电', '机械'], defenseResist: ['草', '虫', '武'], weak: ['冰', '电'] },
  '萌': { strong: ['龙', '武', '恶'], resist: ['火', '毒', '机械'], defenseResist: ['虫', '武'], weak: ['毒', '恶', '机械'] },
  '虫': { strong: ['草', '恶', '幻'], resist: ['火', '毒', '武', '翼', '萌', '幽', '机械'], defenseResist: ['草', '武'], weak: ['火', '翼'] },
  '幽': { strong: ['光', '幽', '幻'], resist: ['普通', '恶'], defenseResist: ['普通', '毒', '虫', '武'], weak: ['光', '幽', '恶'] },
  '龙': { strong: ['龙'], resist: ['机械'], defenseResist: ['草', '火', '水', '电', '翼'], weak: ['冰', '龙', '萌'] },
  '恶': { strong: ['毒', '萌', '幽'], resist: ['光', '武', '恶'], defenseResist: ['幽', '恶'], weak: ['光', '虫', '武', '萌'] },
  '机械': { strong: ['地', '冰', '萌'], resist: ['火', '水', '电', '机械'], defenseResist: ['普通', '草', '冰', '龙', '毒', '虫', '翼', '萌', '机械', '幻'], weak: ['火', '水', '武'] },
  '光': { strong: ['幽', '恶'], resist: ['草', '冰'], defenseResist: ['恶', '幻'], weak: ['草', '幽'] },
  '幻': { strong: ['毒', '武'], resist: ['光', '机械', '幻'], defenseResist: ['武', '幻'], weak: ['虫', '幽'] }
}

const attrAliasMap = {
  '普通系': '普通',
  '草系': '草',
  '火系': '火',
  '水系': '水',
  '光系': '光',
  '地系': '地',
  '冰系': '冰',
  '龙系': '龙',
  '电系': '电',
  '毒系': '毒',
  '虫系': '虫',
  '武系': '武',
  '翼系': '翼',
  '恶系': '恶',
  '机械系': '机械',
  '萌系': '萌',
  '幻系': '幻'
}

export const typeEffectChart = rawTypeEffectChart

export function normalizeAttr(attr) {
  if (!attr) return ''
  return attrAliasMap[attr] || String(attr).replace(/系$/, '')
}

export function normalizeAttrList(attrs = []) {
  const list = Array.isArray(attrs) ? attrs : [attrs]
  return Array.from(new Set(list.map((item) => normalizeAttr(item)).filter(Boolean)))
}

/**
 * 攻击属性对防守方属性组合的克制倍率
 * 口径对齐社区验证项目 roco-cal（github.com/180sans/roco-cal）ele_advantage.py：
 * 每对攻/防独立查格（克制 2 / 抵抗 0.5），n 个克制相乘为 (1+n)（单克 2、双克 3），
 * 其余倍率直接连乘——双抵抗 = 0.5×0.5 = 0.25，克制+抵抗 = 2×0.5 = 1，
 * 混合情形如 1克+2抗 = 2×0.5×0.5 = 0.5。
 */
export function getAttrMultiplier(attackAttr, defenseAttrs = []) {
  const atkType = normalizeAttr(attackAttr)
  const chart = typeEffectChart[atkType]
  if (!chart) return 1

  let strongCount = 0
  let otherProduct = 1

  normalizeAttrList(defenseAttrs).forEach((defType) => {
    if (chart.strong.includes(defType)) {
      strongCount += 1
    } else if (chart.resist.includes(defType)) {
      otherProduct *= 0.5
    }
  })

  return (strongCount > 0 ? 1 + strongCount : 1) * otherProduct
}

// 属性图标文件名（英文，对应 static/static-web/icons/）。
// Android 打包不允许静态资源文件名含中文（会告警），故用英文命名 + 本映射。
const attrIconNameMap = {
  '普通': 'normal', '火': 'fire', '水': 'water', '电': 'electric', '草': 'grass',
  '冰': 'ice', '武': 'fighting', '毒': 'poison', '地': 'ground', '翼': 'flying',
  '萌': 'fairy', '虫': 'bug', '幽': 'ghost', '龙': 'dragon', '恶': 'dark',
  '机械': 'steel', '光': 'light', '幻': 'psychic'
}

// 根据属性中文名返回英文图标文件名（映射不到时回退为原中文名）
export function getAttrIconName(attr) {
  const type = normalizeAttr(attr)
  return attrIconNameMap[type] || type
}

export default {
  typeEffectChart,
  normalizeAttr,
  normalizeAttrList,
  getAttrMultiplier,
  getAttrIconName
}