"""
遠端資料同步與資料庫寫入測試腳本
"""
import pandas as pd
from storage import StockChipStorage
from data_fetcher import sync_chip_data

def run_test():
    code = "6234"
    print(f"=== 開始測試股票代號: {code} 之同步機制 ===")
    
    storage = StockChipStorage(code)
    
    try:
        print("正在呼叫 sync_chip_data()...")
        sync_chip_data(code, storage)
        print("sync_chip_data執行結束。")
        
        # 驗證本地資料庫讀取結果
        inst_df = storage.load_institutional_df()
        margin_df = storage.load_margin_df()
        holding_df = storage.load_holding_df()
        
        print(f"【三大法人】讀取筆數: {len(inst_df)}")
        if not inst_df.empty:
            print(inst_df.tail(2))
            
        print(f"【資券餘額】讀取筆數: {len(margin_df)}")
        if not margin_df.empty:
            print(margin_df.tail(2))
            
        print(f"【集保大戶】讀取筆數: {len(holding_df)}")
        if not holding_df.empty:
            print(holding_df.tail(2))
            
    except Exception as e:
        print(f"測試過程發生例外錯誤: {e}")

if __name__ == "__main__":
    run_test()
