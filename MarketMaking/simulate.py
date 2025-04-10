import pandas as pd
from MarketMaking.MarketMaking import Trader
from datamodel import OrderDepth, TradingState, Order
from collections import defaultdict
import sys
import matplotlib.pyplot as plt


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


def match_order(order: Order, order_depth: OrderDepth) -> tuple[int, int]:
    if order.quantity > 0:
        available_prices = sorted([p for p in order_depth.sell_orders.keys() if p <= order.price])
        executed_qty = 0
        total_spent = 0
        remaining_qty = order.quantity

        for price in available_prices:
            available_at_price = -order_depth.sell_orders[price]
            executed_at_price = min(remaining_qty, available_at_price)
            if executed_at_price <= 0:
                continue
            executed_qty += executed_at_price
            total_spent += executed_at_price * price
            remaining_qty -= executed_at_price
            if remaining_qty <= 0:
                break

        return executed_qty, (total_spent / executed_qty if executed_qty > 0 else 0)

    else:
        available_prices = sorted([p for p in order_depth.buy_orders.keys() if p >= order.price], reverse=True)
        executed_qty = 0
        total_received = 0
        remaining_qty = -order.quantity

        for price in available_prices:
            available_at_price = order_depth.buy_orders[price]
            executed_at_price = min(remaining_qty, available_at_price)
            if executed_at_price <= 0:
                continue
            executed_qty += executed_at_price
            total_received += executed_at_price * price
            remaining_qty -= executed_at_price
            if remaining_qty <= 0:
                break

        return -executed_qty, (total_received / executed_qty if executed_qty > 0 else 0)


# Load data
day = sys.argv[1] if len(sys.argv) > 1 else "0"
price_file = f"PriceData/prices_round_1_day_{day}.csv"
print(f"Simulating with price data from: {price_file}")

prices_df = pd.read_csv(price_file, sep=";")
timestamps = sorted(prices_df['timestamp'].unique())
trader = Trader()

position = defaultdict(int)
order_log = []
equity_curve_log = []
last_prices = {}

for t in timestamps:
    snapshot = prices_df[prices_df['timestamp'] == t]
    order_depths = {
        row['product']: build_order_depth(row) for _, row in snapshot.iterrows()
    }

    for _, row in snapshot.iterrows():
        product = row['product']
        if order_depths[product].buy_orders and order_depths[product].sell_orders:
            best_bid = max(order_depths[product].buy_orders.keys())
            best_ask = min(order_depths[product].sell_orders.keys())
            last_prices[product] = (best_bid + best_ask) / 2
            print(f"Time {t} - {product}: bid={best_bid}, ask={best_ask}, mid={last_prices[product]}")

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
            executed_qty, executed_price = match_order(order, order_depths[product])
            if executed_qty != 0:
                old_pos = position[product]
                position[product] += executed_qty
                trader.update_cost_basis_and_pnl(product, executed_price, executed_qty, position[product])
                order_log.append([t, product, executed_price, executed_qty])

    unrealized = 0
    for product, pos in position.items():
        if pos != 0 and product in last_prices:
            unrealized += pos * last_prices[product]

    realized = sum(trader.realized_pnl.values())
    total_equity = realized + unrealized

    equity_curve_log.append({
        "timestamp": t,
        "realized_pnl": realized,
        "inventory_value": unrealized,
        "total_pnl": total_equity,
        "positions": dict(position),
        "cost_basis": dict(trader.cost_basis)
    })

# Save to file
output_file = f"simulated_orders_day_{day}.csv"
pd.DataFrame(order_log, columns=["timestamp", "product", "price", "quantity"]).to_csv(output_file, index=False)
pd.DataFrame(equity_curve_log).to_csv(f"equity_curve_day_{day}.csv", index=False)
print(f"\nSimulation complete. Results saved to {output_file}.")
print(f"Equity curve saved to equity_curve_day_{day}.csv")

# Final summary report
final = equity_curve_log[-1]
print("\nFinal Report")
print("-" * 40)
print(f"Final Realized PnL: {final['realized_pnl']:.2f}")
print(f"Final Inventory Value: {final['inventory_value']:.2f}")
print(f"Final Total PnL: {final['total_pnl']:.2f}")
print("Final Positions:")
for product, qty in final['positions'].items():
    print(f"  {product}: {qty} units")
print("Final Cost Basis:")
for product, basis in final['cost_basis'].items():
    print(f"  {product}: {basis:.2f}")

# Plot equity curve
timestamps = [row['timestamp'] for row in equity_curve_log]
pnl_values = [row['total_pnl'] for row in equity_curve_log]

plt.figure(figsize=(12, 5))
plt.plot(timestamps, pnl_values, label='Total PnL', color='purple')
plt.title("Equity Curve")
plt.xlabel("Timestamp")
plt.ylabel("PnL")
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.show()
