# NEXTACTION — tv_autotrading

## 完了済み
- [x] multi-pane streaming (`tv stream all`)
- [x] pane/layout 管理 (pane_list, pane_set_layout, pane_focus, pane_set_symbol)
- [x] tab 管理 (tab_list, tab_new, tab_close, tab_switch)
- [x] README / SECURITY.md / RESEARCH.md / SETUP_GUIDE.md 整備
- [x] Pane & Tab の e2e テスト追加
- [x] `scripts/fx_monitor.py` — FX マルチシンボル監視（Discord アラート付き）
- [x] `pine/msb_ob_signal.pine` — MSB-OB Pine Script v6 インジケータ
- [x] `scripts/msb_ob_bridge.py` — MSB-OB → crypto_auto_trading シグナルブリッジ
- [x] Poko1919/tradingview-mcp fork 作成 + origin 切り替え + push 完了
- [x] 英語 UI 切り替え (jp.tradingview.com → www.tradingview.com)
- [x] `pine compile` ボタン検出修正 (title 属性対応、Save ダイアログ自動処理)
- [x] `data strategy` コンパクト出力 (64KB パイプ制限対策)
- [x] `TVPrototype.run()` E2E 動作確認 (PF/WR/totalTrades 正常取得)
- [x] `watchlist_remove` 実装 (core/tools/cli) + CLI テスト追加 (pane/tab/watchlist)

## 次の優先タスク

### 1. watchlist_remove e2e テスト
- `tests/e2e.test.js` に watchlist add → remove のフローテストを追加（TradingView 接続必須）

### 2. `--help` タイムアウト調査
- `tests/cli.test.js` の `--help shows command list` が 15秒タイムアウトで flaky
- `-h` は 12秒でパス。`tv --help` が初回起動時に遅延している可能性

## 保留
- `data_get_study_values` の study_filter 対応（nice-to-have）
- `replay_trade` のより詳細なテスト
