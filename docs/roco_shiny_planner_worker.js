// 全局变量（等待数据加载后初始化）
let SPECIES = [];
let GROUP_ORDER = [];
let GROUP_MASK = {};
let SPECIES_BY_INDEX = [];
let SINGLE_SHINY_PERCENT_CENTI = 36;
let DOUBLE_SHINY_PERCENT_CENTI = 72;

// Worker 是否已经初始化
let isInitialized = false;
const pendingMessages = [];

// 加载 JSON 数据
async function loadSpeciesData() {
  try {
    const response = await fetch('./roco_species_data.json');
    if (!response.ok) {
      throw new Error('无法加载精灵数据');
    }
    const data = await response.json();
    
    SPECIES = data.SPECIES;
    GROUP_ORDER = data.GROUP_ORDER;
    SINGLE_SHINY_PERCENT_CENTI = data.SINGLE_SHINY_PERCENT_CENTI;
    
    GROUP_MASK = Object.fromEntries(GROUP_ORDER.map((group, index) => [group, 1 << index]));
    SPECIES_BY_INDEX = SPECIES.map((species, index) => ({
      ...species,
      index,
      label: species.aliases.length ? `${species.name}（${species.aliases.join(" / ")}）` : species.name,
      mask: species.groups.reduce((sum, group) => sum | GROUP_MASK[group], 0)
    }));
    
    isInitialized = true;
    
    // 处理待处理的消息
    while (pendingMessages.length > 0) {
      const event = pendingMessages.shift();
      handleMessage(event);
    }
    
    return true;
  } catch (error) {
    console.error('加载精灵数据失败:', error);
    return false;
  }
}

function getExpectedShinyPercentCenti(score) {
  return score.expectedShinyPercentCenti ?? (score.shinyChanceScore * SINGLE_SHINY_PERCENT_CENTI);
}

function getShinyUsage(score) {
  return score.shinyUsage ?? ((score.shinyMaleUsage || 0) + (score.shinyFemaleUsage || 0));
}

function popcount(value) {
  let count = 0;
  let current = value >>> 0;
  while (current) {
    current &= current - 1;
    count++;
  }
  return count;
}

function normalizeCells(cells) {
  const minX = Math.min(...cells.map(cell => cell.x));
  const minY = Math.min(...cells.map(cell => cell.y));
  return cells
    .map(cell => ({ x: cell.x - minX, y: cell.y - minY }))
    .sort((a, b) => a.y - b.y || a.x - b.x);
}

function serializeCells(cells) {
  return cells.map(cell => `${cell.x},${cell.y}`).join(";");
}

function canonical(cells) {
  const transforms = [
    ({ x, y }) => ({ x, y }),
    ({ x, y }) => ({ x: -x, y }),
    ({ x, y }) => ({ x, y: -y }),
    ({ x, y }) => ({ x: -x, y: -y }),
    ({ x, y }) => ({ x: y, y: x }),
    ({ x, y }) => ({ x: -y, y: x }),
    ({ x, y }) => ({ x: y, y: -x }),
    ({ x, y }) => ({ x: -y, y: -x })
  ];
  const keys = transforms.map(transform => serializeCells(normalizeCells(cells.map(transform))));
  keys.sort();
  return keys[0];
}

function cellsOverlap(a, b) {
  return Math.abs(a.x - b.x) < 2 && Math.abs(a.y - b.y) < 2;
}

function isLegalLayout(cells) {
  for (let i = 0; i < cells.length; i++) {
    for (let j = i + 1; j < cells.length; j++) {
      if (cellsOverlap(cells[i], cells[j])) {
        return false;
      }
    }
  }
  return true;
}

function hasEdge(a, b) {
  return Math.abs(a.x - b.x) + Math.abs(a.y - b.y) <= 5;
}

function scoreShape(cells) {
  let pairScore = 0;
  for (let i = 0; i < cells.length; i++) {
    for (let j = i + 1; j < cells.length; j++) {
      if (hasEdge(cells[i], cells[j])) {
        pairScore++;
      }
    }
  }
  const width = Math.max(...cells.map(cell => cell.x)) + 2;
  const height = Math.max(...cells.map(cell => cell.y)) + 2;
  return { pairScore, compactness: -(width * height), width, height };
}

function scorePartialLayout(cells) {
  const shape = scoreShape(cells);
  const { edges, adjacency } = buildEdges(cells);
  const degrees = adjacency.map(list => list.length).sort((a, b) => b - a);
  const degreeHead = degrees.slice(0, Math.min(4, degrees.length)).reduce((sum, value) => sum + value, 0);
  return {
    pairScore: shape.pairScore,
    degreeHead,
    compactness: shape.compactness,
    height: shape.height,
    width: shape.width
  };
}

function buildRowLayout(n, rowWidth, staggerStep = 0) {
  const width = Math.max(1, Math.min(n, rowWidth));
  const cells = [];
  for (let index = 0; index < n; index++) {
    const row = Math.floor(index / width);
    const col = index % width;
    const offset = staggerStep && (row % 2 === 1) ? staggerStep : 0;
    cells.push({ x: col * 2 + offset, y: row * 2 });
  }
  return normalizeCells(cells);
}

function buildColumnLayout(n, columnHeight, staggerStep = 0) {
  const height = Math.max(1, Math.min(n, columnHeight));
  const cells = [];
  for (let index = 0; index < n; index++) {
    const col = Math.floor(index / height);
    const row = index % height;
    const offset = staggerStep && (col % 2 === 1) ? staggerStep : 0;
    cells.push({ x: col * 2 + offset, y: row * 2 });
  }
  return normalizeCells(cells);
}

function generateStructuredLayouts(n) {
  if (n <= 0) {
    return [[]];
  }
  const widths = [...new Set([
    Math.ceil(Math.sqrt(n)),
    Math.max(2, Math.floor(Math.sqrt(n))),
    Math.max(2, Math.ceil(n / 2)),
    Math.max(3, Math.ceil(n / 3))
  ])];
  const heights = widths;
  const layouts = new Map();

  function add(cells) {
    const normalized = normalizeCells(cells);
    if (isLegalLayout(normalized)) {
      layouts.set(canonical(normalized), normalized);
    }
  }

  add([{ x: 0, y: 0 }]);
  for (const width of widths) {
    add(buildRowLayout(n, width, 0));
    add(buildRowLayout(n, width, 1));
  }
  for (const height of heights) {
    add(buildColumnLayout(n, height, 0));
    add(buildColumnLayout(n, height, 1));
  }
  add(buildRowLayout(n, n, 0));
  add(buildColumnLayout(n, n, 0));
  return [...layouts.values()];
}

function canAdd(point, points) {
  return !points.some(existing => cellsOverlap(existing, point)) &&
    points.some(existing => hasEdge(existing, point));
}

function potentialDegree(point, points) {
  return points.reduce((count, existing) => count + (hasEdge(existing, point) ? 1 : 0), 0);
}

