#!/usr/bin/env python3
"""
FX マルチシンボル監視 — TradingView MCP CLI 経由

TradingView Desktop の4ペインに FX/Gold 銘柄を配置し、
異常検知時に Discord Webhook で通知する。

使い方:
    python scripts/fx_monitor.py [--interval 60] [--symbols EURUSD,GBPUSD,XAUUSD,USDJPY]

環境変数:
    DISCORD_WEBHOOK_EA_ALERTS  — Discord Webhook URL（未設定時は通知なし）
    TV_CLI                     — tv コマンドのパス（デフォルト: tv）
"""

import argparse
import json
import os
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone

import httpx
from loguru import logger

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

DEFAULT_SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]
DEFAULT_INTERVAL = 60          # 秒
ATR_SPIKE_MULT = 1.5           # ATR スパイク判定倍率
CHANGE_PCT_THRESHOLD = 0.5     # 大幅変動判定 (%)
ALERT_COOLDOWN = 600           # 同一シンボルのアラート抑制時間 (秒) = 10分
CLOSE_HISTORY_LEN = 6          # ATR 近似用の close 保持件数 (5差分 + 1)

# Discord Embed カラー
COLOR_GREEN = 0x2ECC71
COLOR_RED = 0xE74C3C
COLOR_BLUE = 0x3498DB

# ---------------------------------------------------------------------------
# TV CLI ヘルパー
# ---------------------------------------------------------------------------

def tv_cli() -> str:
    """tv コマンドのパスを返す。TV_CLI 環境変数で上書き可能。"""
    return os.getenv("TV_CLI", "tv")


def run_tv(args: list[str]) -> dict | None:
    """tv コマンドを実行して JSON を返す。失敗時は None。"""
    cmd = [tv_cli()] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning(f"tv {' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()[:200]}")
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        logger.warning(f"tv {' '.join(args)} timed out")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"tv {' '.join(args)} returned invalid JSON: {e}")
        return None
    except FileNotFoundError:
        logger.error(f"tv command not found: {tv_cli()!r}. Set TV_CLI env var or install with: npm install -g .")
        return None


# ---------------------------------------------------------------------------
# Discord 通知
# ---------------------------------------------------------------------------

class DiscordNotifier:
    """Discord Webhook 通知（同期・例外を投げない設計）"""

    def __init__(self) -> None:
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_EA_ALERTS") or ""

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def send_embed(self, embed: dict) -> bool:
        if not self.webhook_url:
            logger.debug("Discord webhook not configured (DISCORD_WEBHOOK_EA_ALERTS unset)")
            return False
        try:
            resp = httpx.post(
                self.webhook_url,
                json={"embeds": [embed]},
                timeout=10.0,
            )
            if resp.status_code in (200, 204):
                logger.info(f"Discord notified: {embed.get('title', '')}")
                return True
            logger.warning(f"Discord webhook returned {resp.status_code}: {resp.text[:200]}")
            return False
        except Exception as e:
            logger.warning(f"Discord send failed: {type(e).__name__}: {e}")
            return False

    def send_alert(
        self,
        symbol: str,
        price: float,
        change_pct: float,
        reason: str,
    ) -> bool:
        """FX 異常アラートを Discord に送信する。"""
        color = COLOR_GREEN if change_pct >= 0 else COLOR_RED
        direction = "上昇" if change_pct >= 0 else "下落"
        sign = "+" if change_pct >= 0 else ""

        embed = {
            "title": f"FX アラート: {symbol}",
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": [
                {"name": "シンボル", "value": symbol, "inline": True},
                {"name": "現在値", "value": f"{price:.5f}", "inline": True},
                {"name": "変動率", "value": f"{sign}{change_pct:.3f}% ({direction})", "inline": True},
                {"name": "検知理由", "value": reason, "inline": False},
            ],
        }
        return self.send_embed(embed)

    def send_startup(self, symbols: list[str], interval: int) -> None:
        """監視開始通知。"""
        embed = {
            "title": "FX Monitor 開始",
            "color": COLOR_BLUE,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "description": (
                f"監視シンボル: {', '.join(symbols)}\n"
                f"ポーリング間隔: {interval}秒\n"
                f"大幅変動閾値: ±{CHANGE_PCT_THRESHOLD}%\n"
                f"ATR スパイク倍率: {ATR_SPIKE_MULT}x"
            ),
        }
        self.send_embed(embed)


# ---------------------------------------------------------------------------
# 異常検知ロジック
# ---------------------------------------------------------------------------

class SymbolState:
    """シンボルごとの状態（直近 close 履歴・アラート抑制タイマー）"""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.closes: deque[float] = deque(maxlen=CLOSE_HISTORY_LEN)
        self.last_alert_ts: float = 0.0

    def record(self, close: float) -> None:
        self.closes.append(close)

    def approx_atr(self) -> float | None:
        """直近 close 差分の平均で ATR を近似する。データ不足時は None。"""
        if len(self.closes) < 2:
            return None
        diffs = [abs(self.closes[i] - self.closes[i - 1]) for i in range(1, len(self.closes))]
        return sum(diffs) / len(diffs)

    def cooldown_ok(self) -> bool:
        """アラート抑制期間を過ぎているか。"""
        return (time.time() - self.last_alert_ts) >= ALERT_COOLDOWN

    def mark_alerted(self) -> None:
        self.last_alert_ts = time.time()


