/* 界面 2：注册 */
(async function () {
  if (await redirectIfLoggedIn()) return;

  const form = $('#regForm');
  form.onsubmit = async (e) => {
    e.preventDefault();
    const msg = $('#regMsg');
    msg.innerHTML = '';

    const username = $('#rUser').value.trim();
    const password = $('#rPwd').value;
    const display_name = $('#rName').value.trim() || null;

    if (username.length < 3) {
      msg.innerHTML = '<div class="form-err">账号至少 3 个字符</div>';
      return;
    }
    if (password.length < 6) {
      msg.innerHTML = '<div class="form-err">密码至少 6 位</div>';
      return;
    }

    const btn = $('#btnReg');
    btn.disabled = true;
    btn.textContent = '提交中…';
    try {
      await api('/auth/register', { method: 'POST', body: { username, password, display_name } });
      msg.innerHTML = '<div class="form-ok">注册成功，正在登录…</div>';

      // 注册完直接登录，省得再手输一次密码
      try {
        const data = await api('/auth/login', { method: 'POST', body: { username, password } });
        AUTH.token = data.access_token;
        AUTH.user = data.user;
        localStorage.setItem('token', AUTH.token);
        location.replace('tasks.html');
        return;
      } catch {
        // 自动登录失败不阻断：退回手动登录页
        setTimeout(() => { location.replace('login.html'); }, 800);
        return;
      }
    } catch (err) {
      // 后端默认开放注册；只有被显式关掉时才会走到这里
      const tip = err.code === 'REGISTER_DISABLED'
        ? '管理员暂时关闭了自主注册，请联系管理员开通账号。'
        : err.code === 'AUTH_USERNAME_TAKEN' ? '该用户名已被占用，换一个试试。' : err.message;
      msg.innerHTML = `<div class="form-err">${esc(tip)}</div>`;
      btn.disabled = false;
      btn.textContent = '注 册';
    }
  };
})();