function generateCandidatePositions(cells) {
  const next = new Map();
  for (const cell of cells) {
    for (let dx = -5; dx <= 5; dx++) {
      for (let dy = -5; dy <= 5; dy++) {
        if (dx === 0 && dy === 0) continue;
        const candidate = { x: cell.x + dx, y: cell.y + dy };
        if (!canAdd(candidate, cells)) continue;
        next.set(`${candidate.x},${candidate.y}`, candidate);
      }
    }
  }
  return [...next.values()].sort((a, b) => (
    potentialDegree(b, cells) - potentialDegree(a, cells) ||
    a.y - b.y || a.x - b.x
  ));
}

function searchBeamLayouts(n) {
  if (n <= 0) {
    return [];
  }

  const root = normalizeCells([{ x: 0, y: 0 }]);
  let beam = [{ cells: root, partial: scorePartialLayout(root) }];

  const beamWidth = n <= 10 ? 12 : 8;

  for (let size = 1; size < n; size++) {
    const nextMap = new Map();

    const branchLimit = size <= 3 ? 8 : size <= 6 ? 6 : 4;

    for (const state of beam) {
      const candidates = generateCandidatePositions(state.cells).slice(0, branchLimit);

      for (const candidate of candidates) {
        const nextCells = normalizeCells([...state.cells, candidate]);
        if (!isLegalLayout(nextCells)) continue;

        const key = canonical(nextCells);
        if (nextMap.has(key)) continue;

        nextMap.set(key, {
          cells: nextCells,
          partial: scorePartialLayout(nextCells)
        });
      }
    }

    beam = [...nextMap.values()]
      .sort((a, b) => (
        b.partial.pairScore - a.partial.pairScore ||
        b.partial.degreeHead - a.partial.degreeHead ||
        b.partial.compactness - a.partial.compactness ||
        a.partial.height - b.partial.height ||
        a.partial.width - b.partial.width
      ))
      .slice(0, beamWidth);
  }

  return beam.map(entry => entry.cells);
}

function compressLayouts(cellsList, maleCount, keep = 36) {
  const ranked = [...new Map(cellsList.map(cells => [canonical(cells), cells])).values()]
    .filter(isLegalLayout)
    .map(cells => ({
      cells,
      skeleton: scoreLayoutSkeleton(cells, maleCount)
    }))
    .sort((a, b) => (
      b.skeleton.crossEdges - a.skeleton.crossEdges ||
      b.skeleton.totalEdges - a.skeleton.totalEdges ||
      b.skeleton.degreeSum - a.skeleton.degreeSum ||
      b.skeleton.compactness - a.skeleton.compactness ||
      a.skeleton.height - b.skeleton.height
    ));

  const picked = [];
  const signatures = new Set();
  for (const entry of ranked) {
    const shape = scoreShape(entry.cells);
    const signature = [
      entry.skeleton.crossEdges,
      entry.skeleton.totalEdges,
      shape.width,
      shape.height,
      entry.cells.slice(0, Math.min(4, entry.cells.length)).map(cell => `${cell.x},${cell.y}`).join("|")
    ].join("__");
    if (signatures.has(signature) && picked.length >= Math.floor(keep * 0.6)) continue;
    signatures.add(signature);
    picked.push(entry.cells);
    if (picked.length >= keep) break;
  }
  return picked;
}

function generateLayoutCandidates(n, maleCount, limit = 32) {
  const structured = generateStructuredLayouts(n);
  const beamLayouts = searchBeamLayouts(n);
  return compressLayouts([...structured, ...beamLayouts], maleCount, limit);
}

function generateLayout(n, maleCount = Math.floor(n / 2)) {
  return generateLayoutCandidates(n, maleCount, 1)[0] || [];
}

function buildEdges(cells) {
  const edges = [];
  const adjacency = Array.from({ length: cells.length }, () => []);
  for (let i = 0; i < cells.length; i++) {
    for (let j = i + 1; j < cells.length; j++) {
      if (hasEdge(cells[i], cells[j])) {
        edges.push([i, j]);
        adjacency[i].push(j);
        adjacency[j].push(i);
      }
    }
  }
  return { edges, adjacency };
}

function estimateCombinationCount(n, k) {
  const choose = Math.min(k, n - k);
  let result = 1;
  for (let i = 1; i <= choose; i++) {
    result = (result * (n - choose + i)) / i;
    if (result > 400000) {
      return result;
    }
  }
  return result;
}

function optimizeSexSplit(n, maleCount, edges, adjacency) {
  const estimate = estimateCombinationCount(n, maleCount);
  if (estimate <= 300000) {
    let bestMask = 0;
    let bestScore = -1;

    function dfs(start, chosen, mask) {
      if (chosen === maleCount) {
        let cut = 0;
        for (const [a, b] of edges) {
          if ((((mask >>> a) & 1) === 1) !== (((mask >>> b) & 1) === 1)) {
            cut++;
          }
        }
        if (cut > bestScore) {
          bestScore = cut;
          bestMask = mask;
        }
        return;
      }
      for (let index = start; index <= n - (maleCount - chosen); index++) {
        dfs(index + 1, chosen + 1, mask | (1 << index));
      }
    }

    dfs(0, 0, 0);
    return { maleMask: bestMask, crossEdgeUpperBound: bestScore };
  }

  const order = [...Array(n).keys()].sort((a, b) => adjacency[b].length - adjacency[a].length);
  let maleSet = new Set(order.slice(0, maleCount));

  function cutScoreForSet(set) {
    let score = 0;
    for (const [a, b] of edges) {
      if (set.has(a) !== set.has(b)) {
        score++;
      }
    }
    return score;
  }

  let improved = true;
  while (improved) {
    improved = false;
    let bestSwap = null;
    let bestScore = cutScoreForSet(maleSet);
    const males = [...maleSet];
    const females = [...Array(n).keys()].filter(index => !maleSet.has(index));
    for (const male of males) {
      for (const female of females) {
        const next = new Set(maleSet);
        next.delete(male);
        next.add(female);
        const score = cutScoreForSet(next);
        if (score > bestScore) {
          bestScore = score;
          bestSwap = { male, female };
        }
      }
    }
    if (bestSwap) {
      maleSet.delete(bestSwap.male);
      maleSet.add(bestSwap.female);
      improved = true;
    }
  }

  let mask = 0;
  for (const index of maleSet) {
    mask |= 1 << index;
  }
  return { maleMask: mask, crossEdgeUpperBound: cutScoreForSet(maleSet) };
}

function scoreLayoutSkeleton(cells, maleCount) {
  const { edges, adjacency } = buildEdges(cells);
  const sexPlan = optimizeSexSplit(cells.length, maleCount, edges, adjacency);
  const degrees = adjacency.map(list => list.length).sort((a, b) => b - a);
  const degreeSum = degrees.reduce((sum, value) => sum + value, 0);
  const topHalfDegree = degrees.slice(0, Math.max(1, Math.ceil(degrees.length / 2))).reduce((sum, value) => sum + value, 0);
  const shapeScore = scoreShape(cells);
  return {
    crossEdges: sexPlan.crossEdgeUpperBound,
    totalEdges: edges.length,
    degreeSum,
    topHalfDegree,
    compactness: shapeScore.compactness,
    height: shapeScore.height
  };
}

