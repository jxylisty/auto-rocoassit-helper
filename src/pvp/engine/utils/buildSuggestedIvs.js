const NATURE_LABEL_TO_KEY = {
  '无': '无',
  '生命': 'hp',
  '物攻': 'attack',
  '魔攻': 'mattack',
  '物防': 'defense',
  '魔防': 'mdefense',
  '速度': 'speed'
}

const NATURE_KEY_TO_LABEL = {
  '无': '无',
  'hp': '生命',
  'attack': '物攻',
  'mattack': '魔攻',
  'defense': '物防',
  'mdefense': '魔防',
  'speed': '速度'
}

function getRaceNumber(race, key) {
  const value = Number(race?.[key] ?? 0)
  return Number.isFinite(value) ? value : 0
}

function buildSuggestedIvs(race = {}, natureUpInput = '无', natureDownInput = '无') {
  const natureUp = NATURE_LABEL_TO_KEY[natureUpInput] || natureUpInput
  const natureDown = NATURE_LABEL_TO_KEY[natureDownInput] || natureDownInput

  const next = {
    hp: 0,
    attack: 0,
    mattack: 0,
    defense: 0,
    mdefense: 0,
    speed: 0
  }

  const blocked = new Set()
  if (natureDown && natureDown !== '无') blocked.add(natureDown)

  const attackRace = getRaceNumber(race, 'attack')
  const mattackRace = getRaceNumber(race, 'mattack')
  const defenseRace = getRaceNumber(race, 'defense')
  const mdefenseRace = getRaceNumber(race, 'mdefense')

  let offenseKey = attackRace >= mattackRace ? 'attack' : 'mattack'
  if (blocked.has(offenseKey)) {
    offenseKey = offenseKey === 'attack' ? 'mattack' : 'attack'
  }

  let defenseKey = defenseRace >= mdefenseRace ? 'defense' : 'mdefense'
  if (blocked.has(defenseKey)) {
    defenseKey = defenseKey === 'defense' ? 'mdefense' : 'defense'
  }

  const speedValue = getRaceNumber(race, 'speed')
  const speedPriority = speedValue >= 95 ? 'high' : speedValue <= 70 ? 'low' : 'mid'

  const candidates = []
  const pushCandidate = (key) => {
    if (!key || key === '无' || blocked.has(key) || candidates.includes(key)) return
    candidates.push(key)
  }

  pushCandidate(natureUp)
  pushCandidate(offenseKey)
  if (speedPriority === 'high') pushCandidate('speed')
  pushCandidate('hp')
  if (speedPriority === 'mid') pushCandidate('speed')
  pushCandidate(defenseKey)

  candidates.slice(0, 3).forEach((key) => {
    next[key] = 10
  })

  if (natureUp && natureUp !== '无' && !blocked.has(natureUp)) {
    next[natureUp] = 10
  }
  if (natureDown && natureDown !== '无') {
    next[natureDown] = 0
  }

  return next
}

export {
  NATURE_LABEL_TO_KEY,
  NATURE_KEY_TO_LABEL,
  buildSuggestedIvs
}
