#!/usr/bin/env python3
"""探测 Microsoft Edge 全部通道最新版本（稳定/Beta/Dev/Canary/Win7/企业版MSI），更新 index.html 内嵌数据

数据源（全部为微软官方接口，不依赖任何 GitHub 仓库，可长期运行）：
- 消费版（stable/beta/dev/canary）：微软 CDP API（msedge.api.cdp.microsoft.com）
- Win7/Win8 最终版（109.0.1518.140，含 x64/x86/arm64）：微软 CDP API，
  product name 为 msedge-stable-win7and8-{x64|x86|arm64}
- 企业版 MSI：微软官方 edgeupdates API（edgeupdates.microsoft.com/api/products?view=enterprise）
"""
import base64
import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone

UA = "Microsoft Edge Update/1.3.183.29;winhttp"
# (key, product_name, channel_label, arch) —— 消费版（CDP API）
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

# (key, product_name, arch) —— Win7/Win8 最终版（CDP API，109.0.1518.140）
WIN7_TARGETS = [
    ("win7-x64",   "msedge-stable-win7and8-x64",   "x64"),
    ("win7-x86",   "msedge-stable-win7and8-x86",   "x86"),
    ("win7-arm64", "msedge-stable-win7and8-arm64", "arm64"),
]


def _ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _norm_url(raw: str) -> str:
    """统一升级为 https + sb 子域（f/b 子域均指向同一文件流，签名有效）"""
    return raw.replace("http://msedge.f", "https://msedge.sb").replace("http://msedge.b", "https://msedge.sb")


def _parse_file(f: dict) -> dict:
    sha_b64 = (f.get("Hashes") or {}).get("Sha256", "")
    sha256 = base64.b64decode(sha_b64).hex().lower() if sha_b64 else ""
    return {
        "size": f"{f.get('SizeInBytes', 0) / 1048576:.0f}MB",
        "downloadURL": _norm_url(f.get("Url", "")),
        "sha256": sha256,
        "fileName": f.get("FileId") or "MicrosoftEdge.exe",
    }


def probe_cdp(name: str, files_path: str = "v1.1/internal"):
    """通用 CDP 两步探测：取版本 + 取最大安装包"""
    ctx = _ctx()
    headers = {"User-Agent": UA, "Content-Type": "application/json"}
    body = json.dumps(
        {"targetingAttributes": {"IsInternalUser": True, "Updater": "MicrosoftEdgeUpdate", "UpdaterVersion": "1.3.183.29"}}
    ).encode()

    url1 = f"https://msedge.api.cdp.microsoft.com/api/v2/contents/Browser/namespaces/Default/names/{name}/versions/latest?action=select"
    req = urllib.request.Request(url1, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        data1 = json.loads(resp.read().decode())
    version = data1.get("ContentId", {}).get("Version", "")

    url2 = (f"https://msedge.api.cdp.microsoft.com/api/{files_path}/contents/Browser/namespaces/Default/"
            f"names/{name}/versions/{version}/files?action=GenerateDownloadInfo")
    req = urllib.request.Request(url2, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        files = json.loads(resp.read().decode())
    files = files if isinstance(files, list) else files.get("Files", [])
    files.sort(key=lambda x: x.get("SizeInBytes", 0), reverse=True)
    out = _parse_file(files[0])
    out["version"] = version
    return out


def probe_enterprise():
    """企业版 MSI：edgeupdates API 取各架构最新 Stable 的 msi artifact"""
    ctx = _ctx()
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
    for key, name, label, arch in TARGETS:
        try:
            info = probe_cdp(name)
            info["key"] = key
            info["channel"] = label
            info["arch"] = arch
            items.append(info)
            print(f"{key}: v{info['version']} {info['size']}")
        except Exception as e:
            print(f"{key} 探测失败: {e}")

    # Win7/Win8 最终版（CDP API，v2 路径已验证）
    for key, name, arch in WIN7_TARGETS:
        try:
            info = probe_cdp(name, files_path="v2")
            info["key"] = key
            info["channel"] = "Win7/2008R2"
            info["arch"] = arch
            items.append(info)
            print(f"{key}: v{info['version']} {info['size']} sha={info['sha256'][:12]}")
        except Exception as e:
            print(f"{key} 探测失败: {e}")

    try:
        ent = probe_enterprise()
        items.extend(ent)
        for e in ent:
            print(f"enterprise-{e['arch']}: v{e['version']} {e['size']} {e['fileName']}")
    except Exception as e:
        print(f"企业版探测失败: {e}")

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
