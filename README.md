# edge-installer

Microsoft Edge 离线安装包下载页（官方 CDP API 直链）

- 数据来源：msedge.api.cdp.microsoft.com（微软官方 CDP API）
- 版本：Windows x64 / ARM64 稳定版
- 部署：Cloudflare Pages → edge_installer.pages.dev

## 自动更新

GitHub Actions 每天自动探测最新版本，更新 index.html 内嵌数据并推送，
触发 Cloudflare Pages 自动部署。