function generateLayoutNeighbors(cells) {
  const seen = new Map();
  for (let index = 0; index < cells.length; index++) {
    const cell = cells[index];
    for (let dx = -2; dx <= 2; dx++) {
      for (let dy = -2; dy <= 2; dy++) {
        if (dx === 0 && dy === 0) continue;
        const candidate = { x: cell.x + dx, y: cell.y + dy };
        if (cells.some((other, otherIndex) => otherIndex !== index && cellsOverlap(other, candidate))) continue;
        if (!cells.some((other, otherIndex) => otherIndex !== index && hasEdge(other, candidate))) continue;
        const next = cells.map((entry, entryIndex) => (
          entryIndex === index ? candidate : entry
        ));
        const normalized = normalizeCells(next);
        if (!isLegalLayout(normalized)) continue;
        seen.set(canonical(normalized), normalized);
      }
    }
  }
  return [...seen.values()];
}

function refineLayoutCandidates(cellsList, maleCount, limit = 32) {
  const pool = new Map();

  function add(cells) {
    if (isLegalLayout(cells)) {
      pool.set(canonical(cells), cells);
    }
  }

  cellsList.forEach(add);
  cellsList.slice(0, Math.min(cellsList.length, 10)).forEach(cells => {
    generateLayoutNeighbors(cells).forEach(add);
  });

  return [...pool.values()]
    .map(cells => ({ cells, skeleton: scoreLayoutSkeleton(cells, maleCount) }))
    .sort((a, b) => (
      b.skeleton.crossEdges - a.skeleton.crossEdges ||
      b.skeleton.totalEdges - a.skeleton.totalEdges ||
      b.skeleton.topHalfDegree - a.skeleton.topHalfDegree ||
      b.skeleton.degreeSum - a.skeleton.degreeSum ||
      b.skeleton.compactness - a.skeleton.compactness ||
      a.skeleton.height - b.skeleton.height
    ))
    .slice(0, limit)
    .map(entry => entry.cells);
}

function buildFemaleVariantOptions(inventory) {
  const options = [];
  for (const species of SPECIES_BY_INDEX) {
    if (inventory.statuses[species.index] === "ignore") {
      continue;
    }
    if (inventory.shinyFemaleStocks[species.index] > 0) {
      options.push({
        speciesIndex: species.index,
        species,
        isShiny: true,
        stock: inventory.shinyFemaleStocks[species.index],
        key: `${species.index}:shiny`
      });
    }
    if (inventory.statuses[species.index] === "missing" && inventory.shinyFemaleStocks[species.index] === 0) {
      options.push({
        speciesIndex: species.index,
        species,
        isShiny: false,
        stock: inventory.normalTargetFemaleStock || 20,
        key: `${species.index}:normal-fallback`
      });
    }
  }
  return options;
}

function buildMaleVariantOptions(inventory) {
  const options = [];
  for (const species of SPECIES_BY_INDEX) {
    if (inventory.statuses[species.index] === "ignore") {
      continue;
    }
    if (inventory.shinyMaleStocks[species.index] > 0) {
      options.push({
        speciesIndex: species.index,
        species,
        isShiny: true,
        stock: inventory.shinyMaleStocks[species.index],
        key: `${species.index}:shiny`
      });
    }
    options.push({
      speciesIndex: species.index,
      species,
      isShiny: false,
      stock: inventory.normalTargetMaleStock || 20,
      key: `${species.index}:normal`
    });
  }
  return options;
}

function rankFemaleCandidate(candidate, state, statuses, degree) {
  const status = statuses[candidate.speciesIndex];
  const used = state.femaleUsed[candidate.key] || 0;
  let score = degree * 22 + candidate.species.groups.length * 4;
  if (status === "missing") {
    score += 280;
    if (!state.usedMissingSpecies.has(candidate.speciesIndex)) {
      score += 170;
    } else {
      score += 20;
    }
    score += candidate.isShiny ? 110 : 18;
  }
  return score;
}

function compareScores(a, b, targetPriority = "variety") {
  const aShinyPercent = getExpectedShinyPercentCenti(a);
  const bShinyPercent = getExpectedShinyPercentCenti(b);
  const aShinyUsage = getShinyUsage(a);
  const bShinyUsage = getShinyUsage(b);
  const primary = targetPriority === "wanted"
    ? (b.targetPairs - a.targetPairs || b.coveredMissingSpecies - a.coveredMissingSpecies)
    : targetPriority === "probability"
      ? (b.coveredMissingSpecies - a.coveredMissingSpecies || bShinyPercent - aShinyPercent || b.targetPairs - a.targetPairs)
      : (b.coveredMissingSpecies - a.coveredMissingSpecies || b.targetPairs - a.targetPairs);
  const secondary = targetPriority === "probability"
    ? (bShinyUsage - aShinyUsage || b.totalPairs - a.totalPairs)
    : (b.totalPairs - a.totalPairs || bShinyUsage - aShinyUsage);
  return (
    primary ||
    a.deadFemales - b.deadFemales ||
    a.deadMales - b.deadMales ||
    secondary ||
    a.idleTargetFemales - b.idleTargetFemales ||
    bShinyUsage - aShinyUsage ||
    b.shinyChanceScore - a.shinyChanceScore ||
    b.coveredMissingFemales - a.coveredMissingFemales
  );
}

function isBetterScore(next, current, targetPriority) {
  return compareScores(current, next, targetPriority) > 0;
}

