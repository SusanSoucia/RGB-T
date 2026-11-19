/* 上传素材 + 划定警戒区域 + 发起检测
 *
 * 画框的坐标逻辑与 MVP 控制台一致（那套已经有无浏览器回归测试）：
 *   - 用 isDrawing 标记驱动，只有按住左键才改矩形
 *   - 松开鼠标结束；小于 2% 的抖动视为单击，丢弃
 *   - 保存前归一化成 x1<x2 / y1<y2
 */
(async function () {
  await requireAuth();
  mountTopbar('tasks');

  const canvas = $('#stage');
  const ctx = canvas.getContext('2d');

  const st = {
    media: null,       // 已上传的媒体
    img: null,         // 当前显示的预览图（Image）
    regions: [],       // 已保存的区域
    drag: null,        // 正在拖的矩形（归一化）
    objUrl: null,
  };

  const MIN_SIZE = 0.02;

  /* ---------------------------------------------------------- 上传 */

  $('#btnUpload').onclick = async () => {
    const f = $('#fileRgb').files[0];
    const msg = $('#uploadMsg');
    msg.innerHTML = '';
    if (!f) { msg.innerHTML = '<div class="form-err">请先选择可见光文件</div>'; return; }

    const fd = new FormData();
    fd.append('file', f);
    const ir = $('#fileIr').files[0];
    if (ir) fd.append('ir_file', ir);

    const btn = $('#btnUpload');
    btn.disabled = true;
    btn.textContent = '上传中…';
    try {
      const media = await api('/media', { method: 'POST', body: fd });
      st.media = media;
      msg.innerHTML = `<div class="form-ok">上传成功：${esc(media.original_name)}
        （${media.media_type}${media.width ? '，' + media.width + '×' + media.height : ''}
        ${media.has_ir ? '，含红外' : ''}）</div>`;
      $('#cardRegion').style.display = '';
      $('#cardDetect').style.display = '';
      await loadPoster();
      await refreshRegions();
    } catch (err) {
      msg.innerHTML = `<div class="form-err">上传失败：${esc(err.message)}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = '上传';
    }
  };

  /** 取预览图：图片用原图，视频用首帧（后端 /poster 统一处理） */
  async function loadPoster() {
    try {
      const url = await blobUrl(`/media/${st.media.id}/poster`);
      if (st.objUrl) URL.revokeObjectURL(st.objUrl); // 不用了，交给缓存管理
      await new Promise((resolve) => {
        const img = new Image();
        img.onload = () => {
          st.img = img;
          canvas.width = img.naturalWidth;
          canvas.height = img.naturalHeight;
          render();
          $('#stageHint').textContent =
            `${st.media.original_name} · ${img.naturalWidth}×${img.naturalHeight}`
            + '　按住左键拖拽即可画框';
          resolve();
        };
        img.onerror = () => { $('#stageHint').textContent = '预览图加载失败'; resolve(); };
        img.src = url;
      });
    } catch (err) {
      $('#stageHint').textContent = '预览图加载失败：' + err.message;
    }
  }

  /* ---------------------------------------------------------- 绘制 */

  function render() {
    if (!st.img) return;
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(st.img, 0, 0, W, H);

    const lw = Math.max(3, Math.round(W / 300));

    // 已保存区域：橙色半透明 + 轮廓 + 名称
    ctx.setLineDash([]);
    for (const r of st.regions) {
      const pts = r.points;
      if (!pts || pts.length < 3) continue;
      ctx.beginPath();
      ctx.moveTo(pts[0][0] * W, pts[0][1] * H);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0] * W, pts[i][1] * H);
      ctx.closePath();
      ctx.fillStyle = 'rgba(245,158,11,.18)';
      ctx.fill();
      ctx.lineWidth = lw;
      ctx.strokeStyle = '#f59e0b';
      ctx.stroke();
      ctx.font = `${Math.max(14, Math.round(W / 50))}px ui-monospace, monospace`;
      ctx.fillStyle = '#b45309';
      ctx.fillText(r.name || `区域${r.id}`, pts[0][0] * W + lw * 2, pts[0][1] * H + Math.max(20, W / 40));
    }

    // 正在拖的矩形：红色虚线 + 半透明
    if (st.drag) {
      const x1 = Math.min(st.drag.x1, st.drag.x2), y1 = Math.min(st.drag.y1, st.drag.y2);
      const x2 = Math.max(st.drag.x1, st.drag.x2), y2 = Math.max(st.drag.y1, st.drag.y2);
      ctx.setLineDash([10, 8]);
      ctx.lineWidth = lw;
      ctx.strokeStyle = '#ef4444';
      ctx.fillStyle = 'rgba(239,68,68,.12)';
      ctx.fillRect(x1 * W, y1 * H, (x2 - x1) * W, (y2 - y1) * H);
      ctx.strokeRect(x1 * W, y1 * H, (x2 - x1) * W, (y2 - y1) * H);
      ctx.setLineDash([]);
    }
  }

  /* ---------------------------------------------------------- 画框交互 */

  let drawing = false;

  function norm(ev) {
    const r = canvas.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height)),
    };
  }

  function dragRect() {
    if (!st.drag) return null;
    return {
      x1: Math.min(st.drag.x1, st.drag.x2), y1: Math.min(st.drag.y1, st.drag.y2),
      x2: Math.max(st.drag.x1, st.drag.x2), y2: Math.max(st.drag.y1, st.drag.y2),
    };
  }

  const valid = (r) => !!r && (r.x2 - r.x1) >= MIN_SIZE && (r.y2 - r.y1) >= MIN_SIZE;

  canvas.addEventListener('mousedown', (ev) => {
    if (!st.img || ev.button !== 0) return;
    ev.preventDefault();
    const p = norm(ev);
    st.drag = { x1: p.x, y1: p.y, x2: p.x, y2: p.y };
    drawing = true;
    $('#btnSaveRegion').disabled = true;
    $('#btnClearDrag').disabled = false;
    render();
  });

  canvas.addEventListener('mousemove', (ev) => {
    if (!drawing || !st.drag) return;   // 没按住左键就什么都不做
    const p = norm(ev);
    st.drag.x2 = p.x;
    st.drag.y2 = p.y;
    $('#btnSaveRegion').disabled = !valid(dragRect());
    render();
  });

  function endDrag() {
    if (!drawing) return;
    drawing = false;
    if (!valid(dragRect())) {          // 单击或抖动太小 → 丢弃
      st.drag = null;
      $('#btnSaveRegion').disabled = true;
      $('#btnClearDrag').disabled = true;
    }
    render();
  }
  canvas.addEventListener('mouseup', endDrag);
  window.addEventListener('mouseup', endDrag);

  $('#btnClearDrag').onclick = () => {
    st.drag = null; drawing = false;
    $('#btnSaveRegion').disabled = true;
    $('#btnClearDrag').disabled = true;
    render();
  };

  $('#btnSaveRegion').onclick = async () => {
    if (!st.media) return;
    const r = dragRect();
    if (!valid(r)) { toast('请先在画面上拖出一个像样的矩形', true); return; }

    const pts = [[r.x1, r.y1], [r.x2, r.y1], [r.x2, r.y2], [r.x1, r.y2]]
      .map((p) => [+p[0].toFixed(5), +p[1].toFixed(5)]);

    try {
      const saved = await api('/regions', {
        method: 'POST',
        body: {
          media_id: st.media.id,
          name: '区域' + (st.regions.length + 1),
          shape_type: 'rect',
          points: pts,
        },
      });
      toast(`区域 #${saved.id} 已保存`);
      st.drag = null;
      drawing = false;
      $('#btnSaveRegion').disabled = true;
      $('#btnClearDrag').disabled = true;
      await refreshRegions();
    } catch (err) {
      toast('保存区域失败：' + err.message, true);
    }
  };

  async function refreshRegions() {
    st.regions = await api('/regions?media_id=' + st.media.id);
    const box = $('#regionList');
    if (!st.regions.length) {
      box.innerHTML = '尚未创建区域（没有区域就不会产生侵入告警）';
    } else {
      box.innerHTML = st.regions
        .map((x) => `#${x.id} ${esc(x.name)}（${x.shape_type}，${x.points.length} 点）`)
        .join('<br>');
    }
    render();
  }

  /* ---------------------------------------------------------- 发起检测 */

  $('#btnDetect').onclick = async () => {
    if (!st.media) return;
    const btn = $('#btnDetect');
    const msg = $('#detectMsg');
    msg.innerHTML = '';
    btn.disabled = true;
    btn.textContent = '检测中…';
    try {
      const task = await api('/detect-tasks', {
        method: 'POST',
        body: { media_id: st.media.id, requested_mode: $('#mode').value },
      });
      location.href = `task.html?id=${task.id}`;
    } catch (err) {
      msg.innerHTML = `<div class="form-err">检测失败：${esc(err.message)}</div>`;
      btn.disabled = false;
      btn.textContent = '开始检测';
    }
  };
})();
