/* 前端运行时配置
 *
 * ⚠️ 改了 .env 里的 API_PORT，这里要同步改，否则前端连不上后端。
 *
 * 为什么不用 8000：8000 是最常见的开发端口之一，很容易被别的服务占用；
 * 而且 Windows 的 Hyper-V/WSL 会动态保留端口段（5173 就曾被整段占掉）。
 * 所以本项目把宿主端口放到 15k–18k 这个冷门区间：
 *
 *     后端 API   → http://localhost:17800
 *     前端页面   → http://localhost:17880
 *     数据库     → localhost:15432
 *
 * 想临时指向别的后端（比如连同学的机器），在浏览器控制台执行：
 *     localStorage.setItem('apiBase', 'http://192.168.1.20:17800')
 *     location.reload()
 * 清除覆盖：
 *     localStorage.removeItem('apiBase')
 */
window.APP_CONFIG = {
  apiPort: 17800,
};