function evaluateAssignment(adjacency, femaleIndices, maleIndices, femaleAssignment, maleAssignment, inventory) {
  const coveredMissingSpecies = new Set();
  let coveredMissingFemales = 0;
  let targetPairs = 0;
  let totalPairs = 0;
  let shinyChanceScore = 0;
  let deadMales = 0;
  let deadFemales = 0;
  let shinyMaleUsage = 0;
  let shinyFemaleUsage = 0;

  for (const maleIndex of maleIndices) {
    const maleCandidate = maleAssignment[maleIndex];
    if (!maleCandidate) {
      deadMales++;
      continue;
    }
    if (maleCandidate.isShiny) {
      shinyMaleUsage++;
    }
    let malePairs = 0;
    for (const neighbor of adjacency[maleIndex]) {
      const femaleCandidate = femaleAssignment[neighbor];
      if (!femaleCandidate) {
        continue;
      }
      if ((femaleCandidate.species.mask & maleCandidate.species.mask) === 0) {
        continue;
      }
      if (!femaleCandidate.isShiny && !maleCandidate.isShiny) {
        continue;
      }
      malePairs++;
      totalPairs++;
      shinyChanceScore += (femaleCandidate.isShiny ? 1 : 0) + (maleCandidate.isShiny ? 1 : 0);
      if (inventory.statuses[femaleCandidate.speciesIndex] === "missing") {
        targetPairs++;
        coveredMissingSpecies.add(femaleCandidate.speciesIndex);
      }
    }
    if (malePairs === 0) {
      deadMales++;
    }
  }

  for (const femaleIndex of femaleIndices) {
    const femaleCandidate = femaleAssignment[femaleIndex];
    if (!femaleCandidate) {
      deadFemales++;
      continue;
    }
    if (femaleCandidate.isShiny) {
      shinyFemaleUsage++;
    }
    let covered = false;
    for (const neighbor of adjacency[femaleIndex]) {
      const maleCandidate = maleAssignment[neighbor];
      if (!maleCandidate) {
        continue;
      }
      if ((femaleCandidate.species.mask & maleCandidate.species.mask) === 0) {
        continue;
      }
      if (!femaleCandidate.isShiny && !maleCandidate.isShiny) {
        continue;
      }
      covered = true;
      break;
    }
    if (!covered) {
      deadFemales++;
    }
    if (inventory.statuses[femaleCandidate.speciesIndex] !== "missing") {
      continue;
    }
    if (covered) {
      coveredMissingFemales++;
    }
  }

  const missingFemaleTotal = femaleIndices.filter(index => {
    const candidate = femaleAssignment[index];
    return candidate && inventory.statuses[candidate.speciesIndex] === "missing";
  }).length;

  return {
    coveredMissingSpecies: coveredMissingSpecies.size,
    targetPairs,
    totalPairs,
    shinyChanceScore,
    deadFemales,
    coveredMissingFemales,
    deadMales,
    idleTargetFemales: missingFemaleTotal - coveredMissingFemales,
    shinyMaleUsage,
    shinyFemaleUsage,
    shinyUsage: shinyMaleUsage + shinyFemaleUsage,
    expectedShinyPercentCenti: shinyChanceScore * SINGLE_SHINY_PERCENT_CENTI
  };
}

function cloneAssignmentMap(source) {
  return { ...source };
}

function repairUnmatchedFemales(adjacency, femaleIndices, femaleOptions, femaleAssignment, maleAssignment, inventory) {
  function countFemaleUse(key, ignoreIndex) {
    let used = 0;
    for (const index of femaleIndices) {
      if (index === ignoreIndex) {
        continue;
      }
      const current = femaleAssignment[index];
      if (current && current.key === key) {
        used++;
      }
    }
    return used;
  }

  for (const femaleIndex of femaleIndices) {
    const currentFemale = femaleAssignment[femaleIndex];
    if (!currentFemale) {
      continue;
    }

    const isCovered = adjacency[femaleIndex].some(maleIndex => {
      const maleCandidate = maleAssignment[maleIndex];
      return maleCandidate && ((currentFemale.species.mask & maleCandidate.species.mask) !== 0);
    });
    if (isCovered) {
      continue;
    }

    const rankedCandidates = femaleOptions
      .filter(candidate => {
        const compatible = adjacency[femaleIndex].some(maleIndex => {
          const maleCandidate = maleAssignment[maleIndex];
          return maleCandidate && ((candidate.species.mask & maleCandidate.species.mask) !== 0);
        });
        if (!compatible) {
          return false;
        }
        const used = countFemaleUse(candidate.key, femaleIndex);
        return used < candidate.stock;
      })
      .sort((a, b) => {
        const aMissing = inventory.statuses[a.speciesIndex] === "missing" ? 1 : 0;
        const bMissing = inventory.statuses[b.speciesIndex] === "missing" ? 1 : 0;
        return (
          bMissing - aMissing ||
          (a.isShiny ? 1 : 0) - (b.isShiny ? 1 : 0) ||
          a.speciesIndex - b.speciesIndex
        );
      });

    if (rankedCandidates.length > 0) {
      femaleAssignment[femaleIndex] = rankedCandidates[0];
    }
  }
}

function upgradeOwnedFemalesToTargets(adjacency, femaleIndices, femaleOptions, femaleAssignment, maleAssignment, inventory) {
  function countFemaleUse(key, ignoreIndex) {
    let used = 0;
    for (const index of femaleIndices) {
      if (index === ignoreIndex) {
        continue;
      }
      const current = femaleAssignment[index];
      if (current && current.key === key) {
        used++;
      }
    }
    return used;
  }

  const targetCandidates = femaleOptions.filter(candidate => inventory.statuses[candidate.speciesIndex] === "missing");
  if (targetCandidates.length === 0) {
    return;
  }

  for (const femaleIndex of femaleIndices) {
    const currentFemale = femaleAssignment[femaleIndex];
    if (!currentFemale || inventory.statuses[currentFemale.speciesIndex] === "missing") {
      continue;
    }

    const compatibleTargets = targetCandidates
      .filter(candidate => {
        const used = countFemaleUse(candidate.key, femaleIndex);
        if (used >= candidate.stock) {
          return false;
        }
        return adjacency[femaleIndex].some(maleIndex => {
          const maleCandidate = maleAssignment[maleIndex];
          return maleCandidate && ((candidate.species.mask & maleCandidate.species.mask) !== 0);
        });
      })
      .sort((a, b) => (
        (b.isShiny ? 1 : 0) - (a.isShiny ? 1 : 0) ||
        a.speciesIndex - b.speciesIndex
      ));

    if (compatibleTargets.length > 0) {
      femaleAssignment[femaleIndex] = compatibleTargets[0];
    }
  }
}

