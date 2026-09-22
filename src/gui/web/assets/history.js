// ============================================================
// 洛克王国：世界 — 天梯赛季战报与 ELO 遇敌分析前端控制器
// ============================================================

let currentHistoryFilter = 'ALL';
let currentHistoryList = [];

// 页面切换到 history 时自动加载数据
window.loadMatchHistory = async function() {
    await Promise.all([
        refreshHistoryStats(),
        refreshHistoryList(currentHistoryFilter)
    ]);
};

// 刷新统计大盘与 ELO
async function refreshHistoryStats() {
    try {
        const res = await window.pywebview.api.pvp_get_history_stats();
        if (!res || !res.success) return;
        renderHistoryStats(res.stats || {}, res.elo || {});
    } catch (e) {
        console.warn('获取战报统计失败:', e);
    }
}

// 刷新历史对局列表
async function refreshHistoryList(filter = 'ALL') {
    currentHistoryFilter = filter;
    try {
        const res = await window.pywebview.api.pvp_get_history(100, 0, filter);
        if (!res || !res.success) return;
        currentHistoryList = res.history || [];
        renderHistoryList(currentHistoryList);
    } catch (e) {
        console.warn('获取战报列表失败:', e);
    }
}

// 渲染大盘统计
function renderHistoryStats(stats, elo) {
    const totalEl = document.getElementById('statTotalMatches');
    const winRateEl = document.getElementById('statWinRate');
    const streakEl = document.getElementById('statCurrentStreak');
    const crushEl = document.getElementById('statCrushWins');
    const durationEl = document.getElementById('statAvgDuration');

    if (totalEl) totalEl.textContent = `${stats.total || 0} 场`;
    if (winRateEl) {
        const wr = stats.win_rate || 0;
        winRateEl.textContent = `${wr}%`;
        winRateEl.className = 'stat-val ' + (wr >= 60 ? 'good' : wr < 45 ? 'bad' : '');
    }
    if (streakEl) {
        const st = stats.current_streak || 0;
        streakEl.textContent = st > 0 ? `${st} 连胜 🔥` : st < 0 ? `${Math.abs(st)} 连败` : '平局';
        streakEl.className = 'stat-val ' + (st > 0 ? 'good' : st < 0 ? 'bad' : '');
    }
    if (crushEl) crushEl.textContent = `${stats.crush_wins || 0} 场`;
    if (durationEl) durationEl.textContent = stats.avg_duration || '--';

    // 渲染 ELO 常见敌方怪 TOP 6
    const topPetsList = document.getElementById('eloTopPetsList');
    if (topPetsList) {
        const pets = elo.top_enemy_pets || [];
        if (!pets.length) {
            topPetsList.innerHTML = '<div class="empty-hint">暂无遇敌对局数据</div>';
        } else {
            topPetsList.innerHTML = pets.map(p => {
                const avatar = typeof getPetAvatar === 'function' ? getPetAvatar(p.name) : 'assets/img/icons/normal.webp';
                return `
                <div class="elo-pet-row">
                    <img class="elo-pet-avatar" src="${avatar}" onerror="this.src='assets/img/icons/normal.webp'">
                    <div class="elo-pet-info">
                        <div class="elo-pet-name-row">
                            <span class="elo-pet-name">${p.name}</span>
                            <span class="elo-pet-count">遭遇 ${p.encounters} 次</span>
                        </div>
                        <div class="elo-bar-wrap">
                            <div class="elo-bar-fill" style="width: ${p.win_rate}%"></div>
                        </div>
                    </div>
                    <div class="elo-pet-rate ${p.win_rate >= 55 ? 'good' : p.win_rate < 40 ? 'bad' : ''}">胜率 ${p.win_rate}%</div>
                </div>`;
            }).join('');
        }
    }

    // 渲染敌方属性分布 ELO 雷达
    const attrDistList = document.getElementById('eloAttrDistList');
    if (attrDistList) {
        const attrs = elo.enemy_attr_distribution || [];
        if (!attrs.length) {
            attrDistList.innerHTML = '<div class="empty-hint">暂无属性遭遇数据</div>';
        } else {
            attrDistList.innerHTML = attrs.map(a => {
                const icon = typeof getAttrIcon === 'function' ? getAttrIcon(a.attr) : '';
                return `
                <div class="elo-attr-row">
                    <div class="elo-attr-badge">
                        ${icon ? `<img src="${icon}" class="attr-icon-mini">` : ''}
                        <span>${a.attr}系</span>
                    </div>
                    <div class="elo-bar-wrap">
                        <div class="elo-bar-fill attr-fill" style="width: ${a.pct}%"></div>
                    </div>
                    <span class="elo-attr-pct">${a.pct}% (${a.count})</span>
                </div>`;
            }).join('');
        }
    }
}

