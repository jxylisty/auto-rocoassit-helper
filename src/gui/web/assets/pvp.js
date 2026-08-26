// ========================================
// 洛克王国 PVP 实时对战 · 智能预设 + 全技能伤害预览
// ========================================

const TYPE_EN = {'火':'fire','水':'water','草':'grass','电':'electric','冰':'ice','虫':'bug','翼':'flying','地':'ground','萌':'fairy','武':'fighting','毒':'poison','龙':'dragon','幽':'ghost','恶':'dark','光':'light','普通':'normal','机械':'steel','幻':'psychic'};
const STAT_LABEL = {hp:'HP',attack:'物攻',mattack:'魔攻',defense:'物防',mdefense:'魔防',speed:'速度'};
const STATS = ['hp','attack','mattack','defense','mdefense','speed'];

let pvpPetCache=[], pvpAtkPet=null, pvpDefPet=null, pvpAllSkills=[], pvpAtkPanels=null, pvpDefPanels=null;
let pvpFloatVisible=false, pvpCalcTimer=null;

// ---------- 页面切换 ----------
function switchToPVP(){switchPage('pvp');if(!pvpPetCache.length)loadPVPData();}

async function loadPVPData(){
    try{
        const r=await pywebview.api.pvp_get_all_pets();
        if(r.success){pvpPetCache=r.pets;renderPetList('pvpAtkList','pvpAtkInput','atk');renderPetList('pvpDefList','pvpDefInput','def');}
    }catch(e){addLog('PVP数据加载失败: '+e,'error');}
}

// ---------- 精灵列表 ----------
function renderPetList(listId,inputId,side){
    const list=$(listId);if(!list)return;
    list.innerHTML=pvpPetCache.map(p=>`<div class="pvp-pet-item" onclick="selectPVPPet(${p.seq},'${side}','${p.name.replace(/'/g,"\\'")}')"><span class="pvp-pet-seq">#${p.seq}</span><span class="pvp-pet-name">${p.name}</span></div>`).join('');
}
function filterPVPPets(inputId,listId){
    const input=$(inputId),list=$(listId),q=input.value.trim().toLowerCase();
    if(!q){renderPetList(listId,inputId,listId==='pvpAtkList'?'atk':'def');list.style.display='block';return;}
    const f=pvpPetCache.filter(p=>p.name.toLowerCase().includes(q)||String(p.seq).includes(q)).slice(0,30);
    list.innerHTML=f.map(p=>`<div class="pvp-pet-item" onclick="selectPVPPet(${p.seq},'${listId==='pvpAtkList'?'atk':'def'}','${p.name.replace(/'/g,"\\'")}')"><span class="pvp-pet-seq">#${p.seq}</span><span class="pvp-pet-name">${p.name}</span></div>`).join('');
    list.style.display='block';
}
document.addEventListener('click',e=>{if(!e.target.closest('.pvp-pet-dropdown')){$$('pvp-pet-list').forEach(l=>l.style.display='none');}});
function $$(id){return document.querySelectorAll('.'+id);}

// ---------- 精灵选择 + 智能预设 ----------
async function selectPVPPet(seq,side,name){
    try{
        const [petR, presetR] = await Promise.all([
            pywebview.api.pvp_get_pet(seq, name),
            pywebview.api.pvp_get_pet_preset(seq)
        ]);
        if(!petR.success){showToast(petR.message,'error');return;}
        const pet=petR.pet;
        if(side==='atk'){pvpAtkPet=pet;renderPetPanel('pvpAtkPanel',pet,name,'pvpAtkInput');}
        else{pvpDefPet=pet;renderPetPanel('pvpDefPanel',pet,name,'pvpDefInput');}
        $(side==='atk'?'pvpAtkList':'pvpDefList').style.display='none';
        // 应用智能预设
        if(presetR.success){
            applyPreset(side==='atk'?'pvpAtk':'pvpDef', presetR);
        }
        pvpIVChanged();
    }catch(e){showToast('选择失败: '+e,'error');}
}

async function renderPetPanel(panelId,pet,name,inputId){
    const panel=$(panelId),input=$(inputId);
    if(!panel)return;
    input.value=name;
    const race=pet.race||{},types=pet.types||[],speedRace=pet.speed_race||0;
    let avatar='';
    try{const r=await pywebview.api.pvp_get_asset('pet',`${pet.seq}|${pet.name}`);if(r.success)avatar=r.image;}catch(e){}
    const typeIcons=await Promise.all(types.map(async t=>{
        const en=TYPE_EN[t]||'normal';
        try{const r=await pywebview.api.pvp_get_asset('icon',en);return r.success?`<img class="pvp-type-icon" src="${r.image}" alt="${t}">`:'';}catch(e){return'';}
    }));
    panel.innerHTML=`
        <div class="pvp-pet-header">
            <img class="pvp-pet-avatar" src="${avatar||''}" alt="${name}" onerror="this.style.display='none'">
            <div class="pvp-pet-info">
                <div class="pvp-pet-name">${pet.name||name}</div>
                <div class="pvp-type-icons">${typeIcons.join('')}${types.join(' ')}</div>
            </div>
        </div>
        <div class="pvp-race">
            <span>HP:${race.hp||0}</span><span>攻:${race.attack||0}</span><span>魔攻:${race.mattack||0}</span>
            <span>防:${race.defense||0}</span><span>魔防:${race.mdefense||0}</span><span>速:${speedRace}</span>
        </div>
    `;
    panel.style.display='block';
}