def detect_anomaly(state: SymbolState, close: float, change_pct: float) -> str | None:
    """
    異常を検知して理由文字列を返す。正常時は None。

    検知条件:
      1. change_pct の絶対値が CHANGE_PCT_THRESHOLD 超
      2. 前回 close との差が approx_atr * ATR_SPIKE_MULT 超
    """
    reasons = []

    # 条件 1: 大幅変動
    if abs(change_pct) > CHANGE_PCT_THRESHOLD:
        sign = "+" if change_pct > 0 else ""
        reasons.append(f"大幅変動 ({sign}{change_pct:.3f}% > ±{CHANGE_PCT_THRESHOLD}%)")

    # 条件 2: ATR スパイク（直近2本以上ある場合のみ）
    if len(state.closes) >= 1:
        prev_close = state.closes[-1]
        move = abs(close - prev_close)
        atr = state.approx_atr()
        if atr is not None and atr > 0 and move > atr * ATR_SPIKE_MULT:
            reasons.append(
                f"ATR スパイク (move={move:.5f} > ATR×{ATR_SPIKE_MULT}={atr * ATR_SPIKE_MULT:.5f})"
            )

    return " / ".join(reasons) if reasons else None


# ---------------------------------------------------------------------------
# セットアップ（4ペイン配置）
# ---------------------------------------------------------------------------

def setup_layout(symbols: list[str]) -> None:
    """2x2 グリッドを設定し、各ペインにシンボルをセットする。"""
    logger.info("4ペインレイアウトを設定中...")
    result = run_tv(["pane", "layout", "2x2"])
    if result and result.get("success"):
        logger.info("レイアウト設定成功")
    else:
        logger.warning("レイアウト設定に失敗（TradingView が起動していない可能性があります）")

    for idx, symbol in enumerate(symbols[:4]):
        logger.info(f"ペイン {idx} に {symbol} をセット中...")
        result = run_tv(["pane", "symbol", str(idx), symbol])
        if result and result.get("success"):
            logger.info(f"  ペイン {idx} → {symbol} OK")
        else:
            logger.warning(f"  ペイン {idx} → {symbol} 失敗")
        time.sleep(0.5)  # UI 操作の安定化


# ---------------------------------------------------------------------------
# メインループ
# ---------------------------------------------------------------------------

def poll_once(
    symbols: list[str],
    states: dict[str, SymbolState],
    notifier: DiscordNotifier,
) -> None:
    """全シンボルを1回ポーリングして異常検知・通知する。"""
    for symbol in symbols:
        result = run_tv(["quote", symbol])
        if not result or not result.get("success"):
            logger.warning(f"{symbol}: quote 取得失敗")
            continue

        close = result.get("close") or result.get("last_price")
        change_pct = result.get("change_percent") or result.get("change_pct") or 0.0

        if close is None:
            logger.warning(f"{symbol}: close が取得できません (raw={result})")
            continue

        logger.debug(f"{symbol}: close={close:.5f} change={change_pct:+.3f}%")

        state = states[symbol]
        reason = detect_anomaly(state, close, change_pct)

        # アラート送信（クールダウン制御）
        if reason and state.cooldown_ok():
            logger.info(f"ALERT {symbol}: {reason}")
            notifier.send_alert(symbol, close, change_pct, reason)
            state.mark_alerted()
        elif reason:
            remaining = ALERT_COOLDOWN - (time.time() - state.last_alert_ts)
            logger.info(f"ALERT {symbol} 抑制中（あと {remaining:.0f}秒）: {reason}")

        # close を記録（アラート判定後）
        state.record(close)


def run_monitor(symbols: list[str], interval: int) -> None:
    """メイン監視ループ。Ctrl+C で停止。"""
    notifier = DiscordNotifier()
    if not notifier.enabled:
        logger.warning("DISCORD_WEBHOOK_EA_ALERTS が未設定です。通知はスキップされます。")

    # ペイン配置
    setup_layout(symbols)

    # シンボル状態を初期化
    states: dict[str, SymbolState] = {s: SymbolState(s) for s in symbols}

    # 開始通知
    notifier.send_startup(symbols, interval)
    logger.info(f"監視開始: {symbols} / 間隔={interval}秒")

    try:
        while True:
            cycle_start = time.time()
            poll_once(symbols, states, notifier)
            elapsed = time.time() - cycle_start
            sleep_sec = max(0.0, interval - elapsed)
            logger.debug(f"次回ポーリングまで {sleep_sec:.1f}秒")
            time.sleep(sleep_sec)
    except KeyboardInterrupt:
        logger.info("監視を停止しました (Ctrl+C)")
        sys.exit(0)


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FX マルチシンボル監視 — TradingView MCP CLI 経由",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"ポーリング間隔（秒）。デフォルト: {DEFAULT_INTERVAL}",
    )
    parser.add_argument(
        "--symbols", "-s",
        type=str,
        default=",".join(DEFAULT_SYMBOLS),
        help=f"カンマ区切りのシンボルリスト。デフォルト: {','.join(DEFAULT_SYMBOLS)}",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="ログレベル。デフォルト: INFO",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # ログ設定
    logger.remove()
    logger.add(
        sys.stderr,
        level=args.log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    )

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        logger.error("シンボルが指定されていません")
        sys.exit(1)
    if len(symbols) > 4:
        logger.warning(f"シンボルは最大4つです。先頭4つのみ使用します: {symbols[:4]}")
        symbols = symbols[:4]

    run_monitor(symbols, args.interval)


if __name__ == "__main__":
    main()
