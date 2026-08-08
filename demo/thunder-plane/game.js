'use strict';
/* ================= 雷电战机 Thunder Strike ================= */
/* 方向键/WASD 移动 · 空格连射 · 粒子爆炸效果                   */

// ---------- 画布 ----------
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const W = 480, H = 720;
canvas.width = W; canvas.height = H;

function resize() {
  const scale = Math.min(innerWidth / W, innerHeight / H) * 0.96;
  canvas.style.width = (W * scale) + 'px';
  canvas.style.height = (H * scale) + 'px';
}
addEventListener('resize', resize);
resize();

// ---------- DOM ----------
const elScore = document.getElementById('score');
const elHi = document.getElementById('hi');
const elLives = document.getElementById('lives');
const overlay = document.getElementById('overlay');
const ovTitle = document.getElementById('ovTitle');
const ovSub = document.getElementById('ovSub');
const ovTip = document.querySelector('#overlay .tip');

// ---------- 输入 ----------
const keys = {};
addEventListener('keydown', e => {
  if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space'].includes(e.code)) e.preventDefault();
  keys[e.code] = true;
  if (e.code === 'Space' && game.state !== 'playing') startGame();
  if (e.code === 'KeyR' && game.state !== 'playing') startGame();
});
addEventListener('keyup', e => { keys[e.code] = false; });

// ---------- 游戏状态 ----------
const game = {
  state: 'start',          // start | playing | over
  score: 0, lives: 3, time: 0,
  spawnTimer: 0, shake: 0, flash: 0, respawn: -1,
  hiScore: 0,
};
try { game.hiScore = +localStorage.getItem('thunder_hi') || 0; } catch (e) { /* ignore */ }

function startGame() {
  game.state = 'playing';
  game.score = 0; game.lives = 3; game.time = 0;
  game.spawnTimer = 0; game.shake = 0; game.flash = 0; game.respawn = -1;
  bullets.length = 0; enemies.length = 0; particles.length = 0;
  shockwaves.length = 0; debris.length = 0; enemyBullets.length = 0;
  player.x = W / 2; player.y = H - 90;
  player.alive = true; player.invincible = 2; player.cooldown = 0;
  overlay.classList.add('hidden');
}

// ---------- 玩家 ----------
const player = {
  x: W / 2, y: H - 90,
  speed: 320, cooldown: 0, fireRate: 0.16,
  invincible: 0, alive: true,
};

function playerShoot() {
  const lv = Math.min(1 + Math.floor(game.score / 800), 3);
  const y = player.y - 26;
  if (lv === 1) {
    bullets.push({ x: player.x, y: y, vy: -640, r: 3 });
  } else if (lv === 2) {
    bullets.push({ x: player.x - 11, y: y, vy: -640, r: 3 });
    bullets.push({ x: player.x + 11, y: y, vy: -640, r: 3 });
  } else {
    bullets.push({ x: player.x - 14, y: y, vy: -640, r: 3 });
    bullets.push({ x: player.x, y: y + 4, vy: -740, r: 4 });
    bullets.push({ x: player.x + 14, y: y, vy: -640, r: 3 });
  }
}

// ---------- 实体数组 ----------
const bullets = [];
const enemyBullets = [];
const enemies = [];
const particles = [];
const shockwaves = [];
const debris = [];

// 背景星空
const stars = [];
for (let i = 0; i < 140; i++) {
  stars.push({
    x: Math.random() * W, y: Math.random() * H,
    s: 20 + Math.random() * 90, sz: 0.5 + Math.random() * 2,
    tw: Math.random() * Math.PI * 2,
  });
}

// ---------- 爆炸粒子系统 ----------
const EXPLO_COLORS = ['#ff5722', '#ffc107', '#fff3e0', '#ff8a65', '#ffd54f'];
function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

/* 核心：爆炸效果
   power 控制规模（1=普通爆炸, 1.6~2=玩家被击毁的大爆炸）
   由三部分组成：
   1) 大量火花粒子（喷溅 + 拖尾衰减）
   2) 冲击波圆环（两层，向外扩散渐隐）
   3) 旋转残骸碎片（带角速度翻滚坠落） */
