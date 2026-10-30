import numpy as np
import pandas as pd
from storage import StockChipStorage

HOLDING_LEVEL_MAP = {
    100: [8, 9, 10, 11, 12, 13, 14, 15],
    200: [9, 10, 11, 12, 13, 14, 15],
    400: [11, 12, 13, 14, 15],
    600: [12, 13, 14, 15],
    800: [13, 14, 15],
    1000: [15]
}

def test_recent_holding_values(pure_code: str, major1_thresh: int = 1000, major2_thresh: int = 400):
    storage = StockChipStorage(pure_code)
    holding_df = storage.load_holding_df()
    
    if holding_df.empty:
        print(f"[{pure_code}] 資料庫中查無大戶持股資料。")
        return

    holding_df['date'] = pd.to_datetime(holding_df['date']).dt.normalize()
    
    m1_levels = HOLDING_LEVEL_MAP.get(int(major1_thresh), [15])
    m2_levels = HOLDING_LEVEL_MAP.get(int(major2_thresh), [11, 12, 13, 14, 15])

    def get_weekly_sum(levels):
        sub = holding_df[holding_df['level'].isin(levels)]
        if sub.empty:
            return pd.Series(dtype=float)
        return sub.groupby('date')['percent'].sum().sort_index()

    m1_weekly = get_weekly_sum(m1_levels)
    m2_weekly = get_weekly_sum(m2_levels)

    pub_dates_m1 = pd.to_datetime(m1_weekly.index).values
    pct_vals_m1 = m1_weekly.values
    
    pub_dates_m2 = pd.to_datetime(m2_weekly.index).values
    pct_vals_m2 = m2_weekly.values

    mock_dates = pd.date_range(end=pd.Timestamp.today(), periods=60, freq='B')
    
    results = []
    for d in mock_dates:
        d_val = pd.to_datetime(d).normalize().to_numpy()
        
        valid_m1 = np.where(pub_dates_m1 <= d_val)[0]
        v1 = float(pct_vals_m1[valid_m1[-1]]) if len(valid_m1) > 0 else float('nan')
        
        valid_m2 = np.where(pub_dates_m2 <= d_val)[0]
        v2 = float(pct_vals_m2[valid_m2[-1]]) if len(valid_m2) > 0 else float('nan')
        
        results.append({'Date': pd.to_datetime(d).strftime('%Y-%m-%d'), 'Major1_Pct': v1, 'Major2_Pct': v2})

    res_df = pd.DataFrame(results)
    print("=== 近 60 個交易日對應結果（最後 15 筆） ===")
    print(res_df.tail(15).to_string(index=False))

if __name__ == '__main__':
    test_recent_holding_values('2330', major1_thresh=1000, major2_thresh=400)