function applyPreset(prefix, preset){
    const ivConfig = document.getElementById(prefix+'IVConfig');
    if(ivConfig) ivConfig.style.display='block';
    const highIVs = preset.high_ivs || ['attack','mattack','speed'];
    document.querySelectorAll(`#${prefix}IVChecks input[data-stat]`).forEach(cb=>{
        cb.checked = highIVs.includes(cb.dataset.stat);
    });
    const ivVal = $(prefix+'IVValue');
    if(ivVal) ivVal.value = String(preset.iv_value || 10);
    const nu = $(prefix+'NatureUp');
    if(nu) nu.value = preset.nature_up || '';
    const nd = $(prefix+'NatureDown');
    if(nd) nd.value = preset.nature_down || '';
}

// ---------- IV/性格 变更 → 自动重算 ----------
function pvpIVChanged(){
    clearTimeout(pvpCalcTimer);
    pvpCalcTimer=setTimeout(doCalcAllSkills,300);
}

function getIVConfig(prefix){
    const checks=document.querySelectorAll(`#${prefix}IVChecks input[data-stat]:checked`);
    const highIVs=Array.from(checks).map(c=>c.dataset.stat);
    const val=parseInt($(prefix+'IVValue')?.value||'10');
    const nu=$(prefix+'NatureUp')?.value||null;
    const nd=$(prefix+'NatureDown')?.value||null;
    return {highIVs,val,nu,nd};
}

async function doCalcAllSkills(){
    if(!pvpAtkPet||!pvpDefPet)return;
    const atkCfg=getIVConfig('pvpAtk'),defCfg=getIVConfig('pvpDef');
    try{
        const r=await pywebview.api.pvp_calc_all_skills(
            pvpAtkPet.seq,pvpDefPet.seq,
            atkCfg.highIVs,atkCfg.val,defCfg.highIVs,defCfg.val,
            atkCfg.nu,atkCfg.nd,defCfg.nu,defCfg.nd
        );
        if(!r.success){showToast(r.message,'error');return;}
        pvpAllSkills=r.skills;pvpAtkPanels=r.atkPanels;pvpDefPanels=r.defPanels;
        renderSkillTable('all');
        updatePanelStats('pvpAtkPanel',r.atkPanels);
        updatePanelStats('pvpDefPanel',r.defPanels);
        // 速度对比
        updateSpeedCompare(r);
        updateFloatIfVisible(r);
        $('pvpSkillSection').style.display='block';
    }catch(e){showToast('计算失败: '+e,'error');}
}

function updatePanelStats(panelId,panels){
    const panel=$(panelId);if(!panel||!panels)return;
    const raceEl=panel.querySelector('.pvp-race');
    if(raceEl){
        raceEl.innerHTML=`
            <span>HP:${Math.round(panels.hp)}</span><span>攻:${Math.round(panels.attack)}</span>
            <span>魔攻:${Math.round(panels.mattack)}</span><span>防:${Math.round(panels.defense)}</span>
            <span>魔防:${Math.round(panels.mdefense)}</span><span>速:${Math.round(panels.speed)}</span>
        `;
    }
}

function updateSpeedCompare(r){
    const el = $('pvpSpeedCompare');
    if(!el) return;
    const mySpd = r.mySpeed || 0, enemySpd = r.enemySpeed || 0;
    const result = r.speedResult || '速度相同';
    const cls = result==='我方先手'?'speed-win':result==='敌方先手'?'speed-lose':'speed-tie';
    el.innerHTML = `<span class="pvp-speed-label">⚡ 先手：</span>
        <span class="pvp-speed-val">我方${mySpd}</span> vs <span class="pvp-speed-val">敌方${enemySpd}</span>
        <span class="pvp-speed-result ${cls}">${result}</span>`;
    el.style.display = 'block';
}

