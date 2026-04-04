#!/usr/bin/env python3
"""
マクロフィルタ — VIX/DXY 取得 → ロット係数算出 → JSON 書き出し

TradingView MCP CLI 経由で VIX/DXY の最新値を取得し、
MT5 EA が FileOpen() で読み込める macro_filter.json を生成する。

使い方:
    python scripts/macro_filter.py
    python scripts/macro_filter.py --output /path/to/macro_filter.json
    python scripts/macro_filter.py --dry-run
    python scripts/macro_filter.py --loop 300    # 5分ごとに更新

環境変数:
    TV_CLI — tv コマンドのパス（デフォルト: tv）
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

# JSON 書き出しデフォルトパス（プロジェクトルート）
DEFAULT_OUTPUT = Path(__file__).parent.parent / "macro_filter.json"

# ──────────────────────────────────────────────
# ロット係数ロジック
# ──────────────────────────────────────────────

def calc_lot_multiplier(vix: float) -> tuple[float, str]:
    """
    VIX 値からロット係数とレベル説明を返す。
    VIX <= 20 → 1.0  (通常ボラ)
    VIX <= 25 → 0.75 (やや高ボラ)
    VIX <= 30 → 0.5  (高ボラ)
    VIX >  30 → 0.25 (極高ボラ)
    """
    if vix <= 20.0:
        return 1.0, "VIX<=20: full size"
    if vix <= 25.0:
        return 0.75, "VIX<=25: 75% size"
    if vix <= 30.0:
        return 0.5, "VIX<=30: 50% size"
    return 0.25, "VIX>30: 25% size"


# ──────────────────────────────────────────────
# TV CLI ヘルパー
# ──────────────────────────────────────────────

def tv_cli() -> str:
    return os.getenv("TV_CLI", "tv")


def run_tv(args: list[str], timeout: int = 15) -> Optional[dict]:
    """tv CLI を実行して JSON を返す。失敗時は None。"""
    cmd = [tv_cli()] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            log.debug("tv CLI エラー (exit=%d): %s", result.returncode, result.stderr.strip())
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        log.warning("tv CLI タイムアウト: %s", " ".join(cmd))
        return None
    except json.JSONDecodeError as e:
        log.warning("tv CLI 出力の JSON パース失敗: %s", e)
        return None
    except FileNotFoundError:
        log.error("tv コマンドが見つかりません。tv_autotrading のセットアップを確認してください")
        return None


# ──────────────────────────────────────────────
# VIX/DXY 取得
# ──────────────────────────────────────────────

def _extract_first_numeric(studies: list[dict]) -> Optional[float]:
    """studies リストの最初のエントリから数値を取り出す。"""
    for study in studies:
        for val in study.get("values", {}).values():
            try:
                return float(str(val).replace(",", ""))
            except (ValueError, TypeError):
                continue
    return None


def fetch_via_study_values(symbol_hint: str) -> Optional[float]:
    """
    data_get_study_values (tv values) でインジケータ値を取得する。
    チャートに VIX/DXY が overlay として追加されている場合に有効。
    """
    data = run_tv(["values", "--filter", symbol_hint])
    if not data or not data.get("success") or data.get("study_count", 0) == 0:
        return None
    return _extract_first_numeric(data.get("studies", []))


def fetch_via_symbol_switch(tv_symbol: str, original_symbol: Optional[str] = None) -> Optional[float]:
    """
    chart_set_symbol で一時的にシンボルを切り替えて quote を取得する。
    取得後に元のシンボルへ戻す。
    """
    # 元のシンボルを保存
    if original_symbol is None:
        state = run_tv(["chart", "state"])
        original_symbol = state.get("symbol") if state else None

    # シンボル切り替え
    switch = run_tv(["chart", "set-symbol", tv_symbol], timeout=20)
    if not switch or not switch.get("success"):
        log.warning("シンボル切り替え失敗: %s", tv_symbol)
        return None

    # quote 取得（少し待つ）
    time.sleep(1.5)
    quote = run_tv(["quote"])
    value = None
    if quote and quote.get("success"):
        value = quote.get("close") or quote.get("last")

    # 元に戻す
    if original_symbol:
        run_tv(["chart", "set-symbol", original_symbol], timeout=20)

    return float(value) if value is not None else None


def fetch_vix() -> Optional[float]:
    """VIX を取得。study_values → symbol_switch の順で試みる。"""
    v = fetch_via_study_values("VIX")
    if v is not None:
        log.info("VIX 取得 (study_values): %.2f", v)
        return v
    v = fetch_via_symbol_switch("CBOE:VIX")
    if v is not None:
        log.info("VIX 取得 (symbol_switch): %.2f", v)
    return v


def fetch_dxy() -> Optional[float]:
    """DXY を取得。study_values → symbol_switch の順で試みる。"""
    v = fetch_via_study_values("DXY")
    if v is not None:
        log.info("DXY 取得 (study_values): %.2f", v)
        return v
    v = fetch_via_symbol_switch("TVC:DXY")
    if v is not None:
        log.info("DXY 取得 (symbol_switch): %.2f", v)
    return v


# ──────────────────────────────────────────────
# JSON 生成・書き出し
# ──────────────────────────────────────────────

def build_payload(vix: Optional[float], dxy: Optional[float]) -> dict:
    """macro_filter.json のペイロードを構築する。"""
    now = datetime.now(timezone.utc).isoformat()

    if vix is None:
        lot_mult = 0.5
        note = "VIX unavailable: conservative 50% size"
    else:
        lot_mult, note = calc_lot_multiplier(vix)

    return {
        "timestamp": now,
        "vix": round(vix, 2) if vix is not None else None,
        "dxy": round(dxy, 2) if dxy is not None else None,
        "lot_multiplier": lot_mult,
        "note": note,
    }


def write_json(payload: dict, output_path: Path, dry_run: bool = False) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if dry_run:
        log.info("[DRY RUN] 書き出し先: %s", output_path)
        log.info("[DRY RUN] 内容:\n%s", text)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    log.info("書き出し完了: %s (lot_mult=%.2f)", output_path, payload["lot_multiplier"])


# ──────────────────────────────────────────────
# エントリポイント
# ──────────────────────────────────────────────

def run_once(output_path: Path, dry_run: bool = False) -> dict:
    vix = fetch_vix()
    dxy = fetch_dxy()
    payload = build_payload(vix, dxy)
    write_json(payload, output_path, dry_run=dry_run)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VIX/DXY 取得 → macro_filter.json 書き出し"
    )
    parser.add_argument(
        "--output", "-o",
        default=str(DEFAULT_OUTPUT),
        help="出力 JSON パス (デフォルト: %(default)s)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="書き出しを行わずログのみ出力",
    )
    parser.add_argument(
        "--loop", type=int, metavar="SECONDS",
        help="指定秒ごとに繰り返し実行 (例: --loop 300)",
    )
    args = parser.parse_args()
    output_path = Path(args.output)

    if args.loop:
        log.info("ループモード開始 (interval=%ds)", args.loop)
        while True:
            try:
                run_once(output_path, dry_run=args.dry_run)
            except Exception as e:
                log.error("エラー: %s", e)
            time.sleep(args.loop)
    else:
        payload = run_once(output_path, dry_run=args.dry_run)
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
