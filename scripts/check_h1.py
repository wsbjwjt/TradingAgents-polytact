"""在 polytact-studio 容器内跑：渲染层视角检查全部报告的 H1 归一结果。"""
from pathlib import Path

from studio.core.config import Config
from studio.core.client import TradingAgentsClient
from studio.digest.fetcher import _from_dir
from studio.notify.report_server import split_sections

cfg = Config.load(Path("/data/studio/studio.yaml"))
client = TradingAgentsClient(cfg)
ta_dir = Path(str(cfg.get("data.ta_dir")))
base = ta_dir / "analysis_results"

n_bad = 0
for sym_dir in sorted(base.iterdir()):
    if not sym_dir.is_dir():
        continue
    doc = _from_dir(ta_dir, sym_dir.name)
    if not doc:
        continue
    name = client.stock_name(doc.symbol)
    for label, body in split_sections(doc.text, symbol=doc.symbol, name=name):
        h1 = next((line for line in body.splitlines() if line.startswith("# ")), "")
        if not h1:
            print(f"[无H1] {doc.symbol} {doc.date} {label}")
            continue
        bad = name and (h1.count(name) > 1 or h1.count(doc.symbol) > 1 or "（）" in h1 or "()" in h1)
        flag = "❌重复" if bad else "OK"
        if bad:
            n_bad += 1
        print(f"{flag} {doc.symbol} {doc.date} [{label}] {h1}")
print(f"\n共 {n_bad} 个问题 H1")
