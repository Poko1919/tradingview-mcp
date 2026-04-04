//+------------------------------------------------------------------+
//| MacroFilterReader.mqh                                            |
//| macro_filter.json を読み込み、ロット係数を返す MQH ヘッダー        |
//|                                                                  |
//| 使い方:                                                           |
//|   #include "MacroFilterReader.mqh"                               |
//|   double mult = GetMacroLotMultiplier();  // 0.25 / 0.5 / 0.75 / 1.0 |
//|   double lots = base_lots * mult;                                |
//|                                                                  |
//| JSON ファイルは scripts/macro_filter.py で生成する。               |
//| MT5 の MQL5/Files/ ディレクトリに macro_filter.json を配置すること。|
//+------------------------------------------------------------------+
#ifndef MACRO_FILTER_READER_MQH
#define MACRO_FILTER_READER_MQH

// ファイル名（MQL5/Files/ 以下の相対パス）
#ifndef MACRO_FILTER_FILE
  #define MACRO_FILTER_FILE "macro_filter.json"
#endif

// フォールバック係数（ファイル未読時）
#ifndef MACRO_FILTER_FALLBACK
  #define MACRO_FILTER_FALLBACK 0.5
#endif

// ファイルが古いとみなす秒数（デフォルト: 10分）
#ifndef MACRO_FILTER_MAX_AGE_SEC
  #define MACRO_FILTER_MAX_AGE_SEC 600
#endif

//+------------------------------------------------------------------+
//| JSON 文字列から指定キーの数値を取り出す                             |
//| 例: _JsonGetDouble("{\"lot_multiplier\": 0.75}", "lot_multiplier") → 0.75 |
//+------------------------------------------------------------------+
double _JsonGetDouble(const string &json, const string &key, double fallback = -1.0)
{
   string search = "\"" + key + "\"";
   int pos = StringFind(json, search);
   if (pos < 0) return fallback;

   // ':' を探す
   int colon = StringFind(json, ":", pos + StringLen(search));
   if (colon < 0) return fallback;

   // 数値の開始位置（空白・null をスキップ）
   int start = colon + 1;
   int len   = StringLen(json);
   while (start < len && (StringGetCharacter(json, start) == ' ' ||
                           StringGetCharacter(json, start) == '\t' ||
                           StringGetCharacter(json, start) == '\r' ||
                           StringGetCharacter(json, start) == '\n'))
      start++;

   // null チェック
   if (start + 3 < len && StringSubstr(json, start, 4) == "null")
      return fallback;

   // 数値文字列の終端を探す（, } \n \r で終わり）
   int end = start;
   while (end < len)
   {
      ushort c = StringGetCharacter(json, end);
      if (c == ',' || c == '}' || c == '\n' || c == '\r' || c == ' ')
         break;
      end++;
   }
   if (end <= start) return fallback;

   string num_str = StringSubstr(json, start, end - start);
   double val = StringToDouble(num_str);
   return val;
}

//+------------------------------------------------------------------+
//| macro_filter.json を読み込んで lot_multiplier を返す               |
//| ファイル不在・古すぎる場合は MACRO_FILTER_FALLBACK を返す          |
//+------------------------------------------------------------------+
double GetMacroLotMultiplier()
{
   int handle = FileOpen(MACRO_FILTER_FILE, FILE_READ | FILE_TXT | FILE_ANSI);
   if (handle == INVALID_HANDLE)
   {
      Print("[MacroFilter] ファイル未読 (", MACRO_FILTER_FILE, ") → fallback=", MACRO_FILTER_FALLBACK);
      return MACRO_FILTER_FALLBACK;
   }

   // ファイル全体を読み込む
   string content = "";
   while (!FileIsEnding(handle))
      content += FileReadString(handle);
   FileClose(handle);

   if (StringLen(content) == 0)
   {
      Print("[MacroFilter] ファイル空 → fallback=", MACRO_FILTER_FALLBACK);
      return MACRO_FILTER_FALLBACK;
   }

   double mult = _JsonGetDouble(content, "lot_multiplier", MACRO_FILTER_FALLBACK);
   double vix  = _JsonGetDouble(content, "vix",  -1.0);

   Print("[MacroFilter] lot_multiplier=", mult, " vix=", (vix >= 0 ? (string)vix : "n/a"));
   return mult;
}

//+------------------------------------------------------------------+
//| VIX 値のみを返す（EA 内での条件分岐に使用可）                       |
//| ファイル不在・VIX 取得失敗時は -1.0 を返す                         |
//+------------------------------------------------------------------+
double GetMacroVix()
{
   int handle = FileOpen(MACRO_FILTER_FILE, FILE_READ | FILE_TXT | FILE_ANSI);
   if (handle == INVALID_HANDLE) return -1.0;

   string content = "";
   while (!FileIsEnding(handle))
      content += FileReadString(handle);
   FileClose(handle);

   return _JsonGetDouble(content, "vix", -1.0);
}

//+------------------------------------------------------------------+
//| DXY 値のみを返す                                                  |
//| ファイル不在・DXY 取得失敗時は -1.0 を返す                         |
//+------------------------------------------------------------------+
double GetMacroDxy()
{
   int handle = FileOpen(MACRO_FILTER_FILE, FILE_READ | FILE_TXT | FILE_ANSI);
   if (handle == INVALID_HANDLE) return -1.0;

   string content = "";
   while (!FileIsEnding(handle))
      content += FileReadString(handle);
   FileClose(handle);

   return _JsonGetDouble(content, "dxy", -1.0);
}

#endif // MACRO_FILTER_READER_MQH