// 渲染历史战报卡片列表
function renderHistoryList(matches) {
    const listEl = document.getElementById('historyCardList');
    if (!listEl) return;

    if (!matches || !matches.length) {
        listEl.innerHTML = '<div class="empty-card">暂无此筛选条件下的战报，打完一把天梯会自动入库！</div>';
        return;
    }

    listEl.innerHTML = matches.map(m => {
        const isWin = m.result === 'WIN';
        const isCrush = m.is_crush;
        const durMin = Math.floor((m.duration_sec || 0) / 60);
        const durSec = (m.duration_sec || 0) % 60;
        const durStr = m.duration_sec > 0 ? `${durMin}分${durSec}秒` : '未知时长';

        // 渲染双方 6 槽位
        const renderSlots = (team, isEnemy) => {
            const slots = [];
            for (let i = 0; i < 6; i++) {
                if (i < team.length) {
                    const p = team[i];
                    const avatar = typeof getPetAvatar === 'function' ? getPetAvatar(p.name) : 'assets/img/icons/normal.webp';
                    const isFainted = p.hp_pct !== undefined && p.hp_pct <= 0;
                    slots.push(`
                    <div class="mini-slot ${isFainted ? 'fainted' : ''}" title="${p.name} ${isFainted ? '(阵亡)' : ''}">
                        <img src="${avatar}" onerror="this.src='assets/img/icons/normal.webp'">
                        <span class="mini-slot-name">${p.name}</span>
                    </div>`);
                } else {
                    // 未出战的灰底槽位
                    slots.push(`
                    <div class="mini-slot empty" title="${isEnemy ? '敌方未出战' : '我方替补'}">
                        <span class="empty-mark">❓</span>
                        <span class="mini-slot-name dim">${isEnemy ? '未出战' : '替补'}</span>
                    </div>`);
                }
            }
            return slots.join('');
        };

        const mySlots = renderSlots(m.my_team || [], false);
        const enemySlots = renderSlots(m.enemy_team || [], true);

        return `
        <div class="match-card ${isWin ? 'win' : 'loss'}">
            <div class="match-left-banner">
                <div class="match-result-badge ${isWin ? 'win' : 'loss'}">
                    ${isWin ? 'VICTORY' : 'DEFEAT'}
                </div>
                ${isCrush ? '<div class="crush-gold-badge">⚡ 碾压局</div>' : ''}
                <div class="match-time">${m.match_time || ''}</div>
                <div class="match-sub">${m.rank_tier || '天梯排位'} · ⏱️ ${durStr}</div>
            </div>

            <div class="match-teams-area">
                <!-- 我方阵容 -->
                <div class="match-team-row">
                    <span class="team-label my">我方出战:</span>
                    <div class="slots-container">${mySlots}</div>
                </div>

                <!-- 敌方阵容 -->
                <div class="match-team-row">
                    <span class="team-label enemy">敌方参战 (${m.enemy_seen_count || 1}/6):</span>
                    <div class="slots-container">${enemySlots}</div>
                </div>
            </div>
        </div>`;
    }).join('');
}

// 切换筛选标签
window.filterHistory = function(filter) {
    document.querySelectorAll('.history-tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.filter === filter);
    });
    refreshHistoryList(filter);
};

// 一键生成 15 场演示战报(仅供界面预览, AI 陪玩会当真实战绩读取 — 需二次确认)
window.generateMockHistory = async function() {
    const ok = await new Promise((resolve) => {
        if (typeof showCustomModal === 'function') {
            showCustomModal({
                title: '生成演示战报',
                desc: '将写入 15 条随机生成的假对局(仅供界面预览)。\n注意: AI 陪玩读取战报历史时无法区分真假, 会把这些当真实战绩分析。\n确认要写入吗?',
                confirmText: '确认写入',
                cancelText: '取消',
                onConfirm: () => resolve(true),
                onCancel: () => resolve(false),
            });
        } else {
            resolve(confirm('将写入 15 条随机生成的假对局(仅供预览), AI 会当真实战绩读取。确认吗?'));
        }
    });
    if (!ok) return;
    try {
        await window.pywebview.api.pvp_generate_mock_history(15);
        showToast('已写入 15 场演示战报(假数据, 可点清空移除)', 'warning');
        await loadMatchHistory();
    } catch (e) {
        showToast('生成失败: ' + e, 'error');
    }
};

// 清空战报
window.clearMatchHistoryConfirm = function() {
    showCustomModal({
        title: '清空战绩确认',
        desc: '确定要清空全部历史对战记录吗？此操作无法撤销。',
        onConfirm: async () => {
            await window.pywebview.api.pvp_clear_history();
            showToast('已清空历史对战记录', 'info');
            await loadMatchHistory();
        }
    });
};
