﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿
    // 全局变量（等待数据加载后初始化）
    let SPECIES = [];
    let GROUP_ORDER = [];
    let GROUP_MASK = {};
    let SPECIES_BY_INDEX = [];
    let SINGLE_SHINY_PERCENT_CENTI = 36;
    let STORAGE_KEY = "roco_shiny_planner_state_v1";

    const STATUS_OPTIONS = [
      { value: "missing", label: "这次想生这个异色" },
      { value: "owned", label: "这个异色我已经有了，但还能拿来配" },
      { value: "ignore", label: "这次不考虑这个异色" }
    ];

    const maleInput = document.getElementById("maleCount");
    const femaleInput = document.getElementById("femaleCount");
    const nestInput = document.getElementById("nestCount");
    const targetPriorityInput = document.getElementById("targetPriority");
    const solveButton = document.getElementById("solveButton");
    const presetButton = document.getElementById("presetButton");
    const missingAllButton = document.getElementById("missingAllButton");
    const saveButton = document.getElementById("saveButton");
    const statusEl = document.getElementById("status");
    const loadingOverlay = document.getElementById("loadingOverlay");
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
        STORAGE_KEY = data.STORAGE_KEY;
        
        GROUP_MASK = Object.fromEntries(GROUP_ORDER.map((group, index) => [group, 1 << index]));
        SPECIES_BY_INDEX = SPECIES.map((species, index) => ({
          ...species,
          index,
          label: species.aliases.length ? `${species.name}（${species.aliases.join(" / ")}）` : species.name,
          mask: species.groups.reduce((sum, group) => sum | GROUP_MASK[group], 0)
        }));
        
        return true;
      } catch (error) {
        console.error('加载精灵数据失败:', error);
        statusEl.className = "status error";
        statusEl.textContent = '加载精灵数据失败，请刷新页面重试';
        return false;
      }
    }

    // 更新库存输入框的高亮状态
    function updateStockHighlight() {
      document.querySelectorAll(".shiny-male, .shiny-female").forEach(input => {
        const count = Number(input.value) || 0;
        if (count > 0) {
          input.classList.add("has-stock");
        } else {
          input.classList.remove("has-stock");
        }
      });
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

      document.querySelectorAll(".shiny-male, .shiny-female").forEach(input => {
        input.addEventListener("input", function() {
          const index = this.dataset.index;
          const maleInput = document.querySelector(`.shiny-male[data-index="${index}"]`);
          const femaleInput = document.querySelector(`.shiny-female[data-index="${index}"]`);
          const statusSelect = document.querySelector(`.inventory-status[data-index="${index}"]`);
          const maleCount = Number(maleInput.value) || 0;
          const femaleCount = Number(femaleInput.value) || 0;
          if (maleCount > 0 || femaleCount > 0) {
            statusSelect.value = "owned";
          } else {
            statusSelect.value = "missing";
          }
          // 更新高亮状态
          updateStockHighlight();
          // 自动保存到localStorage
          saveState();
        });
      });

      // 添加状态选择的自动保存
      document.querySelectorAll(".inventory-status").forEach(select => {
        select.addEventListener("change", function() {
          saveState();
        });
      });

      // 初始化高亮状态
      updateStockHighlight();
    }

    function syncInputs() {
      const male = Number(maleInput.value) || 0;
      const female = Number(femaleInput.value) || 0;
      const nest = Number(nestInput.value) || 0;
      femaleInput.value = Math.max(0, nest - male);
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

    function saveState(showMessage = false) {
      const payload = {
        maleCount: maleInput.value,
        femaleCount: femaleInput.value,
        nestCount: nestInput.value,
        targetPriority: targetPriorityInput.value,
        inventory: getInventoryConfig()
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      // 只在手动保存时显示提示消息
      if (showMessage) {
        statusEl.className = "status good";
        statusEl.textContent = "当前配置已保存到浏览器本地存储,下次访问会自动恢复。";
      }
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
        autoUpdateStatusFromStock();
        // 加载保存的状态后,更新高亮显示
        updateStockHighlight();
      } catch (error) {
        console.error(error);
      }
    }

    function autoUpdateStatusFromStock() {
      document.querySelectorAll(".shiny-male, .shiny-female").forEach(input => {
        const index = input.dataset.index;
        const maleInputEl = document.querySelector(`.shiny-male[data-index="${index}"]`);
        const femaleInputEl = document.querySelector(`.shiny-female[data-index="${index}"]`);
        const statusSelect = document.querySelector(`.inventory-status[data-index="${index}"]`);
        const maleCount = Number(maleInputEl?.value) || 0;
        const femaleCount = Number(femaleInputEl?.value) || 0;
        if (maleCount > 0 || femaleCount > 0) {
          statusSelect.value = "owned";
        } else {
          statusSelect.value = "missing";
        }
      });
    }

    function setProgress(percent, message = "") {
      const value = Math.max(0, Math.min(100, Number(percent) || 0));
      // 显示loading overlay
      loadingOverlay.classList.add('active');
      progressFillEl.style.width = `${value}%`;
      progressMetaEl.textContent = message;
    }

    function hideProgress() {
      loadingOverlay.classList.remove('active');
      progressFillEl.style.width = "0%";
      progressMetaEl.textContent = "";
    }

    function fillDemoInventory() {
      const demo = [
        { name: "治愈兔", shinyMale: 2, shinyFemale: 0, status: "missing" },
        { name: "雪影娃娃", shinyMale: 1, shinyFemale: 1, status: "missing" },
        { name: "格兰种子", shinyMale: 1, shinyFemale: 0, status: "missing" },
        { name: "粉粉星", shinyMale: 1, shinyFemale: 1, status: "owned" },
        { name: "月牙雪熊", shinyMale: 0, shinyFemale: 0, status: "owned" },
        { name: "燃薪虫", shinyMale: 1, shinyFemale: 0, status: "owned" },
        { name: "机械方方", shinyMale: 1, shinyFemale: 0, status: "owned" }
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
      
      // --- 基础格式与数量校验 ---
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
      
      // --- 边界条件拦截 ---
      // 1. 统计真实可用的异色总数
      const totalShinyMales = inventory.shinyMaleStocks.reduce((sum, count) => sum + count, 0);
      const totalShinyFemales = inventory.shinyFemaleStocks.reduce((sum, count) => sum + count, 0);

      // 2. 检查是否有明确的目标（防止"贤者模式"和"全员拉黑"）
      const hasTarget = inventory.statuses.some(status => status === "missing");
      const allIgnored = inventory.statuses.every(status => status === "ignore");
      
      if (allIgnored) {
        throw new Error("计算中止：你把所有精灵都设置成了【不考虑】，无兵可用，请至少保留一些可用的精灵。");
      }
      if (!hasTarget) {
        throw new Error("计算中止：你没有把任何精灵标记为【这次想生】。如果没有目标，规划器就失去了意义，请至少指定一个目标！");
      }

      // 3. 检查异色资源是否枯竭
      if (totalShinyMales === 0 && totalShinyFemales === 0) {
        throw new Error("计算中止：库存里没有任何异色精灵！普通+普通生不出异色蛋，请先去抓几只异色再来规划。");
      }

      // 4. 检查无效占位（没异色的一方，窝的数量不能超过另一方的异色数量）
      if (totalShinyMales === 0 && femaleCount > totalShinyFemales) {
        throw new Error(`配置无效：没有【异色公本】做桥梁。你只有 ${totalShinyFemales} 只【异色母本】，却放了 ${femaleCount} 个雌性小窝，多出来的雌窝绝对生不出异色。请减少雌窝数量！`);
      }
      if (totalShinyFemales === 0 && maleCount > totalShinyMales) {
        throw new Error(`配置无效：没有【异色母本】做桥梁。你只有 ${totalShinyMales} 只【异色公本】，却放了 ${maleCount} 个雄性小窝，多出来的雄窝纯属浪费。请减少雄窝数量！`);
      }

      // 5. 检查普通母本兜底是否足够
      const targetFallbackFemaleCount = inventory.statuses.reduce((sum, status, index) => (
        sum + ((status === "missing" && inventory.shinyFemaleStocks[index] === 0) ? 1 : 0)
      ), 0);
      const totalFemale = inventory.shinyFemaleStocks.reduce((sum, value) => sum + value, 0) + targetFallbackFemaleCount;
      
      if (totalFemale < femaleCount) {
        throw new Error(`雌性总数不足！你当前可用的雌性只有 ${totalFemale} 只，不够填满 ${femaleCount} 个雌窝。请减少雌窝数量，或增加异色母本数量。`);
      }
      
      return { maleCount, femaleCount, nestCount, inventory, targetPriority: targetPriorityInput.value };
    }

    function formatCentiPercent(value) {
      return `${(value / 100).toFixed(2)}%`;
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

    function runPlanner() {
  try {
    console.log("开始计算...");
    const { maleCount, femaleCount, nestCount, inventory, targetPriority } = validateInputs();
    console.log("参数验证通过：", { maleCount, femaleCount, nestCount, targetPriority });
    
    setProgress(2, "正在唤醒多线程计算引擎...");
    statusEl.className = "status warn";
    statusEl.textContent = "多线程计算中，你可以自由滑动页面...";

    console.log("创建Worker...");
    const worker = new Worker("./roco_shiny_planner_worker.js");
    
    // 【修复点】：在异步回调中增加错误捕获，确保一定能关掉 Loading 遮罩
    worker.onmessage = function(event) {
      try {
        const { type, payload } = event.data;
        
        if (type === "progress") {
          setProgress(payload.percent, `${payload.stage}：${payload.detail}`);
          statusEl.className = "status warn";
          statusEl.textContent = `${payload.stage}：${payload.detail}`;
        }
        else if (type === "success") {
          const plans = payload;
          
          // 战后体检 1：完全生殖隔离，全军覆没
          if (!plans || plans.length === 0) {
            throw new Error("当前库存下，无法牵出任何一条合法的孵化连线。请检查精灵蛋组是否存在严重的【生殖隔离】！");
          }
          
          // 战后体检 2：有合法方案，但存在"死窝" (死公窝 + 死母窝)
          const bestPlan = plans[0];
          const deadCount = (bestPlan.score.deadFemales || 0) + (bestPlan.score.deadMales || 0);

          if (deadCount > 0) {
            statusEl.className = "status warn"; // 黄色警告
            statusEl.textContent = `计算完成（找到 ${plans.length} 组方案）。⚠️受限于蛋组隔离或网格距离物理极限，仍有 ${deadCount} 个小窝无法成功配对（死窝），建议调整公母比例或补充其他蛋组。`;
          } else {
            statusEl.className = "status good"; // 绿色完美
            statusEl.textContent = `已完成：多线程计算结束，共找到 ${plans.length} 组候选方案。完美排布，所有小窝均已充分利用！`;
          }

          setProgress(100, "计算完成。");
          renderSolutionPicker(plans);
          renderPlan(bestPlan);
          hideProgress();
          worker.terminate();
        }
        else if (type === "error") {
          throw new Error(payload || "计算引擎发生未知错误");
        }
      } catch (err) {
        console.error("处理计算结果时出错：", err);
        hideProgress(); // 确保关掉遮罩
        statusEl.className = "status error";
        statusEl.textContent = `计算中止：${err.message}`;
        worker.terminate(); // 杀掉挂起的后台线程
      }
    };

    worker.onerror = function(error) {
      console.error("Worker加载错误：", error);
      hideProgress();
      statusEl.className = "status error";
      statusEl.textContent = `计算引擎加载失败，请确保使用本地服务器(Live Server)运行。详细: ${error.message}`;
      worker.terminate();
    };

    console.log("发送消息给Worker...");
    worker.postMessage({
      type: "buildPlan",
      payload: { nestCount, maleCount, femaleCount, inventory, targetPriority }
    });

  } catch (error) {
    // 这里捕获的是点击按钮瞬间，参数没填对的错误
    console.error("主函数错误：", error);
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

    // 初始化应用
    async function initApp() {
      const dataLoaded = await loadSpeciesData();
      if (!dataLoaded) {
        return;
      }
      
      renderInventoryRows();
      loadState();
      autoUpdateStatusFromStock();
      syncInputs();

      [maleInput, femaleInput, nestInput].forEach(element => {
        element.addEventListener("input", syncInputs);
        element.addEventListener("change", syncInputs);
        // 添加自动保存
        element.addEventListener("change", saveState);
      });
      // 目标偏好改变时也自动保存
      targetPriorityInput.addEventListener("change", saveState);
      solveButton.addEventListener("click", runPlanner);
      solutionSelectEl.addEventListener("change", () => {
        const index = Number(solutionSelectEl.value) || 0;
        if (currentPlans[index]) {
          renderPlan(currentPlans[index]);
        }
      });
      presetButton.addEventListener("click", fillDemoInventory);
      missingAllButton.addEventListener("click", setAllMissing);
      saveButton.addEventListener("click", () => saveState(true));
    }

    // 启动应用
    initApp();
