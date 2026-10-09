#!/usr/bin/env python3
"""探测 Microsoft Edge 全部通道最新版本（稳定/Beta/Dev/Canary/Win7/企业版MSI），更新 index.html 内嵌数据

数据源：
- 消费版（stable/beta/dev/canary）：微软 CDP API（msedge.api.cdp.microsoft.com）
- 企业版 MSI：微软官方 edgeupdates API（edgeupdates.microsoft.com/api/products?view=enterprise）
- Win7：微软已于 2023-01 停止 Win7 支持（Edge 109 为最终版，CDP 数据流已下线），
  固定使用官方最终版 109.0.1518.140，下载入口为微软 Update Catalog 官方页
"""
import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone

UA = "Microsoft Edge Update/1.3.183.29;winhttp"
# (key, appid, channel_label, arch) —— 消费版（CDP API）
TARGETS = [
    ("stable-x64",      "msedge-stable-win-x64",                   "稳定版",   "x64"),
    ("stable-x86",      "msedge-stable-win-x86",                   "稳定版",   "x86"),
    ("stable-arm64",    "msedge-stable-win-arm64",                 "稳定版",   "arm64"),
    ("beta-x64",        "msedge-beta-win-x64",                     "Beta",     "x64"),
    ("beta-x86",        "msedge-beta-win-x86",                     "Beta",     "x86"),
    ("beta-arm64",      "msedge-beta-win-arm64",                   "Beta",     "arm64"),
    ("dev-x64",         "msedge-dev-win-x64",                      "Dev",      "x64"),
    ("dev-x86",         "msedge-dev-win-x86",                      "Dev",      "x86"),
    ("dev-arm64",       "msedge-dev-win-arm64",                    "Dev",      "arm64"),
    ("canary-x64",      "msedge-canary-win-x64",                   "Canary",   "x64"),
    ("canary-x86",      "msedge-canary-win-x86",                   "Canary",   "x86"),
    ("canary-arm64",    "msedge-canary-win-arm64",                 "Canary",   "arm64"),
]

# Win7 固定条目（微软官方最终版，官方已停止支持）
WIN7_ITEMS = [
    {"key": "win7-x64", "channel": "Win7/2008R2", "arch": "x64", "version": "109.0.1518.140",
     "size": "127MB", "fileName": "MicrosoftEdge-109-x64（官方Update Catalog）", "sha256": "",
     "downloadURL": "https://www.catalog.update.microsoft.com/Search.aspx?q=edge-stable-109"},
    {"key": "win7-x86", "channel": "Win7/2008R2", "arch": "x86", "version": "109.0.1518.140",
     "size": "127MB", "fileName": "MicrosoftEdge-109-x86（官方Update Catalog）", "sha256": "",
     "downloadURL": "https://www.catalog.update.microsoft.com/Search.aspx?q=edge-stable-109"},
]


def probe_cdp(appid: str, channel: str, arch: str):
    """消费版：CDP API 探测最新版本与最大安装包"""
    import base64
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {"User-Agent": UA, "Content-Type": "application/json"}

    url1 = f"https://msedge.api.cdp.microsoft.com/api/v2/contents/Browser/namespaces/Default/names/{appid}/versions/latest?action=select"
    body1 = json.dumps(
        {"targetingAttributes": {"IsInternalUser": True, "Updater": "MicrosoftEdgeUpdate", "UpdaterVersion": "1.3.183.29"}}
    ).encode()
    req = urllib.request.Request(url1, data=body1, headers=headers)
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        data1 = json.loads(resp.read().decode())
    version = data1.get("ContentId", {}).get("Version", "")

    url2 = f"https://msedge.api.cdp.microsoft.com/api/v1.1/internal/contents/Browser/namespaces/Default/names/{appid}/versions/{version}/files?action=GenerateDownloadInfo"
    req = urllib.request.Request(url2, data=b"", headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        files = json.loads(resp.read().decode())
    files.sort(key=lambda x: x.get("SizeInBytes", 0), reverse=True)
    f = files[0]
    url = f.get("Url", "").replace("http://msedge.b", "https://msedge.sb")
    size = f"{f.get('SizeInBytes', 0) / 1048576:.0f}MB"
    # CDP 的 Sha256 为 base64 编码，转为 hex 小写
    sha_b64 = (f.get("Hashes") or {}).get("Sha256", "")
    sha256 = base64.b64decode(sha_b64).hex().lower() if sha_b64 else ""
    # 真实文件名在 FileId 字段
    fname = f.get("FileId") or f"msedge_{channel}_{arch}_{version}.exe"
    return {"version": version, "size": size, "downloadURL": url, "sha256": sha256, "fileName": fname}


def probe_enterprise():
    """企业版 MSI：edgeupdates API 取各架构最新 Stable 的 msi artifact"""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        "https://edgeupdates.microsoft.com/api/products?view=enterprise",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        data = json.loads(resp.read().decode())
    items = []
    arch_map = {"x64": "x64", "x86": "x86", "arm64": "arm64"}
    seen = set()
    for prod in data:
        if prod.get("Product") != "Stable":
            continue
        for rel in prod.get("Releases", []):
            if rel.get("Platform") != "Windows":
                continue
            arch = arch_map.get(rel.get("Architecture"))
            if not arch or arch in seen:
                continue
            for a in rel.get("Artifacts", []):
                if a.get("ArtifactName") == "msi":
                    loc = a.get("Location", "")
                    fname = loc.split("/")[-1] or f"MicrosoftEdgeEnterprise{arch.capitalize()}.msi"
                    items.append({
                        "key": f"enterprise-{arch}", "channel": "企业版MSI", "arch": arch,
                        "version": rel.get("ProductVersion", ""),
                        "size": f"{a.get('SizeInBytes', 0) / 1048576:.0f}MB",
                        "downloadURL": loc,
                        "sha256": (a.get("Hash") or "").lower(),
                        "fileName": fname,
                    })
                    seen.add(arch)
                    break
    return items


def main():
    items = []
    for key, appid, label, arch in TARGETS:
        try:
            info = probe_cdp(appid, key.split("-")[0], arch)
            info["key"] = key
            info["channel"] = label
            info["arch"] = arch
            items.append(info)
            print(f"{key}: v{info['version']} {info['size']}")
        except Exception as e:
            print(f"{key} 探测失败: {e}")

    try:
        ent = probe_enterprise()
        items.extend(ent)
        for e in ent:
            print(f"enterprise-{e['arch']}: v{e['version']} {e['size']} {e['fileName']}")
    except Exception as e:
        print(f"企业版探测失败: {e}")

    items.extend(WIN7_ITEMS)
    for w in WIN7_ITEMS:
        print(f"{w['key']}: v{w['version']}（官方最终版，已停止更新）")

    new_data = {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": items,
    }

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    pattern = re.compile(r"var EMBEDDED_DATA = \{.*?\};", re.S)
    block = "var EMBEDDED_DATA = " + json.dumps(new_data, ensure_ascii=False, indent=2) + ";"
    new_html, n = pattern.subn(block, html)
    if n == 0:
        raise RuntimeError("未找到 EMBEDDED_DATA 块")
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(new_html)
    print(f"index.html 已更新（{len(items)} 个版本条目）")


if __name__ == "__main__":
    main()
