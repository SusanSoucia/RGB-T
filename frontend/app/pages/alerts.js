/* 业务界面 3：报警情况 */
(async function () {
  await requireAuth();
  mountTopbar('alerts');

  const box = $('#alertsBox');
  const filter = $('#alertFilter');

  async function load() {
    box.innerHTML = '<div class="card"><div class="empty">加载中…</div></div>';
    const status = filter.value;
    try {
      const page = await api(`/alerts?page=1&page_size=60${status ? '&status=' + status : ''}`);
      if (!page.items.length) {
        box.innerHTML = '<div class="card"><div class="empty">暂无报警记录。</div></div>';
        return;
      }
      box.innerHTML = `<div class="gallery">${page.items.map(cardHtml).join('')}</div>`;

      // 卡片点击 → 详情页对应任务
      $$('.thumb-card', box).forEach((card) => {
        card.onclick = (e) => {
          if (e.target.closest('[data-confirm]')) return;
          location.href = `task.html?id=${card.dataset.task}`;
        };
      });

      // 确认按钮
      $$('[data-confirm]', box).forEach((btn) => {
        btn.onclick = async (e) => {
          e.stopPropagation();
          btn.disabled = true;
          try {
            await api(`/alerts/${btn.dataset.confirm}/confirm`, { method: 'POST' });
            toast('已确认');
            await load();
          } catch (err) {
            toast(err.message, true);
            btn.disabled = false;
          }
        };
      });

      // 缩略图逐张异步加载（必须带 token 取 blob）
      $$('.thumb', box).forEach(async (el) => {
        const src = el.dataset.src;
        if (!src) { el.innerHTML = '<span class="ph">无截图</span>'; return; }
        try {
          const url = await blobUrl(src);
          el.innerHTML = `<img alt="报警帧" src="${url}" />`;
        } catch {
          el.innerHTML = '<span class="ph">截图加载失败</span>';
        }
      });
    } catch (err) {
      box.innerHTML = `<div class="card"><div class="empty">加载失败：${esc(err.message)}</div></div>`;
    }
  }

  function cardHtml(a) {
    return `
      <div class="thumb-card" data-task="${a.task_id}" data-frame="${a.frame_index}">
        <div class="thumb" data-src="${a.snapshot_url || ''}">
          <span class="ph">加载缩略图…</span>
        </div>
        <div class="info">
          <div class="t1">
            <span>${esc(a.media_name || '媒体 ' + a.media_id)}</span>
            <span>帧 ${a.frame_index}</span>
          </div>
          <div class="t2">${fmtTime(a.first_seen_at)}</div>
          <div class="t1" style="margin-top:4px">
            <span>分数 ${a.score_max.toFixed(3)}</span>
            <span>×${a.occurrence_count}</span>
          </div>
          <div class="row2">
            ${a.status === 'confirmed'
              ? '<span class="tag ok">已确认</span>'
              : '<span class="tag warn">未确认</span>'}
            ${a.status === 'confirmed'
              ? ''
              : `<button class="btn sm" data-confirm="${a.id}">确认</button>`}
          </div>
        </div>
      </div>`;
  }

  $('#refreshAlerts').onclick = load;
  filter.onchange = load;
  await load();
})();