function improvePlanLocally(adjacency, femaleIndices, maleIndices, femaleOptions, maleOptions, inventory, plan, targetPriority) {
  const femaleAssignment = cloneAssignmentMap(plan.femaleAssignment);
  const maleAssignment = cloneAssignmentMap(plan.maleAssignment);
  upgradeOwnedFemalesToTargets(adjacency, femaleIndices, femaleOptions, femaleAssignment, maleAssignment, inventory);
  repairUnmatchedFemales(adjacency, femaleIndices, femaleOptions, femaleAssignment, maleAssignment, inventory);
  let bestScore = evaluateAssignment(adjacency, femaleIndices, maleIndices, femaleAssignment, maleAssignment, inventory);

  function femaleCanUse(candidate, targetIndex) {
    let used = 0;
    for (const index of femaleIndices) {
      const current = femaleAssignment[index];
      if (!current || current.key !== candidate.key) {
        continue;
      }
      used++;
    }
    const currentAtSlot = femaleAssignment[targetIndex];
    if (currentAtSlot && currentAtSlot.key === candidate.key) {
      used--;
    }
    return used < candidate.stock;
  }

  function maleCanUse(candidate, targetIndex) {
    let used = 0;
    for (const index of maleIndices) {
      const current = maleAssignment[index];
      if (!current || current.key !== candidate.key) {
        continue;
      }
      used++;
    }
    const currentAtSlot = maleAssignment[targetIndex];
    if (currentAtSlot && currentAtSlot.key === candidate.key) {
      used--;
    }
    return used < candidate.stock;
  }

  let improved = true;
  let rounds = 0;
  while (improved && rounds < 5) {
    improved = false;
    rounds++;

    for (const maleIndex of maleIndices) {
      for (const candidate of maleOptions) {
        if (!maleCanUse(candidate, maleIndex)) {
          continue;
        }
        if (maleAssignment[maleIndex] && maleAssignment[maleIndex].key === candidate.key) {
          continue;
        }
        const previous = maleAssignment[maleIndex];
        maleAssignment[maleIndex] = candidate;
        const nextScore = evaluateAssignment(adjacency, femaleIndices, maleIndices, femaleAssignment, maleAssignment, inventory);
        if (isBetterScore(nextScore, bestScore, targetPriority)) {
          bestScore = nextScore;
          improved = true;
        } else {
          maleAssignment[maleIndex] = previous;
        }
      }
    }

    for (const femaleIndex of femaleIndices) {
      for (const candidate of femaleOptions) {
        if (!femaleCanUse(candidate, femaleIndex)) {
          continue;
        }
        if (femaleAssignment[femaleIndex] && femaleAssignment[femaleIndex].key === candidate.key) {
          continue;
        }
        const previous = femaleAssignment[femaleIndex];
        femaleAssignment[femaleIndex] = candidate;
        upgradeOwnedFemalesToTargets(adjacency, femaleIndices, femaleOptions, femaleAssignment, maleAssignment, inventory);
        repairUnmatchedFemales(adjacency, femaleIndices, femaleOptions, femaleAssignment, maleAssignment, inventory);
        const nextScore = evaluateAssignment(adjacency, femaleIndices, maleIndices, femaleAssignment, maleAssignment, inventory);
        if (isBetterScore(nextScore, bestScore, targetPriority)) {
          bestScore = nextScore;
          improved = true;
        } else {
          femaleAssignment[femaleIndex] = previous;
        }
      }
    }
  }

  const femaleCoverage = {};
  for (const femaleIndex of femaleIndices) {
    const femaleCandidate = femaleAssignment[femaleIndex];
    if (!femaleCandidate) {
      femaleCoverage[femaleIndex] = false;
      continue;
    }
    femaleCoverage[femaleIndex] = adjacency[femaleIndex].some(maleIndex => {
      const maleCandidate = maleAssignment[maleIndex];
      return maleCandidate && ((femaleCandidate.species.mask & maleCandidate.species.mask) !== 0);
    });
  }

  return {
    femaleAssignment,
    maleAssignment,
    femaleCoverage,
    score: bestScore
  };
}