function explode(x, y, color, power) {
  power = power || 1;
  const n = Math.floor(36 * power) + 12;
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2;
    const sp = (50 + Math.random() * 300) * power;
    particles.push({
      x: x, y: y,
      vx: Math.cos(a) * sp, vy: Math.sin(a) * sp,
      life: 0.4 + Math.random() * 0.9, maxLife: 1.3,
      size: 1 + Math.random() * 3.5 * power,
      color: Math.random() < 0.5 ? color : pick(EXPLO_COLORS),
      drag: 0.9,
    });
  }
  shockwaves.push({ x: x, y: y, r: 6, maxR: 72 * power, life: 0.5, maxLife: 0.5 });
  shockwaves.push({ x: x, y: y, r: 2, maxR: 42 * power, life: 0.32, maxLife: 0.32 });
  const dn = Math.floor(4 * power);
  for (let i = 0; i < dn; i++) {
    debris.push({
      x: x, y: y,
      vx: (Math.random() - 0.5) * 260 * power, vy: (Math.random() - 0.5) * 260 * power,
      rot: Math.random() * Math.PI * 2, vr: (Math.random() - 0.5) * 14,
      size: 2.5 + Math.random() * 4 * power,
      life: 1.4, maxLife: 1.4, color: color,
    });
  }
}

// ---------- 敌人 ----------
const ENEMY_DEFS = {
  normal: { r: 16, hp: 1, score: 10, color: '#ff5a5a', spd: [70, 130] },
  fast:   { r: 12, hp: 1, score: 15, color: '#ff9f43', spd: [150, 220] },
  tank:   { r: 26, hp: 4, score: 40, color: '#b06bff', spd: [45, 70] },
};

function spawnEnemy() {
  const s = game.score;
  const roll = Math.random();
  let type = 'normal';
  if (s > 400 && roll < 0.12) type = 'tank';
  else if (s > 120 && roll < 0.38) type = 'fast';
  const def = ENEMY_DEFS[type];
  enemies.push({
    type: type,
    x: def.r + Math.random() * (W - 2 * def.r), y: -30,
    vx: (Math.random() - 0.5) * 30,
    vy: def.spd[0] + Math.random() * (def.spd[1] - def.spd[0]),
    hp: def.hp, r: def.r, score: def.score, color: def.color,
    shootT: 1.5 + Math.random() * 3, sway: Math.random() * Math.PI * 2,
  });
}

// ---------- 玩家被击中 ----------
function hitPlayer() {
  if (!player.alive || player.invincible > 0) return;
  player.alive = false;
  explode(player.x, player.y, '#4fc3f7', 1.8);   // ★ 战机爆炸大特效
  game.shake = 1; game.flash = 1;                // 屏幕震动 + 白闪
  game.lives--;
  if (game.lives <= 0) {
    game.state = 'over';
    ovTitle.textContent = '游戏结束';
    ovSub.textContent = '最终得分 ' + game.score + ' · 最高 ' + game.hiScore;
    ovTip.innerHTML = '按 <span class="key">R</span> 或 <span class="key">空格</span> 重新开始';
    overlay.classList.remove('hidden');
  } else {
    game.respawn = 1.2;
  }
}

