import pandas as pd
from MarketMakerV1 import Trader
from datamodel import OrderDepth, TradingState
from collections import defaultdict

def build_order_depth(row):
    depth = OrderDepth()
    for i in range(1, 4):
        bid_price = row.get(f'bid_price_{i}')
        bid_volume = row.get(f'bid_volume_{i}')
        ask_price = row.get(f'ask_price_{i}')
        ask_volume = row.get(f'ask_volume_{i}')
        if pd.notna(bid_price) and pd.notna(bid_volume):
            depth.buy_orders[int(bid_price)] = int(bid_volume)
        if pd.notna(ask_price) and pd.notna(ask_volume):
            depth.sell_orders[int(ask_price)] = -int(ask_volume)
    return depth

prices_df = pd.read_csv("prices_round_1_day_0.csv", sep=";")
timestamps = sorted(prices_df['timestamp'].unique())
trader = Trader()

position = defaultdict(int)
order_log = []

for t in timestamps:
    snapshot = prices_df[prices_df['timestamp'] == t]
    order_depths = {
        row['product']: build_order_depth(row) for _, row in snapshot.iterrows()
    }

    state = TradingState(
        traderData="",
        timestamp=t,
        listings={},
        order_depths=order_depths,
        own_trades={},
        market_trades={},
        position=dict(position),
        observations=None
    )

    orders, conversions, _ = trader.run(state)

    for product, order_list in orders.items():
        for order in order_list:
            position[product] += order.quantity
            order_log.append([t, product, order.price, order.quantity])

# Save orders to CSV
pd.DataFrame(order_log, columns=["timestamp", "product", "price", "quantity"]).to_csv("simulated_orders.csv", index=False)
print("Simulation complete. Results saved to simulated_orders.csv.")
