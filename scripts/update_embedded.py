#!/usr/bin/env python3
"""探测 Microsoft Edge 最新版本，更新 index.html 内嵌数据"""
import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone, timedelta

UA = "Microsoft Edge Update/1.3.183.29;winhttp"
APPIDS = {
    "x64": "msedge-stable-win-x64",
    "arm64": "msedge-stable-win-arm64",
}


def probe(appid: str):
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
    return {"version": version, "size": size, "downloadURL": url}


def main():
    new_data = {"checked_at": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")}
    for key, appid in APPIDS.items():
        try:
            new_data[key] = probe(appid)
            print(f"{key}: v{new_data[key]['version']} {new_data[key]['size']}")
        except Exception as e:
            print(f"{key} 探测失败: {e}")

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # 替换 EMBEDDED_DATA JSON 块（从 "var EMBEDDED_DATA = {" 到 "};"）
    pattern = re.compile(r"var EMBEDDED_DATA = \{.*?\};", re.S)
    block = "var EMBEDDED_DATA = " + json.dumps(new_data, ensure_ascii=False, indent=2) + ";"
    new_html, n = pattern.subn(block, html)
    if n == 0:
        raise RuntimeError("未找到 EMBEDDED_DATA 块")
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(new_html)
    print("index.html 已更新")


if __name__ == "__main__":
    main()