// ---------- 更新逻辑 ----------
function update(dt) {
  if (game.state !== 'playing') return;
  game.time += dt;

  // 敌人生成（随时间加快）
  game.spawnTimer -= dt;
  const interval = Math.max(0.45, 1.1 - game.time * 0.008);
  if (game.spawnTimer <= 0) {
    spawnEnemy();
    game.spawnTimer = interval * (0.7 + Math.random() * 0.6);
  }

  // 玩家移动（8 方向）
  if (player.alive) {
    let dx = 0, dy = 0;
    if (keys.ArrowLeft || keys.KeyA) dx -= 1;
    if (keys.ArrowRight || keys.KeyD) dx += 1;
    if (keys.ArrowUp || keys.KeyW) dy -= 1;
    if (keys.ArrowDown || keys.KeyS) dy += 1;
    if (dx && dy) { dx *= 0.7071; dy *= 0.7071; }
    player.x += dx * player.speed * dt;
    player.y += dy * player.speed * dt;
    player.x = Math.max(24, Math.min(W - 24, player.x));
    player.y = Math.max(40, Math.min(H - 40, player.y));

    // 空格连射
    player.cooldown -= dt;
    if (keys.Space && player.cooldown <= 0) {
      playerShoot();
      player.cooldown = player.fireRate;
    }
    // 尾焰粒子
    if (Math.random() < 0.7) {
      particles.push({
        x: player.x + (Math.random() - 0.5) * 8, y: player.y + 22,
        vx: (Math.random() - 0.5) * 40, vy: 120 + Math.random() * 80,
        life: 0.2 + Math.random() * 0.2, maxLife: 0.4,
        size: 2 + Math.random() * 3,
        color: Math.random() < 0.5 ? '#4fc3f7' : '#ffab40',
        drag: 0.95,
      });
    }
  }

  // 无敌 / 重生
  if (player.invincible > 0) player.invincible -= dt;
  if (!player.alive && game.respawn > 0) {
    game.respawn -= dt;
    if (game.respawn <= 0) {
      player.alive = true; player.invincible = 2.5;
      player.x = W / 2; player.y = H - 90;
    }
  }

  // 玩家子弹 → 敌人
  for (let i = bullets.length - 1; i >= 0; i--) {
    const b = bullets[i];
    b.y += b.vy * dt;
    if (b.y < -10 || b.y > H + 10) { bullets.splice(i, 1); continue; }
    for (let j = enemies.length - 1; j >= 0; j--) {
      const e = enemies[j];
      if (Math.hypot(b.x - e.x, b.y - e.y) < e.r + b.r) {
        bullets.splice(i, 1);
        e.hp--;
        explode(b.x, b.y, '#ffd54f', 0.35);      // 命中火花
        if (e.hp <= 0) {
          explode(e.x, e.y, e.color, 1);         // 敌机击毁爆炸
          game.score += e.score;
          game.shake = Math.min(1, game.shake + 0.25);
          enemies.splice(j, 1);
        }
        break;
      }
    }
  }

  // 敌人移动 / 射击 / 撞机
  for (let i = enemies.length - 1; i >= 0; i--) {
    const e = enemies[i];
    e.sway += dt * 2;
    e.x += (e.vx + Math.sin(e.sway) * 20) * dt;
    e.y += e.vy * dt;
    if (e.x < e.r) e.x = e.r;
    if (e.x > W - e.r) e.x = W - e.r;

    // 敌人向下发射追踪弹（后期解锁）
    e.shootT -= dt;
    if (e.shootT <= 0 && e.y > 0 && e.y < H * 0.6 && game.score > 250) {
      e.shootT = 2 + Math.random() * 2.5;
      const a = Math.atan2(player.y - e.y, player.x - e.x);
      enemyBullets.push({ x: e.x, y: e.y + e.r * 0.5, vx: Math.cos(a) * 180, vy: Math.sin(a) * 180, r: 5 });
    }

    if (e.y > H + 40) { enemies.splice(i, 1); continue; }

    // 敌机撞上玩家
    if (player.alive && player.invincible <= 0) {
      if (Math.hypot(player.x - e.x, player.y - e.y) < e.r + 20) {
        explode(e.x, e.y, e.color, 1.2);
        enemies.splice(i, 1);
        hitPlayer();
      }
    }
  }

  // 敌弹 → 玩家
  for (let i = enemyBullets.length - 1; i >= 0; i--) {
    const b = enemyBullets[i];
    b.x += b.vx * dt; b.y += b.vy * dt;
    if (b.x < -10 || b.x > W + 10 || b.y < -10 || b.y > H + 10) { enemyBullets.splice(i, 1); continue; }
    if (player.alive && player.invincible <= 0) {
      if (Math.hypot(b.x - player.x, b.y - player.y) < 20 + b.r) {
        enemyBullets.splice(i, 1);
        hitPlayer();
      }
    }
  }

  // 粒子 / 冲击波 / 残骸 演化
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.life -= dt;
    if (p.life <= 0) { particles.splice(i, 1); continue; }
    p.vx *= p.drag; p.vy *= p.drag;
    p.x += p.vx * dt; p.y += p.vy * dt;
  }
  for (let i = shockwaves.length - 1; i >= 0; i--) {
    const s = shockwaves[i];
    s.life -= dt;
    s.r = s.maxR * (1 - s.life / s.maxLife);
    if (s.life <= 0) shockwaves.splice(i, 1);
  }
  for (let i = debris.length - 1; i >= 0; i--) {
    const d = debris[i];
    d.life -= dt;
    if (d.life <= 0) { debris.splice(i, 1); continue; }
    d.vx *= 0.98; d.vy *= 0.98;
    d.x += d.vx * dt; d.y += d.vy * dt;
    d.rot += d.vr * dt;
  }

  // 震动 / 闪光 衰减
  game.shake = Math.max(0, game.shake - dt * 2.5);
  game.flash = Math.max(0, game.flash - dt * 3);

  // 最高分存档
  if (game.score > game.hiScore) {
    game.hiScore = game.score;
    try { localStorage.setItem('thunder_hi', game.hiScore); } catch (e) { /* ignore */ }
  }

  // HUD
  elScore.textContent = game.score;
  elHi.textContent = game.hiScore;
  let ls = '';
  for (let i = 0; i < game.lives; i++) ls += '❤ ';
  elLives.textContent = ls;
}

