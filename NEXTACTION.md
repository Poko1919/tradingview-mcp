# NEXTACTION — tv_autotrading

## 完了済み
- [x] multi-pane streaming (`tv stream all`)
- [x] pane/layout 管理 (pane_list, pane_set_layout, pane_focus, pane_set_symbol)
- [x] tab 管理 (tab_list, tab_new, tab_close, tab_switch)
- [x] README / SECURITY.md / RESEARCH.md / SETUP_GUIDE.md 整備
- [x] Pane & Tab の e2e テスト追加

## 次の優先タスク

### 1. watchlist_remove の実装
- `core/watchlist.js` に `remove({ symbol })` を追加（右クリックメニュー or Delete キー）
- `tools/watchlist.js` に `watchlist_remove` ツールを登録
- `cli/commands/watchlist.js` に `remove` サブコマンドを追加
- e2e テストを追加

### 2. CLI test カバレッジ
- `tests/cli.test.js` に pane/tab コマンドのテストを追加

## 保留
- `data_get_study_values` の study_filter 対応（nice-to-have）
- `replay_trade` のより詳細なテスト
