
    const SPECIES = [
      { name: "粉星仔", aliases: ["粉耳星兔", "落陨星兔"], groups: ["妖精"] },
      { name: "粉粉星", aliases: ["小皮球"], groups: ["妖精"] },
      { name: "酷拉", aliases: ["拉特"], groups: ["妖精"] },
      { name: "雪影娃娃", aliases: ["大耳帽兜"], groups: ["妖精", "拟人"] },
      { name: "治愈兔", aliases: ["红绒十字"], groups: ["妖精", "动物"] },
      { name: "格兰球", aliases: [], groups: ["妖精", "植物"] },
      { name: "月牙雪熊", aliases: [], groups: ["动物", "怪兽"] },
      { name: "恶魔狼", aliases: [], groups: ["动物"] },
      { name: "獠牙猪", aliases: ["呼呼猪"], groups: ["动物"] },
      { name: "奇丽花", aliases: [], groups: ["植物"] },
      { name: "燃薪虫", aliases: ["柴渣虫"], groups: ["植物", "昆虫"] },
      { name: "窃光蚊", aliases: ["嗜光嗡嗡"], groups: ["昆虫"] },
      { name: "空空颅", aliases: ["夜宿颅", "夜枭"], groups: ["怪兽"] },
      { name: "机械方方", aliases: [], groups: ["机械", "拟人"] },
      { name: "贝瑟", aliases: ["贝古斯", "贝加尔"], groups: ["机械"] },
      { name: "利灯鱼", aliases: ["双灯鱼"], groups: ["海洋"] },
      { name: "菊花梨", aliases: [], groups: ["植物"] },
      { name: "公平鸽", aliases: [], groups: ["天空"] },
      { name: "恶魔叮", aliases: [], groups: ["妖精"] },
      { name: "尖嘴狐仙", aliases: ["灵狐"], groups: ["动物"] },
      { name: "嘟嘟煲", aliases: [], groups: ["妖精", "大地"] },
      { name: "小独角兽", aliases: [], groups: ["巨灵", "动物"] },
      { name: "小夜", aliases: [], groups: ["妖精", "拟人"] },
      { name: "幽影树", aliases: [], groups: ["妖精", "植物"] },
      { name: "小丑豆豆", aliases: ["小丑公爵"], groups: ["妖精", "拟人"] },
      { name: "炫光迪迪", aliases: ["霹雳迪迪"], groups: ["动物"] },
      { name: "烟花团", aliases: ["烟花伯爵"], groups: ["妖精"] },
      { name: "咕咕帽", aliases: ["咕德帽帽"], groups: ["妖精"] },
      { name: "牵线木偶", aliases: ["帅帅魔偶"], groups: ["妖精", "拟人"] },
      { name: "加油海葵", aliases: ["加油蟹"], groups: ["妖精", "海洋"] },
      { name: "猴麦仔", aliases: ["音碟吼"], groups: ["动物", "机械"] },
      { name: "小鼓象", aliases: ["巨鼓象"], groups: ["动物", "巨灵"] }
    ];

    const STORAGE_KEY = "roco_shiny_planner_state_v1";
    const SINGLE_SHINY_PERCENT_CENTI = 36;
    const DOUBLE_SHINY_PERCENT_CENTI = 72;
    const STATUS_OPTIONS = [
      { value: "missing", label: "这次想生这个异色" },
      { value: "ignore", label: "这次不考虑这个异色" }
    ];
    const GROUP_ORDER = ["妖精", "动物", "植物", "昆虫", "怪兽", "机械", "拟人", "海洋", "天空", "大地", "巨灵"];
    const GROUP_MASK = Object.fromEntries(GROUP_ORDER.map((group, index) => [group, 1 << index]));
    const SPECIES_BY_INDEX = SPECIES.map((species, index) => ({
      ...species,
      index,
      label: species.aliases.length ? `${species.name}（${species.aliases.join(" / ")}）` : species.name,
      mask: species.groups.reduce((sum, group) => sum | GROUP_MASK[group], 0)
    }));

    function getExpectedShinyPercentCenti(score) {
      return score.expectedShinyPercentCenti ?? (score.shinyChanceScore * SINGLE_SHINY_PERCENT_CENTI);
    }

    function getShinyUsage(score) {
      return score.shinyUsage ?? ((score.shinyMaleUsage || 0) + (score.shinyFemaleUsage || 0));
    }

    const maleInput = document.getElementById("maleCount");
    const femaleInput = document.getElementById("femaleCount");
    const nestInput = document.getElementById("nestCount");
    const autoFieldInput = document.getElementById("autoField");
    const solveEngineInput = document.getElementById("solveEngine");
    const targetPriorityInput = document.getElementById("targetPriority");
    const solveButton = document.getElementById("solveButton");
    const presetButton = document.getElementById("presetButton");
    const missingAllButton = document.getElementById("missingAllButton");
    const saveButton = document.getElementById("saveButton");
    const statusEl = document.getElementById("status");
    const progressPanelEl = document.getElementById("progressPanel");
    const progressFillEl = document.getElementById("progressFill");
    const progressMetaEl = document.getElementById("progressMeta");
    const overviewEl = document.getElementById("overview");
    const solutionSelectEl = document.getElementById("solutionSelect");
    const solutionNoteEl = document.getElementById("solutionNote");
    const statsEl = document.getElementById("stats");
    const inventoryBody = document.getElementById("inventoryBody");
    const boardEl = document.getElementById("board");
    const nestTableBody = document.getElementById("nestTableBody");
    const pairList = document.getElementById("pairList");
    let currentPlans = [];
    const SOLVER_API_URL = "http://127.0.0.1:8765/solve";
    const SOLVER_ASYNC_API_URL = "http://127.0.0.1:8765/solve_async";
    const SOLVER_JOB_API_BASE = "http://127.0.0.1:8765/jobs";

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
      const { adjacency } = buildEdges(cells);
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

  // 加速版：原来是 n<=10 ? 24 : 18
  const beamWidth = n <= 10 ? 12 : 8;

  for (let size = 1; size < n; size++) {
    const nextMap = new Map();

    // 加速版：原来是 14 / 10 / 8
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

    function renderInventoryRows() {
      inventoryBody.innerHTML = SPECIES_BY_INDEX.map(species => `
        <tr>
          <td>${species.label}</td>
          <td>${species.groups.join(" / ")}</td>
          <td><input class="tiny shiny-male" data-index="${species.index}" type="number" min="0" max="99" value="0"></td>
          <td><input class="tiny shiny-female" data-index="${species.index}" type="number" min="0" max="99" value="0"></td>
          <td>
            <select class="inventory-status" data-index="${species.index}">
              ${STATUS_OPTIONS.map(option => `<option value="${option.value}" ${option.value === "missing" ? "selected" : ""}>${option.label}</option>`).join("")}
            </select>
          </td>
        </tr>
      `).join("");
    }

    function syncInputs() {
      const autoField = autoFieldInput.value;
      const male = Number(maleInput.value) || 0;
      const female = Number(femaleInput.value) || 0;
      const nest = Number(nestInput.value) || 0;
      if (autoField === "female") {
        femaleInput.value = Math.max(0, nest - male);
      } else if (autoField === "male") {
        maleInput.value = Math.max(0, nest - female);
      } else {
        nestInput.value = Math.max(0, male + female);
      }
    }

    function getInventoryConfig() {
      const shinyMaleStocks = Array(SPECIES_BY_INDEX.length).fill(0);
      const shinyFemaleStocks = Array(SPECIES_BY_INDEX.length).fill(0);
      const statuses = Array(SPECIES_BY_INDEX.length).fill("missing");

      document.querySelectorAll(".shiny-male").forEach(input => {
        shinyMaleStocks[Number(input.dataset.index)] = Math.max(0, Number(input.value) || 0);
      });
      document.querySelectorAll(".shiny-female").forEach(input => {
        shinyFemaleStocks[Number(input.dataset.index)] = Math.max(0, Number(input.value) || 0);
      });
      document.querySelectorAll(".inventory-status").forEach(select => {
        statuses[Number(select.dataset.index)] = select.value;
      });

      return {
        shinyMaleStocks,
        shinyFemaleStocks,
        statuses,
        normalTargetFemaleStock: Number(femaleInput.value) || 20,
        normalTargetMaleStock: Number(maleInput.value) || 20
      };
    }

    function saveState() {
      const payload = {
        maleCount: maleInput.value,
        femaleCount: femaleInput.value,
        nestCount: nestInput.value,
        autoField: autoFieldInput.value,
        solveEngine: solveEngineInput.value,
        targetPriority: targetPriorityInput.value,
        inventory: getInventoryConfig()
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      statusEl.className = "status good";
      statusEl.textContent = "当前配置已保存到浏览器。";
    }

    function loadState() {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return;
      }
      try {
        const state = JSON.parse(raw);
        maleInput.value = state.maleCount ?? maleInput.value;
        femaleInput.value = state.femaleCount ?? femaleInput.value;
        nestInput.value = state.nestCount ?? nestInput.value;
        autoFieldInput.value = state.autoField ?? autoFieldInput.value;
        solveEngineInput.value = state.solveEngine === "local" ? "browser" : (state.solveEngine ?? solveEngineInput.value);
        targetPriorityInput.value = state.targetPriority ?? targetPriorityInput.value;
        if (state.inventory) {
          document.querySelectorAll(".shiny-male").forEach(input => {
            input.value = state.inventory.shinyMaleStocks?.[Number(input.dataset.index)]
              ?? state.inventory.maleStocks?.[Number(input.dataset.index)]
              ?? 0;
          });
          document.querySelectorAll(".shiny-female").forEach(input => {
            input.value = state.inventory.shinyFemaleStocks?.[Number(input.dataset.index)]
              ?? state.inventory.femaleStocks?.[Number(input.dataset.index)]
              ?? 0;
          });
          document.querySelectorAll(".inventory-status").forEach(select => {
            select.value = state.inventory.statuses?.[Number(select.dataset.index)] ?? "missing";
          });
        }
      } catch (error) {
        console.error(error);
      }
    }

    function setProgress(percent, message = "") {
      const value = Math.max(0, Math.min(100, Number(percent) || 0));
      progressPanelEl.hidden = false;
      progressFillEl.style.width = `${value}%`;
      progressMetaEl.textContent = message;
    }

    function hideProgress() {
      progressPanelEl.hidden = true;
      progressFillEl.style.width = "0%";
      progressMetaEl.textContent = "";
    }

    async function yieldToUi() {
      // 页面在后台时，不用 setTimeout 让出主线程；
      // 否则浏览器会限制后台计时器，导致计算像暂停一样。
      if (document.visibilityState === "hidden") {
        return;
      }

      // 页面在前台时仍然让出一点时间，避免进度条和界面完全卡死。
      await new Promise(resolve => setTimeout(resolve, 0));
    }

    function fillDemoInventory() {
      const demo = [
        { name: "治愈兔", shinyMale: 2, shinyFemale: 0, status: "missing" },
        { name: "雪影娃娃", shinyMale: 1, shinyFemale: 1, status: "missing" },
        { name: "格兰球", shinyMale: 1, shinyFemale: 0, status: "missing" },
        { name: "粉粉星", shinyMale: 1, shinyFemale: 1, status: "ignore" },
        { name: "月牙雪熊", shinyMale: 0, shinyFemale: 0, status: "ignore" },
        { name: "燃薪虫", shinyMale: 1, shinyFemale: 0, status: "ignore" },
        { name: "机械方方", shinyMale: 1, shinyFemale: 0, status: "ignore" }
      ];
      document.querySelectorAll(".shiny-male").forEach(input => { input.value = 0; });
      document.querySelectorAll(".shiny-female").forEach(input => { input.value = 0; });
      document.querySelectorAll(".inventory-status").forEach(select => { select.value = "ignore"; });
      for (const item of demo) {
        const species = SPECIES_BY_INDEX.find(entry => entry.name === item.name);
        if (!species) {
          continue;
        }
        document.querySelector(`.shiny-male[data-index="${species.index}"]`).value = item.shinyMale;
        document.querySelector(`.shiny-female[data-index="${species.index}"]`).value = item.shinyFemale;
        document.querySelector(`.inventory-status[data-index="${species.index}"]`).value = item.status;
      }
      statusEl.className = "status warn";
      statusEl.textContent = "已填入演示库存，你可以在这个基础上继续改。";
    }

    function setAllMissing() {
      document.querySelectorAll(".inventory-status").forEach(select => {
        select.value = "missing";
      });
    }

    function validateInputs() {
      syncInputs();
      const maleCount = Number(maleInput.value);
      const femaleCount = Number(femaleInput.value);
      const nestCount = Number(nestInput.value);
      if (!Number.isInteger(maleCount) || !Number.isInteger(femaleCount) || !Number.isInteger(nestCount)) {
        throw new Error("数量必须是整数。");
      }
      if (maleCount < 0 || femaleCount < 0 || nestCount <= 0) {
        throw new Error("数量不能为负，小窝总数至少为 1。");
      }
      if (maleCount + femaleCount !== nestCount) {
        throw new Error("当前数量不满足 雄性 + 雌性 = 小窝总数。");
      }
      if (nestCount > 20) {
        throw new Error("为了保证页面流畅，当前版本建议小窝总数不超过 20。");
      }
      const inventory = getInventoryConfig();
      const targetFallbackFemaleCount = inventory.statuses.reduce((sum, status, index) => (
        sum + ((status === "missing" && inventory.shinyFemaleStocks[index] === 0) ? 1 : 0)
      ), 0);
      const totalFemale = inventory.shinyFemaleStocks.reduce((sum, value) => sum + value, 0) + targetFallbackFemaleCount;
      
      if (totalFemale < femaleCount) {
        throw new Error(`你当前可用的雌性总数只有 ${totalFemale}。这里会自动把“想生但没有异色母本”的精灵视为可用普通母本；如果还不够，就请减少雌窝数量或增加异色母本。`);
      }
      return {
        maleCount,
        femaleCount,
        nestCount,
        inventory,
        solveEngine: solveEngineInput.value,
        targetPriority: targetPriorityInput.value
      };
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
        // 'owned' status removed: 有异色数量会通过 shinyFemaleStocks/shinyMaleStocks 表示，无需单独分支
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
        score += 320;
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
          totalPairs: 0,
          targetPairs: 0,
          shinyChanceScore: 0,
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
        if (left.isMale === right.isMale) {
          continue;
        }
        if ((left.species.mask & right.species.mask) === 0) {
          continue;
        }
        if (!left.isShiny && !right.isShiny) {
          continue;
        }
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
        if (!isLegalLayout(cells)) {
          return null;
        }
        const { edges, adjacency } = buildEdges(cells);
        const sexPlan = optimizeSexSplit(plan.nestCount, plan.maleCount, edges, adjacency);
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
        if (!candidatePlan) {
          continue;
        }
        if (isBetterScore(candidatePlan.score, bestPlan.score, targetPriority)) {
          bestPlan = candidatePlan;
        }
      }
      return bestPlan;
    }

    function materializePlan(cells, edges, sexPlan, assignmentPlan, inventory, maleCount, femaleCount, nestCount) {
      if (!assignmentPlan) {
        return null;
      }
      if (!isLegalLayout(cells)) {
        return null;
      }

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

    async function buildPlan(nestCount, maleCount, femaleCount, inventory, targetPriority, onProgress) {
    if (onProgress) {
      onProgress({
        stage: "生成布局骨架",
        percent: 8,
        detail: "正在生成快速候选摆法..."
      });
    }

    // 加速版：原来是 nestCount <= 10 ? 32 : 24
    const rawLayoutCandidates = generateLayoutCandidates(
      nestCount,
      maleCount,
      nestCount <= 10 ? 12 : 8
    );

    if (onProgress) {
      onProgress({
        stage: "压缩布局骨架",
        percent: 16,
        detail: `候选骨架 ${rawLayoutCandidates.length} 组，正在筛选...`
      });
    }

    // 加速版：原来是 nestCount <= 10 ? 36 : 24
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

        await yieldToUi();
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

      await yieldToUi();
    }

    if (allPlans.length === 0) {
      return null;
    }

    if (onProgress) {
      onProgress({
        stage: "固定阵容重排",
        percent: 78,
        detail: "正在快速微调高分方案..."
      });
    }

    // 加速版：原来是 nestCount <= 10 ? 10 : 6
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

      await yieldToUi();
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

    function buildApiPayload(maleCount, femaleCount, nestCount, inventory) {
      return {
        maleCount,
        femaleCount,
        nestCount,
        inventory
      };
    }

    function normalizeApiResult(result) {
      const assignmentsByPosition = new Map(result.assignments.map(item => [item.position_id, item]));
      const nests = result.assignments.map(item => ({
        index: item.position_id,
        x: item.x,
        y: item.y,
        centerX: item.x + 1,
        centerY: item.y + 1,
        isMale: item.sex === "male",
        sex: item.sex_label,
        species: {
          index: item.species_index,
          name: item.species_name,
          label: item.species_label,
          groups: item.groups
        },
        isShiny: item.is_shiny,
        rarityLabel: item.rarity_label === "普通" ? "非异色" : item.rarity_label,
        status: item.role,
        groups: item.groups.join(" / "),
        covered: item.sex === "male" ? false : result.covered_target_species.includes(item.species_name)
      }));

      const compatiblePairs = result.feasible_mating_edges.map(edge => {
        const female = assignmentsByPosition.get(edge.female_position_id);
        const male = assignmentsByPosition.get(edge.male_position_id);
        return {
          female: {
            species: { name: female.species_name, label: female.species_label },
            rarityLabel: female.rarity_label,
            status: female.role
          },
          male: {
            species: { name: male.species_name, label: male.species_label },
            rarityLabel: male.rarity_label
          },
          distance: edge.distance
        };
      });

      const singleShinyPairs = compatiblePairs.filter(pair => (
        (pair.female.rarityLabel === "异色") !== (pair.male.rarityLabel === "异色")
      )).length;
      const doubleShinyPairs = compatiblePairs.filter(pair => (
        pair.female.rarityLabel === "异色" && pair.male.rarityLabel === "异色"
      )).length;
      const expectedShinyPercentCenti =
        result.objective_values.expected_shiny_percent_centi
        ?? ((singleShinyPairs * SINGLE_SHINY_PERCENT_CENTI) + (doubleShinyPairs * DOUBLE_SHINY_PERCENT_CENTI));
      const shinyUsage = nests.filter(nest => nest.isShiny).length;

      return {
        nests,
        compatiblePairs,
        score: {
          coveredMissingSpecies: result.objective_values.covered_target_species ?? result.objective_values.Z1,
          targetPairs: result.objective_values.target_pairs ?? result.objective_values.Z2,
          shinyChanceScore: result.objective_values.double_shiny_score ?? result.objective_values.Z4 ?? result.objective_values.Z3,
          totalPairs: result.objective_values.total_pairs ?? result.objective_values.Z3 ?? result.feasible_mating_edges.length,
          coveredMissingFemales: result.covered_target_species.length,
          expectedShinyPercentCenti,
          singleShinyPairs,
          doubleShinyPairs,
          shinyUsage
        },
        maleCount: result.meta.max_male,
        femaleCount: result.meta.max_female,
        nestCount: result.meta.max_nests,
        theoreticalPairs: result.meta.max_male * result.meta.max_female,
        reachableCrossEdges: result.feasible_mating_edges.length,
        missingSpeciesInInventory: result.covered_target_species.length,
        solverStatus: result.solver_status,
        isGloballyOptimal: result.is_globally_optimal,
        solveSeconds: result.solve_seconds
      };
    }

    function formatCentiPercent(value) {
      return `${(value / 100).toFixed(2)}%`;
    }

    async function trySolveWithApi(maleCount, femaleCount, nestCount, inventory) {
      const createResponse = await fetch(SOLVER_ASYNC_API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildApiPayload(maleCount, femaleCount, nestCount, inventory))
      });
      if (!createResponse.ok) {
        const detail = await createResponse.json().catch(() => ({}));
        const error = new Error(detail.detail || "本地求解服务返回了错误。");
        error.name = "SolverApiError";
        error.status = createResponse.status;
        throw error;
      }
      const created = await createResponse.json();
      const jobId = created.job_id;

      while (true) {
        await new Promise(resolve => setTimeout(resolve, 700));
        const jobResponse = await fetch(`${SOLVER_JOB_API_BASE}/${jobId}`);
        if (!jobResponse.ok) {
          throw new Error("读取求解进度失败。");
        }
        const job = await jobResponse.json();
        if (job.status === "running" || job.status === "queued") {
          statusEl.className = "status warn";
          statusEl.textContent = `正在精确求解：${job.stage}（${job.progress_current || 0}/${job.progress_total || 4}），已等待 ${job.elapsed_seconds || 0} 秒。`;
          continue;
        }
        if (job.status === "error") {
          const error = new Error(job.error || "本地求解服务返回了错误。");
          error.name = "SolverApiError";
          throw error;
        }
        const result = job.result;
        if (!result) {
          throw new Error("求解任务没有返回结果。");
        }
        return [normalizeApiResult(result)];
      }
    }

    function renderStats(plan) {
      const items = [
        { label: "库存里可上阵的缺失母本种类", value: plan.missingSpeciesInInventory },
        { label: "本次补到的缺失异色种类", value: plan.score.coveredMissingSpecies },
        { label: "缺失目标配对次数", value: plan.score.targetPairs },
        { label: "累计异色概率", value: formatCentiPercent(plan.score.expectedShinyPercentCenti ?? (plan.score.shinyChanceScore * SINGLE_SHINY_PERCENT_CENTI)) },
        { label: "整体可孵化配对", value: plan.compatiblePairs.length }
      ];
      statsEl.innerHTML = items.map(item => `
        <article class="stat">
          <span>${item.label}</span>
          <strong>${item.value}</strong>
        </article>
      `).join("");

      const shinyMothers = plan.nests.filter(nest => !nest.isMale && nest.isShiny).length;
      const fallbackMothers = plan.nests.filter(nest => !nest.isMale && !nest.isShiny).length;
      overviewEl.innerHTML = `
        <strong>这套方案优先补 ${plan.score.coveredMissingSpecies} 种目标异色，同时保留 ${plan.compatiblePairs.length} 条可孵化连线。</strong>
        <div class="overview-grid">
          <div class="overview-chip">异色母本 ${shinyMothers} 只，普通替代母本 ${fallbackMothers} 只。</div>
          <div class="overview-chip">目标配对 ${plan.score.targetPairs} 次，说明重点目标没有被稀释掉。</div>
          <div class="overview-chip">单异色配对 ${plan.score.singleShinyPairs ?? 0} 次按 0.72%，双异色配对 ${plan.score.doubleShinyPairs ?? 0} 次按 1.44%，累计异色概率 ${formatCentiPercent(plan.score.expectedShinyPercentCenti ?? (plan.score.shinyChanceScore * SINGLE_SHINY_PERCENT_CENTI))}。</div>
          ${plan.solverStatus ? `<div class="overview-chip">求解状态 ${plan.solverStatus}，${plan.isGloballyOptimal ? "已证明最优" : "当前未证明最优"}，耗时 ${plan.solveSeconds}s。</div>` : ""}
        </div>
      `;
    }

    function renderSolutionPicker(plans) {
      currentPlans = plans;
      solutionSelectEl.innerHTML = plans.map((plan, index) => `
        <option value="${index}">
          方案 ${index + 1}：补 ${plan.score.coveredMissingSpecies} 种，目标配对 ${plan.score.targetPairs}，总配对 ${plan.compatiblePairs.length}
        </option>
      `).join("");
      solutionNoteEl.textContent = plans.length > 1
        ? "这些都是当前输入下的高分候选方案，已经按“先种类、再目标蛋数、再总蛋数、最后双异色”排好序。"
        : "当前输入下只保留到 1 组高分候选方案。";
    }

    function renderPlan(plan) {
      renderStats(plan);
      renderBoard(plan);
      renderNestTable(plan);
      renderPairs(plan);
    }

    function renderBoard(plan) {
      const margin = 46;
      const unit = 56;
      const nestSize = unit * 2;
      const maxCellX = Math.max(...plan.nests.map(nest => nest.x)) + 2;
      const maxCellY = Math.max(...plan.nests.map(nest => nest.y)) + 2;
      const width = maxCellX * unit + margin * 2;
      const height = maxCellY * unit + margin * 2;

      const lines = plan.compatiblePairs.map(pair => {
        const x1 = margin + pair.female.centerX * unit;
        const y1 = margin + pair.female.centerY * unit;
        const x2 = margin + pair.male.centerX * unit;
        const y2 = margin + pair.male.centerY * unit;
        return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(234, 155, 82, 0.54)" stroke-width="10" stroke-linecap="round" />`;
      }).join("");

      const gridLines = [];
      for (let x = 0; x <= maxCellX; x++) {
        const px = margin + x * unit;
        gridLines.push(`<line x1="${px}" y1="${margin}" x2="${px}" y2="${height - margin}" stroke="rgba(31,52,64,0.08)" stroke-width="1" />`);
      }
      for (let y = 0; y <= maxCellY; y++) {
        const py = margin + y * unit;
        gridLines.push(`<line x1="${margin}" y1="${py}" x2="${width - margin}" y2="${py}" stroke="rgba(31,52,64,0.08)" stroke-width="1" />`);
      }

      const nests = plan.nests.map(nest => {
        const x = margin + nest.x * unit;
        const y = margin + nest.y * unit;
        const fill = nest.isMale ? "rgba(113, 181, 198, 0.82)" : "rgba(238, 147, 132, 0.82)";
        const title = `${nest.sex} ${nest.rarityLabel} ${nest.species.label}\n状态：${nest.status}\n蛋组：${nest.groups}`;
        const stroke = !nest.isMale && nest.status === "missing"
          ? "rgba(210, 94, 83, 0.75)"
          : "rgba(31, 52, 64, 0.16)";
        const strokeWidth = !nest.isMale && nest.status === "missing" ? 3 : 2;
        return `
          <g>
            <title>${title}</title>
            <rect x="${x}" y="${y}" width="${nestSize}" height="${nestSize}" rx="20" ry="20"
              fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" />
            <text x="${x + 16}" y="${y + 34}" font-size="13" font-weight="700" fill="#ffffff">${nest.rarityLabel}</text>
            <text x="${x + 16}" y="${y + 58}" font-size="16" font-weight="700" fill="#ffffff">${nest.sex}</text>
            <text x="${x + 16}" y="${y + 84}" font-size="18" font-weight="700" fill="#ffffff">${nest.species.name}</text>
          </g>
        `;
      }).join("");

      boardEl.setAttribute("viewBox", `0 0 ${width} ${height}`);
      boardEl.innerHTML = `<g>${gridLines.join("")}</g><g>${lines}</g><g>${nests}</g>`;
    }

    function renderNestTable(plan) {
      nestTableBody.innerHTML = plan.nests.map(nest => `
        <tr>
          <td><span class="badge ${nest.isMale ? "male" : "female"}">${nest.sex}</span></td>
          <td>${nest.rarityLabel}</td>
          <td>${nest.species.label}</td>
          <td>${nest.groups}</td>
          <td>(${nest.x}, ${nest.y})</td>
          <td>${nest.isMale ? "负责桥接和开边" : (nest.status === "missing" ? "目标母本" : "补位母本")}</td>
        </tr>
      `).join("");
    }

    function renderPairs(plan) {
      if (plan.compatiblePairs.length === 0) {
        pairList.innerHTML = `<div class="pair-chip">当前库存和数量组合下，没有找到可孵化的异色配对。</div>`;
        return;
      }
      pairList.innerHTML = plan.compatiblePairs.map((pair, index) => `
        <div class="pair-chip">
          <strong>配对 ${index + 1}</strong><br>
          母本：${pair.female.rarityLabel}${pair.female.species.label}（${pair.female.status === "missing" ? "这次想生" : "已拥有，可补位"}）<br>
          公本：${pair.male.rarityLabel}${pair.male.species.label}<br>
          距离：${pair.distance}，子代种类：${pair.female.species.name}
        </div>
      `).join("");
    }

    async function runPlanner() {
      try {
        const { maleCount, femaleCount, nestCount, inventory, solveEngine, targetPriority } = validateInputs();
        setProgress(2, solveEngine === "local" ? "正在连接本地求解服务..." : "正在准备浏览器求解...");
        statusEl.className = "status warn";
        statusEl.textContent = solveEngine === "local"
          ? "正在计算推荐方案，当前使用本地精确求解。"
          : "正在计算推荐方案，当前使用网页模型求解。";

        let plans;
        let usedFallback = false;
        if (solveEngine === "local") {
          try {
            plans = await trySolveWithApi(maleCount, femaleCount, nestCount, inventory);
          } catch (apiError) {
            const shouldFallback = apiError.name !== "SolverApiError";
            if (!shouldFallback) {
              throw apiError;
            }
            usedFallback = true;
            plans = await buildPlan(nestCount, maleCount, femaleCount, inventory, targetPriority, progress => {
              setProgress(progress.percent, `${progress.stage}：${progress.detail}`);
              statusEl.className = "status warn";
              statusEl.textContent = `${progress.stage}：${progress.detail}`;
            });
            if (!plans || plans.length === 0) {
              throw apiError;
            }
          }
        } else {
          plans = await buildPlan(nestCount, maleCount, femaleCount, inventory, targetPriority, progress => {
            setProgress(progress.percent, `${progress.stage}：${progress.detail}`);
            statusEl.className = "status warn";
            statusEl.textContent = `${progress.stage}：${progress.detail}`;
          });
          if (!plans || plans.length === 0) {
            throw new Error("网页模型没有找到可用方案。");
          }
        }

        statusEl.className = "status good";
        setProgress(100, "计算完成。");
        statusEl.textContent = solveEngine === "browser"
          ? `已完成：当前使用网页模型求解，共找到 ${plans.length} 组候选方案。`
          : (usedFallback
            ? `已完成：本地精确求解服务未连接，当前展示的是网页内置近似方案，共找到 ${plans.length} 组高分候选。`
            : (plans[0] && plans[0].solverStatus === "SAFE_FALLBACK"
              ? "已完成：精确模型这次没有成功求出最优解，当前展示的是保底可摆方案。"
              : "已完成：当前使用本地精确求解，默认展示第 1 组最优方案。"));
        renderSolutionPicker(plans);
        renderPlan(plans[0]);
      } catch (error) {
        hideProgress();
        statusEl.className = "status error";
        statusEl.textContent = error.message;
        currentPlans = [];
        solutionSelectEl.innerHTML = "";
        solutionNoteEl.textContent = "这里会列出同一组输入下的多套高分摆法，排序规则是先看异色目标种类数，再看目标配对数和总配对数。";
        overviewEl.innerHTML = "<strong>这里会显示本次方案的结论摘要。</strong>";
        statsEl.innerHTML = "";
        boardEl.innerHTML = "";
        nestTableBody.innerHTML = "";
        pairList.innerHTML = "";
      }
    }

    renderInventoryRows();
    loadState();
    syncInputs();

    [maleInput, femaleInput, nestInput, autoFieldInput].forEach(element => {
      element.addEventListener("input", syncInputs);
      element.addEventListener("change", syncInputs);
    });
    solveButton.addEventListener("click", runPlanner);
    solutionSelectEl.addEventListener("change", () => {
      const index = Number(solutionSelectEl.value) || 0;
      if (currentPlans[index]) {
        renderPlan(currentPlans[index]);
      }
    });
    presetButton.addEventListener("click", fillDemoInventory);
    missingAllButton.addEventListener("click", setAllMissing);
    saveButton.addEventListener("click", saveState);

  