function optimizeWithInventory(adjacency, maleMask, inventory, targetPriority) {
  const femaleIndices = [];
  const maleIndices = [];
  for (let i = 0; i < adjacency.length; i++) {
    if (((maleMask >>> i) & 1) === 1) {
      maleIndices.push(i);
    } else {
      femaleIndices.push(i);
    }
  }

  const femaleOrder = [...femaleIndices].sort((a, b) => adjacency[b].length - adjacency[a].length || a - b);
  const maleOrder = [...maleIndices].sort((a, b) => adjacency[b].length - adjacency[a].length || a - b);
  const femaleOptions = buildFemaleVariantOptions(inventory);
  const maleOptions = buildMaleVariantOptions(inventory);
  if (femaleOptions.length === 0 || maleOptions.length === 0) {
    return null;
  }

  const beamWidth = 60;
  let femaleStates = [{
    assignment: {},
    femaleUsed: {},
    usedMissingSpecies: new Set(),
    heuristic: 0
  }];

  for (const femaleIndex of femaleOrder) {
    const nextStates = [];
    for (const state of femaleStates) {
      const ranked = [...femaleOptions]
        .filter(candidate => (state.femaleUsed[candidate.key] || 0) < candidate.stock)
        .sort((a, b) => (
          rankFemaleCandidate(b, state, inventory.statuses, adjacency[femaleIndex].length) -
          rankFemaleCandidate(a, state, inventory.statuses, adjacency[femaleIndex].length)
        ))
        .slice(0, 4);

      for (const candidate of ranked) {
        const nextUsed = { ...state.femaleUsed, [candidate.key]: (state.femaleUsed[candidate.key] || 0) + 1 };
        const nextMissing = new Set(state.usedMissingSpecies);
        if (inventory.statuses[candidate.speciesIndex] === "missing") {
          nextMissing.add(candidate.speciesIndex);
        }
        nextStates.push({
          assignment: { ...state.assignment, [femaleIndex]: candidate },
          femaleUsed: nextUsed,
          usedMissingSpecies: nextMissing,
          heuristic: state.heuristic + rankFemaleCandidate(candidate, state, inventory.statuses, adjacency[femaleIndex].length)
        });
      }
    }
    femaleStates = nextStates
      .sort((a, b) => b.heuristic - a.heuristic || b.usedMissingSpecies.size - a.usedMissingSpecies.size)
      .slice(0, beamWidth);
  }

  const planCandidates = [];
  for (const femaleState of femaleStates) {
    const femaleBitIndex = new Map(femaleIndices.map((femaleIndex, bitIndex) => [femaleIndex, bitIndex]));
    const maleCandidateMetrics = {};
    for (const maleIndex of maleOrder) {
      maleCandidateMetrics[maleIndex] = maleOptions.map(candidate => {
        let coveredMask = 0;
        let totalPairs = 0;
        let targetPairs = 0;
        let shinyChanceScore = 0;
        for (const neighbor of adjacency[maleIndex]) {
          const femaleCandidate = femaleState.assignment[neighbor];
          if (femaleCandidate == null) {
            continue;
          }
          if ((femaleCandidate.species.mask & candidate.species.mask) === 0) {
            continue;
          }
          if (!femaleCandidate.isShiny && !candidate.isShiny) {
            continue;
          }
          totalPairs++;
          coveredMask |= (1 << femaleBitIndex.get(neighbor));
          shinyChanceScore += (femaleCandidate.isShiny ? 1 : 0) + (candidate.isShiny ? 1 : 0);
          if (inventory.statuses[femaleCandidate.speciesIndex] === "missing") {
            targetPairs++;
          }
        }
        return { candidate, coveredMask, totalPairs, targetPairs, shinyChanceScore };
      });
    }

    function summarizeCoverage(mask) {
      const coveredMissingSpecies = new Set();
      let coveredMissingFemales = 0;
      for (let bitIndex = 0; bitIndex < femaleIndices.length; bitIndex++) {
        if (((mask >>> bitIndex) & 1) === 0) {
          continue;
        }
        const femaleIndex = femaleIndices[bitIndex];
        const femaleCandidate = femaleState.assignment[femaleIndex];
        if (femaleCandidate && inventory.statuses[femaleCandidate.speciesIndex] === "missing") {
          coveredMissingSpecies.add(femaleCandidate.speciesIndex);
          coveredMissingFemales++;
        }
      }
      return {
        coveredMissingSpecies: coveredMissingSpecies.size,
        coveredMissingFemales
      };
    }

    const maleBeamWidth = 70;
    let maleStates = [{
      assignment: {},
      used: {},
      coveredMask: 0,
      totalPairs: 0, targetPairs: 0, shinyChanceScore: 0,
      deadMales: 0,
      shinyMaleUsage: 0
    }];

    for (const maleIndex of maleOrder) {
      const nextStates = [];
      for (const state of maleStates) {
        const metrics = maleCandidateMetrics[maleIndex]
          .filter(item => (state.used[item.candidate.key] || 0) < item.candidate.stock)
          .sort((a, b) => (
            b.targetPairs - a.targetPairs ||
            b.totalPairs - a.totalPairs ||
            b.shinyChanceScore - a.shinyChanceScore
          ));

        const positiveMetrics = metrics.filter(item => item.totalPairs > 0);
        const fallbackMetrics = positiveMetrics.length > 0 ? positiveMetrics.slice(0, 4) : metrics.slice(0, 2);

        for (const metric of fallbackMetrics) {
          const nextUsed = { ...state.used, [metric.candidate.key]: (state.used[metric.candidate.key] || 0) + 1 };
          nextStates.push({
            assignment: { ...state.assignment, [maleIndex]: metric.candidate },
            used: nextUsed,
            coveredMask: state.coveredMask | metric.coveredMask,
            totalPairs: state.totalPairs + metric.totalPairs,
            targetPairs: state.targetPairs + metric.targetPairs,
            shinyChanceScore: state.shinyChanceScore + metric.shinyChanceScore,
            deadMales: state.deadMales + (metric.totalPairs > 0 ? 0 : 1),
            shinyMaleUsage: state.shinyMaleUsage + (metric.candidate.isShiny ? 1 : 0)
          });
        }
      }

      maleStates = nextStates
        .sort((a, b) => {
          const aCoverage = summarizeCoverage(a.coveredMask);
          const bCoverage = summarizeCoverage(b.coveredMask);
          const aIdleTargetFemales = aCoverage.coveredMissingFemales === 0
            ? femaleIndices.filter(index => inventory.statuses[femaleState.assignment[index].speciesIndex] === "missing").length
            : femaleIndices.filter(index => inventory.statuses[femaleState.assignment[index].speciesIndex] === "missing").length - aCoverage.coveredMissingFemales;
          const bIdleTargetFemales = bCoverage.coveredMissingFemales === 0
            ? femaleIndices.filter(index => inventory.statuses[femaleState.assignment[index].speciesIndex] === "missing").length
            : femaleIndices.filter(index => inventory.statuses[femaleState.assignment[index].speciesIndex] === "missing").length - bCoverage.coveredMissingFemales;
          return compareScores(
            {
              coveredMissingSpecies: aCoverage.coveredMissingSpecies,
              targetPairs: a.targetPairs,
              totalPairs: a.totalPairs,
              deadFemales: femaleIndices.length - aCoverage.coveredMissingFemales,
              deadMales: a.deadMales,
              idleTargetFemales: aIdleTargetFemales,
              shinyMaleUsage: a.shinyMaleUsage,
              shinyChanceScore: a.shinyChanceScore,
              coveredMissingFemales: aCoverage.coveredMissingFemales
            },
            {
              coveredMissingSpecies: bCoverage.coveredMissingSpecies,
              targetPairs: b.targetPairs,
              totalPairs: b.totalPairs,
              deadFemales: femaleIndices.length - bCoverage.coveredMissingFemales,
              deadMales: b.deadMales,
              idleTargetFemales: bIdleTargetFemales,
              shinyMaleUsage: b.shinyMaleUsage,
              shinyChanceScore: b.shinyChanceScore,
              coveredMissingFemales: bCoverage.coveredMissingFemales
            },
            targetPriority
          );
        })
        .slice(0, maleBeamWidth);
    }

    const finalists = maleStates.slice(0, 6);
    for (const maleState of finalists) {
      const coverageSummary = summarizeCoverage(maleState.coveredMask);
      const femaleCoverage = {};
      for (let bitIndex = 0; bitIndex < femaleIndices.length; bitIndex++) {
        if (((maleState.coveredMask >>> bitIndex) & 1) === 1) {
          femaleCoverage[femaleIndices[bitIndex]] = true;
        }
      }

      const improvedPlan = improvePlanLocally(
        adjacency,
        femaleIndices,
        maleIndices,
        femaleOptions,
        maleOptions,
        inventory,
        {
          femaleAssignment: femaleState.assignment,
          maleAssignment: maleState.assignment,
          femaleCoverage,
          score: {
            coveredMissingSpecies: coverageSummary.coveredMissingSpecies,
            targetPairs: maleState.targetPairs,
            shinyChanceScore: maleState.shinyChanceScore,
            totalPairs: maleState.totalPairs,
            coveredMissingFemales: coverageSummary.coveredMissingFemales,
            deadFemales: femaleIndices.length - coverageSummary.coveredMissingFemales,
            deadMales: maleState.deadMales,
            idleTargetFemales: femaleIndices.filter(index => inventory.statuses[femaleState.assignment[index].speciesIndex] === "missing").length - coverageSummary.coveredMissingFemales,
            shinyMaleUsage: maleState.shinyMaleUsage
          }
        },
        targetPriority
      );

      planCandidates.push(improvedPlan);
    }
  }

  const deduped = new Map();
  for (const candidate of planCandidates) {
    const femalePart = femaleIndices
      .map(index => {
        const item = candidate.femaleAssignment[index];
        return `${index}:${item.speciesIndex}:${item.isShiny ? 1 : 0}`;
      })
      .join("|");
    const malePart = maleIndices
      .map(index => {
        const item = candidate.maleAssignment[index];
        return `${index}:${item.speciesIndex}:${item.isShiny ? 1 : 0}`;
      })
      .join("|");
    const key = `${femalePart}__${malePart}`;
    if (!deduped.has(key) || compareScores(deduped.get(key).score, candidate.score, targetPriority) > 0) {
      deduped.set(key, candidate);
    }
  }

  return [...deduped.values()]
    .sort((a, b) => compareScores(a.score, b.score, targetPriority))
    .slice(0, 5);
}

function summarizeMaterializedPlan(nests, compatiblePairs, inventory) {
  const coveredMissingSpecies = new Set();
  const coveredFemaleIndices = new Set();
  const coveredMaleIndices = new Set();
  let targetPairs = 0;
  let shinyChanceScore = 0;
  let shinyMaleUsage = 0;
  let shinyFemaleUsage = 0;

  for (const pair of compatiblePairs) {
    coveredFemaleIndices.add(pair.female.index);
    coveredMaleIndices.add(pair.male.index);
    shinyChanceScore += (pair.female.isShiny ? 1 : 0) + (pair.male.isShiny ? 1 : 0);
    if (inventory.statuses[pair.female.species.index] === "missing") {
      coveredMissingSpecies.add(pair.female.species.index);
      targetPairs++;
    }
  }

  const femaleNests = nests.filter(nest => !nest.isMale);
  const maleNests = nests.filter(nest => nest.isMale);
  const targetFemaleNests = femaleNests.filter(nest => inventory.statuses[nest.species.index] === "missing");
  shinyMaleUsage = maleNests.filter(nest => nest.isShiny).length;
  shinyFemaleUsage = femaleNests.filter(nest => nest.isShiny).length;

  return {
    coveredMissingSpecies: coveredMissingSpecies.size,
    targetPairs,
    totalPairs: compatiblePairs.length,
    shinyChanceScore,
    coveredMissingFemales: targetFemaleNests.filter(nest => coveredFemaleIndices.has(nest.index)).length,
    deadFemales: femaleNests.filter(nest => !coveredFemaleIndices.has(nest.index)).length,
    deadMales: maleNests.filter(nest => !coveredMaleIndices.has(nest.index)).length,
    idleTargetFemales: targetFemaleNests.filter(nest => !coveredFemaleIndices.has(nest.index)).length,
    shinyMaleUsage,
    shinyFemaleUsage,
    shinyUsage: shinyMaleUsage + shinyFemaleUsage,
    expectedShinyPercentCenti: shinyChanceScore * SINGLE_SHINY_PERCENT_CENTI
  };
}

