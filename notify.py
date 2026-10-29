#!/usr/bin/env python3
"""夸克签到结果 -> WxPusher 推送。

两种凭证任选其一（都从环境变量读，不进代码）：
  * 极简 SPT：WXPUSHER_SPT=SPT_xxx
  * 标准应用：WXPUSHER_APP_TOKEN=AT_xxx + WXPUSHER_UIDS=UID_xxx（或 WXPUSHER_TOPIC_IDS=123）

用法：
  python notify.py                       # 读 ./sign.log + $SIGN_OUTCOME 后推送
  python notify.py --dry-run             # 只打印将要发送的内容
  python notify.py --log x.log --outcome failure
"""
import argparse
import json
import os
import re
import sys
import urllib.request

API_STD = "https://wxpusher.zjiecode.com/api/send/message"
API_SPT = "https://wxpusher.zjiecode.com/api/send/message/simple-push"
MAX_CONTENT = 40000
ANSI = re.compile(r"\x1b\[[0-9;]*m")
TS = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?")


def clean(text: str) -> str:
    return TS.sub("", ANSI.sub("", text)).strip()


def parse_log(path: str, outcome: str):
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [clean(l) for l in f]
    joined = "\n".join(lines)

    accounts = re.search(r"检测到共\s*(\d+)\s*个", joined)
    cap = re.search(r"网盘总容量：([\d.]+\s*[TGM]B)[，,]\s*签到累计容量：([\d.]+\s*[TGM]B)", joined)
    sign = re.search(r"(✅\s*今日已签到[^\n]*|✅\s*签到成功[^\n]*|❌\s*[^\n]*)", joined)
    err = [l for l in lines if re.search(r"(❌|失败|ERROR|Traceback|require login|401|403|500)", l)]

    facts = []
    if accounts:
        facts.append(f"账号：{accounts.group(1)} 个")
    if cap:
        facts.append(f"网盘总容量：{cap.group(1)}（签到累计 {cap.group(2)}）")
    if sign:
        facts.append(f"结果：{sign.group(1)}")

    ok = outcome != "failure" and not re.search(r"(❌\s*\S*失败|Traceback|require login)", joined)
    if outcome in ("failure", "cancelled"):
        ok = False
    title = "夸克签到 ✅" if ok else "夸克签到 ❌"
    if ok and sign and "今日已签到" in sign.group(1):
        title = "夸克签到 ✅ 今日已签"

    bits = [title]
    if cap:
        bits.append(cap.group(2))
    if sign:
        m = re.search(r"[+\-]?[\d.]+\s*[KMGT]B", sign.group(1))
        if m:
            bits.append(m.group(0))
        m = re.search(r"连签进度?（?([\d/]+)）?", sign.group(1))
        if m:
            bits.append(f"连签 {m.group(1)}")
    summary = " ".join(bits)[:100]

    body = [f"## {title}", ""]
    body += [f"- {x}" for x in facts] or ["- 没有从日志中解析到签到结果"]
    if not ok:
        tail = "\n".join(err[-6:]) if err else "\n".join(lines[-10:])
        body += ["", "```", tail[-1500:], "```"]
    body += ["", f"运行：{os.getenv('GITHUB_SERVER_URL', '')}/{os.getenv('GITHUB_REPOSITORY', '')}/actions/runs/{os.getenv('GITHUB_RUN_ID', '')}".rstrip("/")]
    return summary, "\n".join(body)[:MAX_CONTENT]


def send(payload: dict, url: str):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    import ssl
    ctx = ssl._create_unverified_context()  # 兼容抓包/公司代理环境
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="sign.log")
    ap.add_argument("--outcome", default=os.getenv("SIGN_OUTCOME", "success"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    summary, content = parse_log(a.log, a.outcome)
    spt = os.getenv("WXPUSHER_SPT", "").strip()
    app = os.getenv("WXPUSHER_APP_TOKEN", "").strip()
    uids = [x.strip() for x in os.getenv("WXPUSHER_UIDS", "").replace(",", " ").split() if x.strip()]
    topics = [int(x) for x in os.getenv("WXPUSHER_TOPIC_IDS", "").replace(",", " ").split() if x.strip().isdigit()]

    if a.dry_run:
        print(f"[summary] {summary}\n\n{content}")
        return 0
    if not spt and not (app and (uids or topics)):
        print("跳过推送：未配置 WXPUSHER_SPT 或 WXPUSHER_APP_TOKEN + WXPUSHER_UIDS/TOPIC_IDS")
        return 0

    payload = {"content": content, "summary": summary, "contentType": 3}
    if spt:
        payload["spt"] = spt
        url = API_SPT
    else:
        payload["appToken"] = app
        if uids:
            payload["uids"] = uids
        if topics:
            payload["topicIds"] = topics
        url = API_STD

    try:
        resp = send(payload, url)
    except Exception as e:
        print(f"推送异常：{e}")
        return 1
    print("WxPusher 响应：", json.dumps(resp, ensure_ascii=False)[:400])
    return 0 if resp.get("code") == 1000 else 1


if __name__ == "__main__":
    sys.exit(main())
