"""
strg_broker_mixin.py - 券商分點統計/日況與大盤八大官股 SQLite 讀寫 Mixin 模組
(自 storage.py 依邏輯職責拆分，維持既有分點統計、關注日序列綁定與八大官股明細儲存讀取機制)
版本: 202611242144
"""

import sqlite3
import pandas as pd

from strg_cloud_names import sync_db_push

MODULE_NAME = "strg_broker_mixin"
MODULE_VERSION = "202611242144"


class BrokerStorageMixin:
    # =====================================================================
    # 大盤/櫃買八大官股個股逐日分欄明細儲存與讀取 API（單位：萬元）
    # =====================================================================
    def save_gov_index_stock_daily(self, trade_date: str, stock_rows: list, sync_cloud: bool = False):
        """
        【修訂說明 2026-11-24】【修改目的與防呆防錯原因】：
        1. 修改目的：儲存單一交易日（trade_date）加權指數或櫃買指數八大官股買超前30與賣超前30個股之 8 家官股行庫各自買賣超與合計（單位：萬元）。
        2. 防呆防錯原因：每筆 dict 皆轉換為數值並以 (trade_date, stock_name) 為主鍵寫入 gov_index_stock_daily，遇缺表自動呼叫 _init_db() 修復。
        """
        d_str = str(trade_date or "").strip()[:10]
        if not d_str or not stock_rows:
            return
        records = []
        for item in stock_rows:
            if not isinstance(item, dict):
                continue
            s_name = str(item.get("stock_name", "") or "").strip()
            if not s_name:
                continue
            b_vals = [float(item.get(k, 0.0) or 0.0) for k in ("b_heku", "b_land", "b_bot", "b_tbb", "b_ccb", "b_first", "b_mega", "b_hncb")]
            t_wan = float(item.get("total_wan", sum(b_vals)) or 0.0)
            s_side = str(item.get("source_side", "buy") or "buy").lower()
            records.append((d_str, s_name, s_side, *b_vals, t_wan))
        if not records:
            return

        sql_ins = '''
            INSERT OR REPLACE INTO gov_index_stock_daily
            (trade_date, stock_name, source_side, b_heku, b_land, b_bot, b_tbb, b_ccb, b_first, b_mega, b_hncb, total_wan)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(sql_ins, records)
                conn.commit()
        except sqlite3.OperationalError:
            self._init_db()
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(sql_ins, records)
                conn.commit()
        if sync_cloud:
            sync_db_push(self.pure_code)

    def load_gov_index_stock_daily_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        【修訂說明 2026-11-24】【修改目的與防呆防錯原因】：
        讀取指定起訖日期區間內（[start_date, end_date]）之八大官股個股逐日 8 行庫買賣超明細（單位：萬元）。
        """
        s_d = str(start_date or "").strip()[:10]
        e_d = str(end_date or "").strip()[:10]
        if not s_d or not e_d:
            return pd.DataFrame()
        try:
            with sqlite3.connect(self.db_path) as conn:
                df = pd.read_sql_query('''
                    SELECT trade_date, stock_name, source_side,
                           b_heku, b_land, b_bot, b_tbb, b_ccb, b_first, b_mega, b_hncb, total_wan
                    FROM gov_index_stock_daily
                    WHERE trade_date >= ? AND trade_date <= ?
                    ORDER BY trade_date ASC, stock_name ASC
                ''', conn, params=(s_d, e_d))
            return df
        except sqlite3.OperationalError:
            self._init_db()
            return pd.DataFrame()

    # =====================================================================
    # 雲端分點資料增量累積與讀取 API
    # =====================================================================
    def save_broker_daily_trades(self, broker_name: str, df_trades: pd.DataFrame, sync_cloud: bool = True):
        """增量寫入單一券商分點逐日買賣超張數明細"""
        b_name = str(broker_name or "").strip()
        if not b_name or df_trades is None or df_trades.empty:
            return
        records = []
        for _, r in df_trades.iterrows():
            d_str = str(r.get("日期", "")).strip()[:10]
            if not d_str:
                continue
            b_val = int(r.get("買進(張)", 0) or 0)
            s_val = int(r.get("賣出(張)", 0) or 0)
            n_val = int(r.get("買賣超(張)", b_val - s_val) or 0)
            records.append((b_name, d_str, b_val, s_val, n_val))
        if not records:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany('''
                    INSERT OR REPLACE INTO broker_daily_trades
                    (broker_name, trade_date, buy_sheets, sell_sheets, net_sheets)
                    VALUES (?, ?, ?, ?, ?)
                ''', records)
                conn.commit()
        except sqlite3.OperationalError:
            self._init_db()
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany('''
                    INSERT OR REPLACE INTO broker_daily_trades
                    (broker_name, trade_date, buy_sheets, sell_sheets, net_sheets)
                    VALUES (?, ?, ?, ?, ?)
                ''', records)
                conn.commit()
        if sync_cloud:
            sync_db_push(self.pure_code)

    def load_broker_daily_series(self, broker_name: str, start_date: str, end_date: str) -> pd.DataFrame:
        """從本地/雲端資料庫讀取指定分點於起訖日期區間內之逐日買賣超序列"""
        b_name = str(broker_name or "").strip()
        if not b_name:
            return pd.DataFrame(columns=["日期", "買進(張)", "賣出(張)", "買賣超(張)"])
        try:
            with sqlite3.connect(self.db_path) as conn:
                df = pd.read_sql_query('''
                    SELECT trade_date AS 日期, buy_sheets AS "買進(張)", sell_sheets AS "賣出(張)", net_sheets AS "買賣超(張)"
                    FROM broker_daily_trades
                    WHERE broker_name = ? AND trade_date >= ? AND trade_date <= ?
                    ORDER BY trade_date ASC
                ''', conn, params=(b_name, start_date, end_date))
            return df
        except Exception:
            self._init_db()
            return pd.DataFrame(columns=["日期", "買進(張)", "賣出(張)", "買賣超(張)"])

    def save_broker_focus_daily_series(
        self,
        focus_date: str,
        window_days: int,
        side: str,
        rank_no: int,
        broker_name: str,
        total_net: int,
        df_trades: pd.DataFrame,
        sync_cloud: bool = True
    ):
        """
        【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
        修改目的：儲存指定關注交易日（focus_date）在特定統計視窗（window_days: 10/20/60）與買賣超方向（side: 'buy'/'sell'）
        下第 rank_no 名分點之完整逐日買賣超序列至 broker_focus_daily_series。
        防呆防錯原因：寫入前先刪除同一 (focus_date, window_days, side, rank_no) 舊列並重試防呆缺表，確保資料潔淨且與其他關注交易日完全隔離。
        """
        f_date = str(focus_date or "").strip()[:10]
        b_name = str(broker_name or "").strip()
        s_side = str(side or "").strip().lower()
        w_days = int(window_days or 20)
        r_no = int(rank_no or 1)
        t_net = int(total_net or 0)
        if not f_date or not b_name or s_side not in ("buy", "sell") or df_trades is None or df_trades.empty:
            return

        records = []
        for _, r in df_trades.iterrows():
            d_str = str(r.get("日期", "")).strip()[:10]
            if not d_str:
                continue
            b_val = int(r.get("買進(張)", 0) or 0)
            s_val = int(r.get("賣出(張)", 0) or 0)
            n_val = int(r.get("買賣超(張)", b_val - s_val) or 0)
            records.append((f_date, w_days, s_side, r_no, b_name, t_net, d_str, b_val, s_val, n_val))
        if not records:
            return

        def _exec_write():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM broker_focus_daily_series WHERE focus_date = ? AND window_days = ? AND side = ? AND rank_no = ?",
                    (f_date, w_days, s_side, r_no)
                )
                conn.executemany('''
                    INSERT OR REPLACE INTO broker_focus_daily_series
                    (focus_date, window_days, side, rank_no, broker_name, total_net, trade_date, buy_sheets, sell_sheets, net_sheets)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', records)
                conn.commit()

        try:
            _exec_write()
        except sqlite3.OperationalError:
            self._init_db()
            _exec_write()

        if sync_cloud:
            sync_db_push(self.pure_code)

    def load_all_broker_focus_daily_series(self) -> dict:
        """
        【修訂說明 2026-11-22】【修改目的與防呆防錯原因】：
        修改目的：一次性讀取本地資料庫 broker_focus_daily_series 中所有已儲存之關注交易日專屬分點逐日買賣超序列，
        回傳結構：{focus_date: {"w10": {"top5_buy_series": [...], "top5_sell_series": [...]}, "w20": ..., "w60": ...}}。
        防呆防錯原因：僅查詢本地已存在之 SQLite（耗時 < 3ms，零額外網路請求）；若遇舊表缺失則自動初始化並安全回傳空字典。
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute('''
                    SELECT focus_date, window_days, side, rank_no, broker_name, total_net, trade_date, net_sheets
                    FROM broker_focus_daily_series
                    ORDER BY focus_date ASC, window_days ASC, side ASC, rank_no ASC, trade_date ASC
                ''').fetchall()
        except sqlite3.OperationalError:
            self._init_db()
            return {}
        if not rows:
            return {}

        grouped = {}
        for f_date, w_days, side, rank_no, b_name, t_net, tr_date, n_sh in rows:
            fd = str(f_date or "").strip()[:10]
            td = str(tr_date or "").strip()[:10]
            if not fd or not td:
                continue
            w_key = f"w{int(w_days)}"
            s_key = "top5_buy_series" if str(side).lower() == "buy" else "top5_sell_series"
            r_no = int(rank_no)
            fd_map = grouped.setdefault(fd, {})
            w_map = fd_map.setdefault(w_key, {"top5_buy_series": {}, "top5_sell_series": {}})
            rank_dict = w_map[s_key]
            if r_no not in rank_dict:
                rank_dict[r_no] = {
                    "name": str(b_name or ""),
                    "total_net": int(t_net or 0),
                    "dates": [],
                    "nets": []
                }
            rank_dict[r_no]["dates"].append(td)
            rank_dict[r_no]["nets"].append(int(n_sh or 0))

        out = {}
        for fd, fd_map in grouped.items():
            out[fd] = {}
            for w_key, w_map in fd_map.items():
                out[fd][w_key] = {
                    "top5_buy_series": [w_map["top5_buy_series"][r] for r in sorted(w_map["top5_buy_series"].keys())],
                    "top5_sell_series": [w_map["top5_sell_series"][r] for r in sorted(w_map["top5_sell_series"].keys())],
                }
        return out

    def save_broker_range_rank(self, range_date: str, bundle_dict: dict, sync_cloud: bool = True):
        """
        【修訂說明 2026-11-24】【修改目的與防呆防錯原因】：
        修改目的：儲存指定基準日之 1/10/20/60 日買賣超統計快照，上限放寬至前 50 名，
        支援大盤加權與櫃買指數八大官股前 50 名個股排行儲存，同時完全向下相容個股前 10/15 名。
        防呆防錯原因：以 (range_date, win_days, side, rank) 為主鍵覆寫，避免重疊或殘留舊名次。
        """
        r_date = str(range_date or "").strip()[:10]
        if not r_date or not isinstance(bundle_dict, dict):
            return
        records = []
        for win_days in (1, 10, 20, 60):
            w_obj = bundle_dict.get(f"w{win_days}")
            if not isinstance(w_obj, dict):
                continue
            r_label = str(w_obj.get("range_label", ""))
            for side in ("buy", "sell"):
                rows = w_obj.get(side, [])
                for idx, item in enumerate(rows[:50], start=1):
                    records.append((
                        r_date,
                        int(win_days),
                        side,
                        int(idx),
                        str(item.get("name", "")),
                        str(item.get("sys", "")),
                        int(round(float(item.get("buy", 0) or 0))),
                        int(round(float(item.get("sell", 0) or 0))),
                        int(round(float(item.get("net", 0) or 0))),
                        str(item.get("ratio", "-")),
                        r_label
                    ))
        if not records:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM broker_range_rank WHERE range_date = ?", (r_date,))
            conn.executemany('''
                INSERT OR REPLACE INTO broker_range_rank
                (range_date, win_days, side, rank, broker_name, broker_sys, buy_sheets, sell_sheets, net_sheets, ratio_str, range_label)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', records)
            conn.commit()
        if sync_cloud:
            sync_db_push(self.pure_code)

    def load_broker_range_rank(self, range_date: str) -> dict:
        """讀取指定基準日之分點區間統計快照，若無資料回傳 None"""
        r_date = str(range_date or "").strip()[:10]
        if not r_date:
            return None
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute('''
                    SELECT win_days, side, rank, broker_name, broker_sys, buy_sheets, sell_sheets, net_sheets, ratio_str, range_label
                    FROM broker_range_rank
                    WHERE range_date = ?
                    ORDER BY win_days ASC, side ASC, rank ASC
                ''', (r_date,)).fetchall()
        except sqlite3.OperationalError:
            self._init_db()
            return None
        if not rows:
            return None
        result = {}
        for win_days, side, rank, b_name, b_sys, b_sh, s_sh, n_sh, r_str, r_lbl in rows:
            w_key = f"w{int(win_days)}"
            if w_key not in result:
                result[w_key] = {"range_label": r_lbl or "", "buy": [], "sell": []}
            if r_lbl and not result[w_key]["range_label"]:
                result[w_key]["range_label"] = r_lbl
            result[w_key][side].append({
                "name": b_name,
                "sys": b_sys,
                "buy": int(b_sh or 0),
                "sell": int(s_sh or 0),
                "net": int(n_sh or 0),
                "ratio": r_str or "-"
            })
        return result

    def load_all_broker_range_ranks(self) -> dict:
        """
        【修訂說明 2026-11-21】【修改目的與防呆防錯原因】：
        修改目的：一次性讀取本地已下載 SQLite 資料庫（broker_range_rank）中所有已累積之歷史基準日分點統計快照，
        回傳 {range_date: bundle_dict}，供主圖十字線切換至前一日（如 11/19）時即時呈現，避免隔日基準日推進後看不到前一日紀錄。
        防呆防錯原因：僅查詢本地已存在之 data_{code}.db（耗時 < 3ms，零額外雲端或網站網路請求）；若遇舊表結構不符（OperationalError），自動呼叫 _init_db() 修復並安全回傳空字典。
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute('''
                    SELECT range_date, win_days, side, rank, broker_name, broker_sys, buy_sheets, sell_sheets, net_sheets, ratio_str, range_label
                    FROM broker_range_rank
                    ORDER BY range_date ASC, win_days ASC, side ASC, rank ASC
                ''').fetchall()
        except sqlite3.OperationalError:
            self._init_db()
            return {}
        if not rows:
            return {}
        by_date = {}
        for r_date, win_days, side, rank, b_name, b_sys, b_sh, s_sh, n_sh, r_str, r_lbl in rows:
            d_key = str(r_date or "").strip()[:10]
            if not d_key:
                continue
            if d_key not in by_date:
                by_date[d_key] = {}
            w_key = f"w{int(win_days)}"
            if w_key not in by_date[d_key]:
                by_date[d_key][w_key] = {"range_label": r_lbl or "", "buy": [], "sell": []}
            if r_lbl and not by_date[d_key][w_key]["range_label"]:
                by_date[d_key][w_key]["range_label"] = r_lbl
            by_date[d_key][w_key][side].append({
                "name": b_name,
                "sys": b_sys,
                "buy": int(b_sh or 0),
                "sell": int(s_sh or 0),
                "net": int(n_sh or 0),
                "ratio": r_str or "-"
            })
        return by_date
## EOF strg_broker_mixin.py
