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
- [x] `--help` タイムアウト修正 (cold disk cache, 15s→30s) + watchlist_remove e2e テスト追加
- [x] `data_get_study_values` study_filter 対応 (core/tools/cli)
- [x] `replay_trade` 詳細テスト (sell + full buy/step/close + P&L)
- [x] watchlist add→remove フロー e2e (BITSTAMP:LTCUSD テストシンボル)

## 次の優先タスク

**検討中（2026-04-03）: MT5 EA への活用**

### 優先高（即着手可）
- [x] マクロフィルタ統合: `data_get_study_values` で VIX/DXY 取得 → JSON → MT5 `FileOpen()` → EA ロット係数反映
  - `scripts/macro_filter.py` — VIX/DXY 取得・ロット係数算出・macro_filter.json 書き出し
  - `mql5/MacroFilterReader.mqh` — MT5 EA 用 FileOpen() 読み込みヘッダー（GetMacroLotMultiplier()）
  - `tests/test_macro_filter.py` — pytest 21件全通過
  - 対象: instance_gold_live (XAUUSD) — VIX/DXY 感応度が高い
  - 次: ea_trading_system 側で `#include "MacroFilterReader.mqh"` を組み込む（ea_trading_system NEXTACTION.md を更新）

### 優先中（factory パイプライン安定後）
- [ ] Pine ゲート (factory_qa.py Phase 2.5): EA 候補 BT 前に TV でシグナル確認 → 無駄 BT 削減
  - ea_trading_system NEXTACTION.md:7 に `[ ]` タスクとして残存

### 優先低（設計が必要）
- [ ] リアルタイム Pine ライン → TP/SL ブリッジ: `data_get_pine_lines` → Windows Agent (port 8050) → EA の TP/SL 動的更新
- [ ] MTF フィルター: 上位 TF (D1/H4) の Bias ラベルと EA エントリー方向を一致させるフィルター