// ---------- 渲染 ----------
let dtGlobal = 0.016;

function render() {
  ctx.save();
  // 屏幕震动
  if (game.shake > 0) {
    ctx.translate((Math.random() - 0.5) * 12 * game.shake, (Math.random() - 0.5) * 12 * game.shake);
  }

  // 背景渐变
  const bg = ctx.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, '#020614');
  bg.addColorStop(0.6, '#061230');
  bg.addColorStop(1, '#0a1e42');
  ctx.fillStyle = bg;
  ctx.fillRect(-20, -20, W + 40, H + 40);

  // 滚动星空
  for (const s of stars) {
    s.y += s.s * dtGlobal;
    s.tw += dtGlobal * 3;
    if (s.y > H + 2) { s.y = -2; s.x = Math.random() * W; }
    ctx.fillStyle = 'rgba(200,225,255,' + (0.35 + 0.65 * Math.abs(Math.sin(s.tw))) + ')';
    ctx.fillRect(s.x, s.y, s.sz, s.sz);
  }

  // 敌人
  for (const e of enemies) drawEnemy(e);

  // 玩家
  drawPlayer();

  // 子弹
  drawBullets();

  // 特效（粒子 / 冲击波 / 残骸）
  drawFx();

  // 白色闪光
  if (game.flash > 0) {
    ctx.fillStyle = 'rgba(255,255,255,' + (game.flash * 0.6) + ')';
    ctx.fillRect(-20, -20, W + 40, H + 40);
  }

  ctx.restore();
}

// ---------- 玩家战机绘制 ----------
function drawPlayer() {
  if (!player.alive) return;
  // 无敌闪烁
  if (player.invincible > 0 && Math.floor(player.invincible * 12) % 2 === 0) return;
  ctx.save();
  ctx.translate(player.x, player.y);

  ctx.shadowColor = '#4fc3f7'; ctx.shadowBlur = 18;
  // 机身
  ctx.fillStyle = '#e0f7ff';
  ctx.beginPath();
  ctx.moveTo(0, -26); ctx.lineTo(-7, -12); ctx.lineTo(-17, 4);
  ctx.lineTo(-9, 20); ctx.lineTo(9, 20); ctx.lineTo(17, 4); ctx.lineTo(7, -12);
  ctx.closePath(); ctx.fill();
  ctx.shadowBlur = 0;
  // 座舱
  ctx.fillStyle = '#0288d1';
  ctx.beginPath(); ctx.ellipse(0, -6, 4.5, 8, 0, 0, Math.PI * 2); ctx.fill();
  // 机翼装饰
  ctx.fillStyle = '#29b6f6';
  ctx.beginPath(); ctx.moveTo(-17, 4); ctx.lineTo(-24, 10); ctx.lineTo(-9, 20); ctx.closePath(); ctx.fill();
  ctx.beginPath(); ctx.moveTo(17, 4); ctx.lineTo(24, 10); ctx.lineTo(9, 20); ctx.closePath(); ctx.fill();
  // 动态尾焰
  const fl = 8 + Math.sin(performance.now() / 40) * 3;
  ctx.fillStyle = '#ffab40';
  ctx.beginPath(); ctx.moveTo(-5, 20); ctx.lineTo(0, 20 + fl); ctx.lineTo(5, 20); ctx.closePath(); ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.beginPath(); ctx.moveTo(-2.5, 20); ctx.lineTo(0, 20 + fl * 0.6); ctx.lineTo(2.5, 20); ctx.closePath(); ctx.fill();
  ctx.restore();
}

