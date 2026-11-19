// 用桩 DOM 驱动真实的 index.html 内嵌脚本，验证画框行为。
// 目的：不靠肉眼，直接断言「没按住左键时不会改框」「单击不留退化矩形」。
//
// 为什么值得存在：画框的坐标逻辑（归一化、边界、反向拖拽）是需求 §3.2.1
// 的验收点，但它在 canvas 里，肉眼很难验证对错。这套桩把 DOM 抽掉，
// 直接在 Node 里跑真实代码，改坏了会立刻红。
//
// 运行（在项目根目录）：
//     node frontend/mvp/test/draw.test.js frontend/mvp/index.html
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const HTML = process.argv[2];
const html = fs.readFileSync(HTML, 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
if (!m) { console.error('没找到 <script>'); process.exit(1); }

// ---------------- 桩 ----------------
const handlers = new Map();       // element -> { type: fn }
function makeEl(id) {
  const el = {
    id,
    style: {},
    disabled: false,
    innerHTML: '',
    textContent: '',
    value: '',
    files: [],
    children: [],
    classList: { toggle() {}, add() {}, remove() {} },
    firstChild: null,
    addEventListener(type, fn) {
      if (!handlers.has(el)) handlers.set(el, {});
      handlers.get(el)[type] = fn;
    },
    appendChild(c) { el.children.push(c); },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 800, height: 600 }; },
  };
  return el;
}

const els = new Map();
const getEl = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };

const calls = { beginPath: 0, stroke: 0, fill: 0, fillText: 0, strokeRect: 0 };
const ctx2d = {
  clearRect() {}, drawImage() {}, fillRect() {}, strokeRect() { calls.strokeRect++; },
  beginPath() { calls.beginPath++; }, moveTo() {}, lineTo() {}, closePath() {},
  fill() { calls.fill++; }, stroke() { calls.stroke++; },
  setLineDash() {}, fillText() { calls.fillText++; },
  set lineWidth(v) {}, set strokeStyle(v) {}, set fillStyle(v) {}, set font(v) {},
};
const canvas = getEl('stage');
canvas.width = 960; canvas.height = 540;
canvas.getContext = () => ctx2d;

const winHandlers = {};
const sandbox = {
  console,
  document: {
    getElementById: getEl,
    createElement: () => makeEl('tmp'),
  },
  window: {
    addEventListener(type, fn) { winHandlers[type] = fn; },
  },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  fetch: () => Promise.reject(new Error('no network in test')),
  Image: class { set src(v) { if (this.onerror) this.onerror(new Error('no img')); } },
  URL: { createObjectURL: () => 'blob:stub', revokeObjectURL() {} },
  setTimeout, clearTimeout, Promise, JSON, Math, Date, String, Number, Array, Object,
};
sandbox.globalThis = sandbox;

// 暴露内部状态供断言
const patched = m[1] + '\n;globalThis.__T = { get S(){return S;}, dragRect, rectIsValid, render, canvas: canvas };\n';
vm.createContext(sandbox);
try {
  vm.runInContext(patched, sandbox, { filename: 'mvp-inline.js' });
} catch (e) {
  console.error('脚本执行失败：', e.message);
  process.exit(1);
}

const T = sandbox.__T;
const C = T.canvas;
// mousedown 有"画布上必须有图"的前置判断，这里塞一个桩图
T.S.img = { naturalWidth: 800, naturalHeight: 600 };
const h = handlers.get(C) || {};
const down = h.mousedown, move = h.mousemove, up = h.mouseup || winHandlers.mouseup;
const saveBtn = getEl('btnSaveRegion');

let pass = 0, fail = 0;
function ok(cond, name, extra = '') {
  if (cond) { pass++; console.log(`  [ok] ${name}`); }
  else { fail++; console.log(`  [FAIL] ${name} ${extra}`); }
}
const ev = (x, y, button = 0) => ({ clientX: x, clientY: y, button, preventDefault() {} });

const hasAll = down && move && up;
ok(hasAll, '三个鼠标事件都已注册', `down=${!!down} move=${!!move} up=${!!up}`);
if (!hasAll) process.exit(1);

console.log('\n[1] 只有 mousedown 没有移动时，不应留下可见矩形尺寸');
down(ev(100, 100));
ok(T.dragRect().x2 - T.dragRect().x1 === 0, 'mousedown 后矩形尺寸为 0');
ok(saveBtn.disabled === true, '保存按钮仍禁用');

console.log('\n[2] 单击（按下即松开）应被丢弃，不留退化矩形');
up();
ok(T.S.drag === null, '松开后 drag 被清空');
ok(saveBtn.disabled === true, '保存按钮保持禁用');

console.log('\n[3] 松开鼠标后移动鼠标，绝不能继续改框（本次修复的核心）');
down(ev(100, 100));
move(ev(300, 300));
const before = JSON.stringify(T.S.drag);
up();
move(ev(700, 500));
const after = JSON.stringify(T.S.drag);
ok(before === after, '松开后 mousemove 不再影响矩形', `before=${before} after=${after}`);

console.log('\n[4] 正常拖拽：矩形归一化且保存按钮启用');
down(ev(100, 100));
move(ev(400, 350));
const r = T.dragRect();
ok(r.x1 === 100 / 800 && r.x2 === 400 / 800, `x 归一化正确 (${r.x1}, ${r.x2})`);
ok(r.y1 === 100 / 600 && r.y2 === 350 / 600, `y 归一化正确 (${r.y1}, ${r.y2})`);
ok(saveBtn.disabled === false, '保存按钮已启用');
ok(T.rectIsValid(r) === true, 'rectIsValid 判定有效');

console.log('\n[5] 反向拖拽（从右下往左上）也应归一化成 x1<x2, y1<y2');
up();
down(ev(500, 450));
move(ev(150, 120));
const r2 = T.dragRect();
ok(r2.x1 < r2.x2 && r2.y1 < r2.y2, `反向拖拽已归一化 (${r2.x1},${r2.y1})-(${r2.x2},${r2.y2})`);
ok(Math.abs(r2.x1 - 150 / 800) < 1e-9 && Math.abs(r2.x2 - 500 / 800) < 1e-9, 'x 上下界正确');

console.log('\n[6] 极小抖动（<2%）视为点击，不保留');
up();
down(ev(200, 200));
move(ev(203, 202));
ok(T.rectIsValid(T.dragRect()) === false, '微小拖动判为无效');
up();
ok(T.S.drag === null, '无效矩形被清除');

console.log('\n[7] 已保存的区域必须真的被画出来（填充 + 描边 + 名称）');
T.S.drag = null;
T.S.regions = [
  { id: 1, name: '区域1', shape_type: 'rect',
    points: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]] },
];
calls.beginPath = calls.stroke = calls.fill = calls.fillText = 0;
T.render();
ok(calls.beginPath >= 1, `beginPath 被调用 ${calls.beginPath} 次`);
ok(calls.fill >= 1, `区域有半透明填充（fill ${calls.fill} 次）`);
ok(calls.stroke >= 1, `区域有轮廓描边（stroke ${calls.stroke} 次）`);
ok(calls.fillText >= 1, `区域名称被绘制（fillText ${calls.fillText} 次）`);

console.log(`\n结果：${pass} 通过，${fail} 失败`);
process.exit(fail ? 1 : 0);
