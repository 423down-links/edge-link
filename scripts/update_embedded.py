#!/usr/bin/env python3
"""探测 Microsoft Edge 全部通道最新版本（稳定/Beta/Dev/Canary/Win7/企业版MSI），更新 index.html 内嵌数据

数据源（全部为微软官方接口，不依赖任何 GitHub 仓库，可长期运行）：
- 消费版（stable/beta/dev/canary）：微软 CDP API（msedge.api.cdp.microsoft.com）
- Win7/Win8 最终版（109.0.1518.140，含 x64/x86/arm64）：微软 CDP API，
  product name 为 msedge-stable-win7and8-{x64|x86|arm64}
- 企业版 MSI：微软官方 edgeupdates API（edgeupdates.microsoft.com/api/products?view=enterprise）
- 官方发布时间（published）：优先取 edgeupdates 的 PublishedTime（Stable/Beta/Dev/企业版，
  权威发布时间）；Canary 与 Win7 不在 edgeupdates，取安装包文件的 Last-Modified（官方文件时间）。
  所有时间统一为带 Z 的 UTC ISO，前端固定换算北京时间（UTC+8）。
"""
import base64
import email.utils as eut
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


def _ensure_z(iso: str) -> str:
    """edgeupdates 的 PublishedTime 无后缀但为 UTC，补 Z 让前端按 UTC 解析"""
    if iso and not iso.endswith("Z"):
        return iso + "Z"
    return iso


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


def head_last_modified(url: str) -> str:
    """HEAD 安装包取 Last-Modified（官方文件时间），返回带 Z 的 UTC ISO"""
    ctx = _ctx()
    for _ in range(3):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
                lm = r.headers.get("Last-Modified")
                if lm:
                    dt = eut.parsedate_to_datetime(lm)
                    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            continue
    return ""


_EDGE_RAW = None


def edgeupdates_raw():
    global _EDGE_RAW
    if _EDGE_RAW is None:
        ctx = _ctx()
        req = urllib.request.Request(
            "https://edgeupdates.microsoft.com/api/products?view=enterprise",
            headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            _EDGE_RAW = json.loads(r.read().decode())
    return _EDGE_RAW


def edge_published(product: str, arch: str, version: str) -> str:
    """edgeupdates 官方发布时间：Product=Stable/Beta/Dev，匹配 Windows/架构/版本"""
    for p in edgeupdates_raw():
        if p.get("Product") != product:
            continue
        for rel in p.get("Releases", []):
            if (rel.get("Platform") == "Windows" and rel.get("Architecture") == arch
                    and rel.get("ProductVersion") == version):
                return _ensure_z(rel.get("PublishedTime"))
    return ""


PRODUCT_BY_CHANNEL = {"稳定版": "Stable", "Beta": "Beta", "Dev": "Dev"}


def probe_enterprise():
    """企业版 MSI：edgeupdates 取各架构最新 Stable 的 msi artifact（带官方发布时间）"""
    items = []
    arch_map = {"x64": "x64", "x86": "x86", "arm64": "arm64"}
    seen = set()
    for prod in edgeupdates_raw():
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
                        "published": _ensure_z(rel.get("PublishedTime")),
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
            # 官方发布时间：Canary 不在 edgeupdates → Last-Modified；其余优先 edgeupdates，失败兜底 Last-Modified
            if label == "Canary":
                info["published"] = head_last_modified(info["downloadURL"])
            else:
                info["published"] = edge_published(PRODUCT_BY_CHANNEL.get(label), arch, info["version"]) \
                    or head_last_modified(info["downloadURL"])
            items.append(info)
            print(f"{key}: v{info['version']} {info['size']} pub={info['published']}")
        except Exception as e:
            print(f"{key} 探测失败: {e}")

    # Win7/Win8 最终版（CDP v2 路径已验证；发布时间取文件 Last-Modified）
    for key, name, arch in WIN7_TARGETS:
        try:
            info = probe_cdp(name, files_path="v2")
            info["key"] = key
            info["channel"] = "Win7/2008R2"
            info["arch"] = arch
            info["published"] = head_last_modified(info["downloadURL"])
            items.append(info)
            print(f"{key}: v{info['version']} {info['size']} pub={info['published']}")
        except Exception as e:
            print(f"{key} 探测失败: {e}")

    try:
        ent = probe_enterprise()
        items.extend(ent)
        for e in ent:
            print(f"enterprise-{e['arch']}: v{e['version']} {e['size']} pub={e['published']}")
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