// ---------- 敌机绘制 ----------
function drawEnemy(e) {
  ctx.save();
  ctx.translate(e.x, e.y);
  ctx.shadowColor = e.color; ctx.shadowBlur = 12;
  ctx.fillStyle = e.color;
  if (e.type === 'normal') {
    // 菱形
    ctx.beginPath();
    ctx.moveTo(0, -e.r); ctx.lineTo(e.r, 0); ctx.lineTo(0, e.r); ctx.lineTo(-e.r, 0);
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#7a1f1f';
    ctx.beginPath();
    ctx.moveTo(0, -e.r * 0.5); ctx.lineTo(e.r * 0.5, 0); ctx.lineTo(0, e.r * 0.5); ctx.lineTo(-e.r * 0.5, 0);
    ctx.closePath(); ctx.fill();
  } else if (e.type === 'fast') {
    // 箭头
    ctx.beginPath();
    ctx.moveTo(-e.r, -e.r * 0.7); ctx.lineTo(e.r, 0); ctx.lineTo(-e.r, e.r * 0.7);
    ctx.closePath(); ctx.fill();
  } else {
    // 六边形重甲
    ctx.beginPath();
    for (let k = 0; k < 6; k++) {
      const a = k * Math.PI / 3;
      ctx.lineTo(Math.cos(a) * e.r, Math.sin(a) * e.r);
    }
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#4a148c';
    ctx.beginPath(); ctx.arc(0, 0, e.r * 0.45, 0, Math.PI * 2); ctx.fill();
  }
  ctx.shadowBlur = 0;
  // tank 血条
  if (e.type === 'tank') {
    ctx.fillStyle = 'rgba(0,0,0,.5)';
    ctx.fillRect(-e.r, -e.r - 10, e.r * 2, 4);
    ctx.fillStyle = '#b06bff';
    ctx.fillRect(-e.r, -e.r - 10, e.r * 2 * (e.hp / 4), 4);
  }
  ctx.restore();
}

// ---------- 子弹绘制 ----------
function drawBullets() {
  for (const b of bullets) {
    ctx.save();
    ctx.shadowColor = '#7fd4ff'; ctx.shadowBlur = 10;
    const g = ctx.createLinearGradient(b.x, b.y - 8, b.x, b.y + 8);
    g.addColorStop(0, '#fff'); g.addColorStop(1, '#4fc3f7');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.moveTo(b.x, b.y - 8); ctx.lineTo(b.x + 3.5, b.y + 6); ctx.lineTo(b.x - 3.5, b.y + 6);
    ctx.closePath(); ctx.fill();
    ctx.restore();
  }
  for (const b of enemyBullets) {
    ctx.save();
    ctx.shadowColor = '#ff5a5a'; ctx.shadowBlur = 10;
    ctx.fillStyle = '#ff8a65';
    ctx.beginPath(); ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#ffd5c4';
    ctx.beginPath(); ctx.arc(b.x, b.y, b.r * 0.5, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }
}

// ---------- 特效绘制 ----------
function drawFx() {
  // 火花粒子
  for (const p of particles) {
    const a = Math.max(0, p.life / p.maxLife);
    ctx.globalAlpha = a;
    ctx.fillStyle = p.color;
    ctx.beginPath(); ctx.arc(p.x, p.y, Math.max(0.4, p.size * a), 0, Math.PI * 2); ctx.fill();
  }
  ctx.globalAlpha = 1;
  // 冲击波环
  for (const s of shockwaves) {
    const a = Math.max(0, s.life / s.maxLife);
    ctx.strokeStyle = 'rgba(255,235,180,' + a + ')';
    ctx.lineWidth = 3 * a + 1;
    ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2); ctx.stroke();
  }
  // 残骸碎片
  for (const d of debris) {
    ctx.save();
    ctx.translate(d.x, d.y); ctx.rotate(d.rot);
    ctx.globalAlpha = Math.max(0, d.life / d.maxLife);
    ctx.fillStyle = d.color;
    ctx.fillRect(-d.size / 2, -d.size / 2, d.size, d.size * 0.6);
    ctx.restore();
  }
  ctx.globalAlpha = 1;
}

// ---------- 主循环 ----------
let last = performance.now();
function loop(t) {
  const dt = Math.min((t - last) / 1000, 0.05);
  last = t;
  dtGlobal = dt;
  update(dt);
  render();
  requestAnimationFrame(loop);
}

// 引擎启动标记（供自动化验证：确认 JS 已成功执行）
const engineMark = document.getElementById('engineMark');
engineMark.textContent = 'ENGINE-READY';

requestAnimationFrame(loop);