function buildCompatiblePairsFromNests(nests, edges) {
  const compatiblePairs = [];
  for (const [a, b] of edges) {
    const left = nests[a];
    const right = nests[b];
    if (left.isMale === right.isMale) { continue; }
    if ((left.species.mask & right.species.mask) === 0) { continue; }
    if (!left.isShiny && !right.isShiny) { continue; }
    const female = left.isMale ? right : left;
    const male = left.isMale ? left : right;
    compatiblePairs.push({
      female,
      male,
      distance: Math.abs(left.centerX - right.centerX) + Math.abs(left.centerY - right.centerY)
    });
  }
  return compatiblePairs;
}

function optimizeLayoutForFixedRoster(plan, inventory, targetPriority) {
  const maleRoster = plan.nests
    .filter(nest => nest.isMale)
    .map((nest, index) => ({
      uid: `m${index}:${nest.species.index}:${nest.isShiny ? 1 : 0}`,
      speciesIndex: nest.species.index,
      species: nest.species,
      isShiny: nest.isShiny
    }));
  const femaleRoster = plan.nests
    .filter(nest => !nest.isMale)
    .map((nest, index) => ({
      uid: `f${index}:${nest.species.index}:${nest.isShiny ? 1 : 0}`,
      speciesIndex: nest.species.index,
      species: nest.species,
      isShiny: nest.isShiny
    }));

  const candidateLayouts = refineLayoutCandidates(
    generateLayoutCandidates(plan.nestCount, plan.maleCount, plan.nestCount <= 10 ? 32 : 24),
    plan.maleCount,
    plan.nestCount <= 10 ? 18 : 12
  );

  function femaleRank(candidate, degree) {
    const status = inventory.statuses[candidate.speciesIndex];
    let score = degree * 20 + candidate.species.groups.length * 4;
    if (status === "missing") {
      score += 280;
    }
    score += candidate.isShiny ? (status === "missing" ? 40 : -10) : 12;
    return score;
  }

  function maleRank(candidate, degree) {
    return degree * 20 + candidate.species.groups.length * 8 + (candidate.isShiny ? 14 : 0);
  }

  function evaluateLayout(cells) {
    if (!isLegalLayout(cells)) { return null; }
    const { edges, adjacency } = buildEdges(cells);
    const sexPlan = optimizeSexSplit(cells.length, plan.maleCount, edges, adjacency);
    const femaleIndices = [];
    const maleIndices = [];
    for (let i = 0; i < cells.length; i++) {
      if (((sexPlan.maleMask >>> i) & 1) === 1) {
        maleIndices.push(i);
      } else {
        femaleIndices.push(i);
      }
    }

    const femaleAssignment = {};
    const maleAssignment = {};
    const sortedFemaleIndices = [...femaleIndices].sort((a, b) => adjacency[b].length - adjacency[a].length || a - b);
    const sortedMaleIndices = [...maleIndices].sort((a, b) => adjacency[b].length - adjacency[a].length || a - b);
    const sortedFemales = [...femaleRoster].sort((a, b) => femaleRank(b, 0) - femaleRank(a, 0) || a.speciesIndex - b.speciesIndex);
    const sortedMales = [...maleRoster].sort((a, b) => maleRank(b, 0) - maleRank(a, 0) || a.speciesIndex - b.speciesIndex);

    sortedFemaleIndices.forEach((cellIndex, orderIndex) => {
      femaleAssignment[cellIndex] = sortedFemales[orderIndex];
    });
    sortedMaleIndices.forEach((cellIndex, orderIndex) => {
      maleAssignment[cellIndex] = sortedMales[orderIndex];
    });

    function buildCurrentNests() {
      return cells.map((cell, index) => {
        const isMale = ((sexPlan.maleMask >>> index) & 1) === 1;
        const candidate = isMale ? maleAssignment[index] : femaleAssignment[index];
        const status = inventory.statuses[candidate.speciesIndex];
        return {
          index,
          x: cell.x,
          y: cell.y,
          centerX: cell.x + 1,
          centerY: cell.y + 1,
          isMale,
          sex: isMale ? "雄性" : "雌性",
          species: candidate.species,
          isShiny: candidate.isShiny,
          rarityLabel: candidate.isShiny ? "异色" : "非异色",
          status,
          groups: candidate.species.groups.join(" / "),
          covered: false
        };
      });
    }

    function evaluateCurrent() {
      const nests = buildCurrentNests();
      const compatiblePairs = buildCompatiblePairsFromNests(nests, edges);
      const score = summarizeMaterializedPlan(nests, compatiblePairs, inventory);
      const coveredFemaleIndices = new Set(compatiblePairs.map(pair => pair.female.index));
      nests.forEach(nest => {
        if (!nest.isMale) {
          nest.covered = coveredFemaleIndices.has(nest.index);
        }
      });
      return { nests, compatiblePairs, score };
    }

    let best = evaluateCurrent();
    let improved = true;
    let rounds = 0;
    while (improved && rounds < 2) {
      improved = false;
      rounds++;

      for (let i = 0; i < sortedFemaleIndices.length; i++) {
        for (let j = i + 1; j < sortedFemaleIndices.length; j++) {
          const a = sortedFemaleIndices[i];
          const b = sortedFemaleIndices[j];
          [femaleAssignment[a], femaleAssignment[b]] = [femaleAssignment[b], femaleAssignment[a]];
          const next = evaluateCurrent();
          if (isBetterScore(next.score, best.score, targetPriority)) {
            best = next;
            improved = true;
          } else {
            [femaleAssignment[a], femaleAssignment[b]] = [femaleAssignment[b], femaleAssignment[a]];
          }
        }
      }

      for (let i = 0; i < sortedMaleIndices.length; i++) {
        for (let j = i + 1; j < sortedMaleIndices.length; j++) {
          const a = sortedMaleIndices[i];
          const b = sortedMaleIndices[j];
          [maleAssignment[a], maleAssignment[b]] = [maleAssignment[b], maleAssignment[a]];
          const next = evaluateCurrent();
          if (isBetterScore(next.score, best.score, targetPriority)) {
            best = next;
            improved = true;
          } else {
            [maleAssignment[a], maleAssignment[b]] = [maleAssignment[b], maleAssignment[a]];
          }
        }
      }
    }

    return {
      nests: best.nests,
      compatiblePairs: best.compatiblePairs,
      score: best.score,
      maleCount: plan.maleCount,
      femaleCount: plan.femaleCount,
      nestCount: plan.nestCount,
      theoreticalPairs: plan.theoreticalPairs,
      reachableCrossEdges: sexPlan.crossEdgeUpperBound,
      missingSpeciesInInventory: plan.missingSpeciesInInventory
    };
  }

  let bestPlan = plan;
  for (const cells of candidateLayouts) {
    const candidatePlan = evaluateLayout(cells);
    if (!candidatePlan) { continue; }
    if (isBetterScore(candidatePlan.score, bestPlan.score, targetPriority)) {
      bestPlan = candidatePlan;
    }
  }
  return bestPlan;
}

