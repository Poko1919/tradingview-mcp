#!/usr/bin/env python3
"""
MSB-OB ブリッジ — TradingView Pine データ → crypto_auto_trading

tv CLI 経由で MSB-OB インジケータのラベル・ボックスを読み取り、
crypto_auto_trading の手動シグナル API に POST する。

使い方:
    python scripts/msb_ob_bridge.py --symbol SUIUSDT [--api-url http://localhost:8017]
    python scripts/msb_ob_bridge.py --symbol SUIUSDT --dry-run
    python scripts/msb_ob_bridge.py --symbol SUIUSDT --loop 30
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import requests

# ============================================================
# ロギング設定
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


# ============================================================
# tv CLI ヘルパー
# ============================================================

def run_tv(args: list[str], timeout: int = 15) -> Optional[dict]:
    """tv CLI を実行して JSON を返す。失敗時は None。"""
    cmd = ["tv"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            log.warning("tv CLI エラー (exit=%d): %s", result.returncode, result.stderr.strip())
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        log.error("tv CLI タイムアウト: %s", " ".join(cmd))
        return None
    except json.JSONDecodeError as e:
        log.error("tv CLI 出力の JSON パース失敗: %s", e)
        return None
    except FileNotFoundError:
        log.error("tv コマンドが見つかりません。tv_autotrading のセットアップを確認してください")
        return None


def fetch_labels(study_filter: str = "MSB-OB") -> list[dict]:
    """
    MSB-OB インジケータのラベル一覧を取得する。
    返り値: [{"text": "MSB ↑", "price": 1.2345}, ...]
    """
    data = run_tv(["pine", "labels", "--study-filter", study_filter])
    if not data or not data.get("success"):
        return []

    labels = []
    for study in data.get("studies", []):
        for lbl in study.get("labels", []):
            if lbl.get("text") and lbl.get("price") is not None:
                labels.append({
                    "text":  lbl["text"],
                    "price": float(lbl["price"]),
                })
    return labels


def fetch_boxes(study_filter: str = "MSB-OB") -> list[dict]:
    """
    MSB-OB インジケータのボックス（Order Block ゾーン）一覧を取得する。
    返り値: [{"high": 1.2400, "low": 1.2300}, ...]
    """
    data = run_tv(["pine", "boxes", "--study-filter", study_filter])
    if not data or not data.get("success"):
        return []

    boxes = []
    for study in data.get("studies", []):
        for box in study.get("boxes", []):
            if box.get("top") is not None and box.get("bottom") is not None:
                boxes.append({
                    "high": float(box["top"]),
                    "low":  float(box["bottom"]),
                })
    return boxes


# ============================================================
# シグナル解析
# ============================================================

def parse_direction(labels: list[dict]) -> Optional[str]:
    """
    最新ラベルのテキストから direction を判定する。
    "MSB ↑" → "buy" / "MSB ↓" → "sell"
    直近シグナルが見つからない場合は None。
    """
    msb_labels = [
        lbl for lbl in labels
        if "MSB" in lbl["text"] and ("↑" in lbl["text"] or "↓" in lbl["text"])
    ]
    if not msb_labels:
        return None

    # price の降順（最新バー＝最高値付近）で先頭を取る
    # Pine は時系列順にラベルを返すため末尾が最新
    latest = msb_labels[-1]
    if "↑" in latest["text"]:
        return "buy"
    if "↓" in latest["text"]:
        return "sell"
    return None


def build_signal_payload(
    symbol: str,
    direction: str,
    labels: list[dict],
    boxes: list[dict],
) -> dict:
    """crypto_auto_trading 手動シグナル API に送る payload を構築する。"""
    latest_price = labels[-1]["price"] if labels else None

    # OB ゾーンを direction に合わせてフィルタ
    # buy  → 価格より下にある高い OB（サポートゾーン）
    # sell → 価格より上にある低い OB（レジスタンスゾーン）
    ob_zones = []
    for box in boxes:
        ob_zones.append({"high": box["high"], "low": box["low"]})

    return {
        "symbol":    symbol,
        "direction": direction,
        "source":    "msb_ob_tv",
        "price":     latest_price,
        "ob_zones":  ob_zones,
        "raw_labels": [lbl["text"] for lbl in labels[-5:]],  # 直近5件
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================
# API 送信
# ============================================================

def post_signal(api_url: str, payload: dict, dry_run: bool = False) -> bool:
    """
    crypto_auto_trading の手動シグナル API に POST する。
    dry_run=True のときは送信せずログ出力のみ。
    """
    endpoint = f"{api_url.rstrip('/')}/api/signals/manual"

    if dry_run:
        log.info("[DRY RUN] POST %s", endpoint)
        log.info("[DRY RUN] payload=%s", json.dumps(payload, ensure_ascii=False, indent=2))
        return True

    try:
        resp = requests.post(endpoint, json=payload, timeout=10)
        if resp.status_code in (200, 201):
            log.info("シグナル送信成功: %s direction=%s", payload["symbol"], payload["direction"])
            return True
        else:
            log.warning(
                "API エラー: status=%d body=%s",
                resp.status_code, resp.text[:200]
            )
            return False
    except requests.RequestException as e:
        log.error("POST 失敗: %s", e)
        return False


# ============================================================
# メインロジック
# ============================================================

def run_once(symbol: str, api_url: str, dry_run: bool) -> bool:
    """1サイクル実行。シグナルを検知して POST する。成功時 True。"""
    log.info("MSB-OB データ取得中 (symbol=%s)...", symbol)

    labels = fetch_labels("MSB-OB")
    boxes  = fetch_boxes("MSB-OB")

    if not labels:
        log.info("MSB-OB ラベルなし — シグナルなし")
        return False

    log.info("ラベル %d 件、ボックス %d 件を取得", len(labels), len(boxes))

    direction = parse_direction(labels)
    if direction is None:
        log.info("直近の MSB シグナルなし")
        return False

    log.info("MSB シグナル検知: direction=%s", direction)

    payload = build_signal_payload(symbol, direction, labels, boxes)
    return post_signal(api_url, payload, dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MSB-OB ブリッジ — TradingView Pine → crypto_auto_trading"
    )
    parser.add_argument(
        "--symbol",
        default="SUIUSDT",
        help="取引シンボル（例: SUIUSDT）。crypto_auto_trading 側の識別子に合わせる",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8017",
        help="crypto_auto_trading API ベース URL (default: http://localhost:8017)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際には POST せず、payload をログに出力するのみ",
    )
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        metavar="SECONDS",
        help="ポーリング間隔（秒）。0 の場合は1回だけ実行（default: 0）",
    )
    parser.add_argument(
        "--study-filter",
        default="MSB-OB",
        help='Pine インジケータ名のフィルタ文字列 (default: "MSB-OB")',
    )
    args = parser.parse_args()

    if args.loop > 0:
        log.info(
            "ポーリングモード開始 (interval=%ds, symbol=%s, api=%s, dry_run=%s)",
            args.loop, args.symbol, args.api_url, args.dry_run,
        )
        while True:
            try:
                run_once(args.symbol, args.api_url, args.dry_run)
            except KeyboardInterrupt:
                log.info("中断されました")
                break
            except Exception as e:
                log.error("予期しないエラー: %s", e)
            time.sleep(args.loop)
        return 0
    else:
        success = run_once(args.symbol, args.api_url, args.dry_run)
        return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
