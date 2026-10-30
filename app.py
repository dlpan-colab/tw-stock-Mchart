import streamlit as st
import pandas as pd
from storage import StockChipStorage
from data_fetcher import sync_chip_data

st.title("API 與資料庫同步測試")

code = "6234"
st.write(f"=== 開始測試股票代號: {code} 之同步機制 ===")

storage = StockChipStorage(code)

try:
    st.write("正在呼叫 sync_chip_data()...")
    sync_chip_data(code, storage)
    st.write("sync_chip_data 執行結束。")
    
    inst_df = storage.load_institutional_df()
    margin_df = storage.load_margin_df()
    holding_df = storage.load_holding_df()
    
    st.write(f"【三大法人】讀取筆수: {len(inst_df)}")
    if not inst_df.empty:
        st.dataframe(inst_df.tail(2))
        
    st.write(f"【資券餘額】讀取筆數: {len(margin_df)}")
    if not margin_df.empty:
        st.dataframe(margin_df.tail(2))
        
    st.write(f"【集保大戶】讀取筆數: {len(holding_df)}")
    if not holding_df.empty:
        st.dataframe(holding_df.tail(2))
        
except Exception as e:
    st.error(f"測試過程發生例外錯誤: {e}")