function materializePlan(cells, edges, sexPlan, assignmentPlan, inventory, maleCount, femaleCount, nestCount) {
  if (!assignmentPlan) { return null; }
  if (!isLegalLayout(cells)) { return null; }

  const nests = cells.map((cell, index) => {
    const isMale = ((sexPlan.maleMask >>> index) & 1) === 1;
    const candidate = isMale ? assignmentPlan.maleAssignment[index] : assignmentPlan.femaleAssignment[index];
    const species = candidate.species;
    const status = inventory.statuses[candidate.speciesIndex];
    return {
      index,
      x: cell.x,
      y: cell.y,
      centerX: cell.x + 1,
      centerY: cell.y + 1,
      isMale,
      sex: isMale ? "雄性" : "雌性",
      species,
      isShiny: candidate.isShiny,
      rarityLabel: candidate.isShiny ? "异色" : "非异色",
      status,
      groups: species.groups.join(" / "),
      covered: isMale ? false : Boolean(assignmentPlan.femaleCoverage[index])
    };
  });

  const compatiblePairs = buildCompatiblePairsFromNests(nests, edges);
  const score = summarizeMaterializedPlan(nests, compatiblePairs, inventory);
  const coveredFemaleIndices = new Set(compatiblePairs.map(pair => pair.female.index));
  nests.forEach(nest => {
    if (!nest.isMale) {
      nest.covered = coveredFemaleIndices.has(nest.index);
    }
  });

  const missingSpeciesInInventory = inventory.statuses.reduce((count, status) => (
    status === "missing" ? count + 1 : count
  ), 0);

  return {
    nests,
    compatiblePairs,
    score,
    maleCount,
    femaleCount,
    nestCount,
    theoreticalPairs: maleCount * femaleCount,
    reachableCrossEdges: sexPlan.crossEdgeUpperBound,
    missingSpeciesInInventory
  };
}

function buildPlan(nestCount, maleCount, femaleCount, inventory, targetPriority, onProgress) {
  if (onProgress) {
    onProgress({
      stage: "生成布局骨架",
      percent: 8,
      detail: "正在生成快速候选摆法"
    });
  }

  const rawLayoutCandidates = generateLayoutCandidates(
    nestCount,
    maleCount,
    nestCount <= 10 ? 12 : 8
  );

  if (onProgress) {
    onProgress({
      stage: "压缩布局骨架",
      percent: 16,
      detail: `候选骨架 ${rawLayoutCandidates.length} 组，正在筛选`
    });
  }

  const layoutCandidates = refineLayoutCandidates(
    rawLayoutCandidates,
    maleCount,
    nestCount <= 10 ? 14 : 8
  );

  const allPlans = [];
  let processedLayouts = 0;

  for (const cells of layoutCandidates) {
    const { edges, adjacency } = buildEdges(cells);
    const sexPlan = optimizeSexSplit(nestCount, maleCount, edges, adjacency);
    const assignmentPlans = optimizeWithInventory(
      adjacency,
      sexPlan.maleMask,
      inventory,
      targetPriority
    );

    if (!assignmentPlans || assignmentPlans.length === 0) {
      processedLayouts++;
      if (onProgress) {
        const percent = 16 + Math.round(
          (processedLayouts / Math.max(1, layoutCandidates.length)) * 56
        );
        onProgress({
          stage: "评估库存分配",
          percent,
          detail: `已评估 ${processedLayouts}/${layoutCandidates.length} 组布局`
        });
      }
      continue;
    }

    const materialized = assignmentPlans
      .map(plan => materializePlan(
        cells,
        edges,
        sexPlan,
        plan,
        inventory,
        maleCount,
        femaleCount,
        nestCount
      ))
      .filter(Boolean);

    allPlans.push(...materialized);
    processedLayouts++;

    if (onProgress) {
      const percent = 16 + Math.round(
        (processedLayouts / Math.max(1, layoutCandidates.length)) * 56
      );
      onProgress({
        stage: "评估库存分配",
        percent,
        detail: `已评估 ${processedLayouts}/${layoutCandidates.length} 组布局，保留 ${allPlans.length} 组方案`
      });
    }
  }

  if (allPlans.length === 0) {
    return null;
  }

  if (onProgress) {
    onProgress({
      stage: "固定阵容重排",
      percent: 78,
      detail: "正在快速微调高分方案"
    });
  }

  const relayoutSeeds = [...allPlans]
    .sort((a, b) => compareScores(a.score, b.score, targetPriority))
    .slice(0, nestCount <= 10 ? 3 : 2)
    .map(plan => optimizeLayoutForFixedRoster(plan, inventory, targetPriority));

  for (let index = 0; index < relayoutSeeds.length; index++) {
    allPlans.push(relayoutSeeds[index]);
    if (onProgress) {
      const percent = 78 + Math.round(
        ((index + 1) / Math.max(1, relayoutSeeds.length)) * 14
      );
      onProgress({
        stage: "固定阵容重排",
        percent,
        detail: `已重排 ${index + 1}/${relayoutSeeds.length} 组高分方案`
      });
    }
  }

  const uniquePlans = [...new Map(allPlans.map(plan => {
    const signature = plan.nests
      .map(nest => [
        nest.x,
        nest.y,
        nest.isMale ? "M" : "F",
        nest.species.index,
        nest.isShiny ? "S" : "N"
      ].join(","))
      .join(";");
    return [signature, plan];
  })).values()];

  uniquePlans.sort((a, b) => compareScores(a.score, b.score, targetPriority));

  if (onProgress) {
    onProgress({
      stage: "整理结果",
      percent: 96,
      detail: `共得到 ${uniquePlans.length} 组候选方案`
    });
  }

  return uniquePlans.slice(0, 12);
}

function handleMessage(event) {
  const { type, payload } = event.data;

  if (type === "buildPlan") {
    const { nestCount, maleCount, femaleCount, inventory, targetPriority } = payload;

    try {
      const onProgress = (progress) => {
        self.postMessage({ type: "progress", payload: progress });
      };

      const plans = buildPlan(nestCount, maleCount, femaleCount, inventory, targetPriority, onProgress);

      self.postMessage({ type: "success", payload: plans });
    } catch (error) {
      self.postMessage({ type: "error", payload: error.message });
    }
  }
}

self.onmessage = function(event) {
  if (!isInitialized) {
    pendingMessages.push(event);
    return;
  }

  handleMessage(event);
};

// 启动时加载数据
loadSpeciesData();
