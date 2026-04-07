import yfinance as yf
import pandas as pd

# GC=F adalah Gold Futures di CME
ticker = yf.Ticker("GC=F")

# Fetch data hourly - maksimal 60 hari per request
# Kita loop untuk dapat data lebih panjang
from datetime import datetime, timedelta

all_data = []
end = datetime.utcnow()

# Ambil 6 bulan ke belakang (loop per 60 hari)
for i in range(3):  # 3 x 60 hari = ~6 bulan
    start = end - timedelta(days=59)
    df_batch = yf.download("GC=F", start=start.strftime("%Y-%m-%d"), 
                            end=end.strftime("%Y-%m-%d"), interval="1h", progress=False)
    all_data.append(df_batch)
    end = start

df = pd.concat(all_data)
df = df[~df.index.duplicated()]  # hapus duplikat
df = df.sort_index()

print(df.head())
print(f"\nTotal: {len(df)} candles")
print(f"Dari: {df.index[0]} sampai: {df.index[-1]}")

# Simpan ke CSV
df.to_csv("xauusd_hourly.csv")
print("Data tersimpan ke xauusd_hourly.csv")