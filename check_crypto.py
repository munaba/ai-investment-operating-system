import sqlite3

conn = sqlite3.connect("data/investment_platform.db")

for label, sql in [
    ("ACCOUNT", "SELECT account_id, mode, currency, asset_class, cash, equity FROM accounts WHERE account_id = ?"),
    ("ORDERS", "SELECT order_id, account_id, symbol, action, quantity, status FROM orders WHERE account_id = ?"),
    ("TRADES", "SELECT trade_id, order_id, account_id, symbol, action, quantity, fill_price, fee, tax FROM trades WHERE account_id = ?"),
    ("POSITIONS", "SELECT symbol, quantity, average_price, buy_fee_accumulated FROM positions WHERE account_id = ?"),
]:
    print(f"\n{label}")
    print(conn.execute(sql, ("crypto-usd",)).fetchall())

conn.close()