// ---------- 技能表格渲染 ----------
function renderSkillTable(filter){
    const table=$('pvpSkillTable');if(!table)return;
    document.querySelectorAll('.pvp-filter-btn').forEach(b=>b.classList.toggle('active',b.dataset.filter===filter));
    let skills=pvpAllSkills;
    if(filter==='strong')skills=skills.filter(s=>s.isDamage&&s.attrMultiplier>=2);
    else if(filter==='normal')skills=skills.filter(s=>s.isDamage&&s.attrMultiplier>=1&&s.attrMultiplier<2);
    else if(filter==='resist')skills=skills.filter(s=>s.isDamage&&s.attrMultiplier>0&&s.attrMultiplier<1);
    else if(filter==='status')skills=skills.filter(s=>!s.isDamage);

    if(!skills.length){table.innerHTML='<div class="pvp-table-empty">无匹配技能</div>';return;}

    const defHp=pvpDefPanels?Math.round(pvpDefPanels.hp):100;
    const maxDmg=Math.max(1,...skills.filter(s=>s.isDamage).map(s=>s.maxDamage));

    table.innerHTML=skills.map(s=>{
        if(!s.isDamage){
            return `<div class="pvp-skill-row nodmg">
                <span class="pvp-skill-name">${s.name}</span><span class="pvp-skill-type">${s.type==='状态'?'状':'变'}</span>
                <span class="pvp-skill-power">-</span><span class="pvp-skill-cost">${s.consume}</span>
                <span class="pvp-skill-mult">-</span><span class="pvp-skill-dmg">-</span><span class="pvp-skill-bar">-</span></div>`;
        }
        const mul=s.attrMultiplier;
        const cls=mul>=2?'strong':mul>=1?'normal':'resist';
        const mulText=mul>=2?mul.toFixed(1)+'x':mul>=1?mul.toFixed(1)+'x':mul.toFixed(1)+'x';
        const pct=Math.min(100,(s.maxDamage/defHp)*100);
        const barColor=pct>=100?'#f87171':pct>=50?'#fbbf24':'#4ade80';
        const barWidth=Math.min(100,(s.maxDamage/maxDmg)*100);
        return `<div class="pvp-skill-row ${cls}">
            <span class="pvp-skill-name">${s.name}</span>
            <span class="pvp-skill-type">${s.type==='物攻'?'物':'魔'}</span>
            <span class="pvp-skill-power">${s.power}</span>
            <span class="pvp-skill-cost">${s.consume}</span>
            <span class="pvp-skill-mult">${mulText}</span>
            <span class="pvp-skill-dmg">${s.minDamage}~${s.maxDamage}</span>
            <span class="pvp-skill-bar"><span class="pvp-bar-inner" style="width:${barWidth}%;background:${barColor}"></span></span>
        </div>`;
    }).join('');
}

function filterSkillTable(f){renderSkillTable(f);}

// ---------- 重置预设 ----------
async function resetPreset(side){
    const pet = side==='atk'?pvpAtkPet:pvpDefPet;
    if(!pet) return;
    const r = await pywebview.api.pvp_get_pet_preset(pet.seq);
    if(r.success){
        applyPreset(side==='atk'?'pvpAtk':'pvpDef', r);
        pvpIVChanged();
    }
}

// ---------- 识别精灵 ----------
async function pvpRecognize(){
    showToast('正在捕获游戏画面并识别...','info');
    try{
        const r=await pywebview.api.pvp_recognize();
        if(!r.success){showToast(r.message,'error');return;}
        const pets=r.pets||[];
        showToast(`识别到 ${pets.length} 只精灵`,'success');
        if(pets.length>=1){
            const seq=pets[0].seq;
            if(seq){selectPVPPet(seq,'atk',pets[0].name||'');}
        }
        if(pets.length>=2){
            const seq=pets[1].seq;
            if(seq){selectPVPPet(seq,'def',pets[1].name||'');}
        }
    }catch(e){showToast('识别失败: '+e,'error');}
}

// ---------- 悬浮窗 ----------
async function togglePVPFloat(){
    try{
        const r=await pywebview.api.pvp_float_toggle();
        if(!r.success){showToast('悬浮窗: '+r.message,'warning');return;}
        pvpFloatVisible=r.visible;
        if(pvpFloatVisible){setTimeout(()=>updateFloatIfVisible(null),500);}
    }catch(e){showToast('悬浮窗: '+e,'error');}
}

async function updateFloatIfVisible(calcResult){
    if(!pvpFloatVisible)return;
    const data=calcResult||{atkPanels:pvpAtkPanels,defPanels:pvpDefPanels,skills:pvpAllSkills,atkTypes:pvpAtkPet?.types||[],defTypes:pvpDefPet?.types||[],atkName:pvpAtkPet?.name||'?',defName:pvpDefPet?.name||'?'};
    const topSkill=(data.skills||[]).filter(s=>s.isDamage)[0];
    const defHp=data.defPanels?Math.round(data.defPanels.hp):100;
    const mySpeed=data.atkPanels?Math.round(data.atkPanels.speed):0;
    const enemySpeed=data.defPanels?Math.round(data.defPanels.speed):0;
    try{
        const r=await pywebview.api.pvp_float_update({
            atkName:data.atkName,atkTypes:data.atkTypes,defName:data.defName,defTypes:data.defTypes,
            skillName:topSkill?topSkill.name:'?',damage:topSkill?topSkill.maxDamage:0,
            attrMul:topSkill?topSkill.attrMultiplier:1,atkUsed:data.atkPanels?Math.round(data.atkPanels.attack):0,
            defHp,mySpeed,enemySpeed,
            speedResult:mySpeed>enemySpeed?'我方先手':mySpeed<enemySpeed?'敌方先手':'平速'
        });
        if(!r.success){/* 加载中静默忽略 */}
    }catch(e){/* 悬浮窗未就绪，静默 */}
}