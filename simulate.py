import pandas as pd
import numpy as np
from MarketMaking import Trader
from datamodel import OrderDepth, TradingState, Order
from collections import defaultdict
import sys
import matplotlib.pyplot as plt
import json
import os

def ensure_output_dirs():
    """Create output directories if they don't exist"""
    base_dir = "MarketMakingResults"
    subdirs = ["data", "plots", "analysis", "logs"]
    
    for subdir in [base_dir] + [f"{base_dir}/{d}" for d in subdirs]:
        if not os.path.exists(subdir):
            os.makedirs(subdir)
    return base_dir

def calculate_asset_metrics(trades_df, equity_df, product):
    """Calculate detailed metrics for a single asset"""
    product_trades = trades_df[trades_df['product'] == product]
    
    metrics = {
        'total_trades': len(product_trades),
        'total_volume': abs(product_trades['quantity']).sum(),
        'avg_trade_size': abs(product_trades['quantity']).mean(),
        'max_position': equity_df[product].max(),
        'min_position': equity_df[product].min(),
        'avg_position': equity_df[product].mean(),
        'position_stdev': equity_df[product].std(),
        'price_mean': product_trades['price'].mean(),
        'price_std': product_trades['price'].std(),
        'trade_intervals': np.diff(product_trades['timestamp']).mean(),
        'profitable_trades': len(product_trades[product_trades['quantity'] * product_trades['price'] > 0]),
        'unprofitable_trades': len(product_trades[product_trades['quantity'] * product_trades['price'] < 0])
    }
    
    # Convert numpy types to Python native types for JSON
    return {k: float(v) if isinstance(v, (np.float64, np.int64)) else v 
            for k, v in metrics.items()}

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

def run_simulation():
    # Create output directories
    base_dir = ensure_output_dirs()
    
    # Load data
    day = sys.argv[1] if len(sys.argv) > 1 else "0"
    price_file = f"PriceData/prices_round_1_day_{day}.csv"
    print(f"Simulating market making strategy with price data from: {price_file}")

    prices_df = pd.read_csv(price_file, sep=";")
    timestamps = sorted(prices_df['timestamp'].unique())
    trader = Trader()

    position = defaultdict(int)
    order_log = []
    equity_curve_log = []
    last_prices = {}
    spreads_log = defaultdict(list)
    market_depths_log = defaultdict(list)

    # Open log file
    log_file = f"{base_dir}/logs/simulation_day_{day}.log"
    with open(log_file, 'w') as f:
        f.write(f"Starting market making simulation for day {day}\n")

        for t in timestamps:
            snapshot = prices_df[prices_df['timestamp'] == t]
            order_depths = {
                row['product']: build_order_depth(row) for _, row in snapshot.iterrows()
            }

            # Track market metrics
            for _, row in snapshot.iterrows():
                product = row['product']
                if order_depths[product].buy_orders and order_depths[product].sell_orders:
                    best_bid = max(order_depths[product].buy_orders.keys())
                    best_ask = min(order_depths[product].sell_orders.keys())
                    last_prices[product] = (best_bid + best_ask) / 2
                    spreads_log[product].append(best_ask - best_bid)
                    market_depths_log[product].append({
                        'timestamp': t,
                        'bid_volume': sum(order_depths[product].buy_orders.values()),
                        'ask_volume': sum(-v for v in order_depths[product].sell_orders.values())
                    })

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
                        order_log.append([t, product, executed_price, executed_qty])

            unrealized = 0
            for product, pos in position.items():
                if pos != 0 and product in last_prices:
                    unrealized += pos * last_prices[product]

            total_equity = unrealized

            equity_curve_log.append({
                "timestamp": t,
                "realized_pnl": 0,
                "inventory_value": unrealized,
                "total_pnl": total_equity,
                "positions": dict(position),
                "cost_basis": {}
            })

            # Log status every 100 timestamps
            if int(t) % 100 == 0:
                status = f"\nTime {t}:\n"
                status += f"Total PnL: {total_equity:.2f}\n"
                status += f"Positions: {dict(position)}\n"
                status += "------------------------\n"
                print(status)
                f.write(status)

        # Save detailed results
        trades_df = pd.DataFrame(order_log, columns=["timestamp", "product", "price", "quantity"])
        equity_df = pd.DataFrame(equity_curve_log)
        
        # Expand the positions dictionary into separate columns
        positions_df = pd.json_normalize(equity_df['positions'])
        equity_df = pd.concat([equity_df.drop(columns=['positions']), positions_df], axis=1)
        
        print(equity_df.columns)
        
        trades_df.to_csv(f"{base_dir}/data/trades_day_{day}.csv", index=False)
        equity_df.to_csv(f"{base_dir}/data/equity_day_{day}.csv", index=False)

        # Calculate and save per-asset metrics
        asset_metrics = {}
        for product in trades_df['product'].unique():
            asset_metrics[product] = {
                'trading_metrics': {k: float(v) if isinstance(v, (np.float64, np.int64)) else v for k, v in calculate_asset_metrics(trades_df, equity_df, product).items()},
                'market_metrics': {
                    'avg_spread': float(np.mean(spreads_log[product])),
                    'max_spread': float(np.max(spreads_log[product])),
                    'min_spread': float(np.min(spreads_log[product])),
                    'avg_market_depth': {
                        'bid': float(np.mean([d['bid_volume'] for d in market_depths_log[product]])),
                        'ask': float(np.mean([d['ask_volume'] for d in market_depths_log[product]]))
                    }
                }
            }

        # Save asset metrics
        metrics_file = f"{base_dir}/analysis/asset_metrics_day_{day}.json"
        with open(metrics_file, 'w') as f:
            json.dump(asset_metrics, f, indent=4)

        # Plot results
        plt.figure(figsize=(15, 15))
        
        # Plot 1: Equity Curve
        plt.subplot(3, 1, 1)
        timestamps = [row['timestamp'] for row in equity_curve_log]
        pnl_values = [row['total_pnl'] for row in equity_curve_log]
        plt.plot(timestamps, pnl_values, label='Total PnL', color='purple')
        plt.title("Market Making Performance")
        plt.xlabel("Timestamp")
        plt.ylabel("PnL")
        plt.grid(True)
        plt.legend()

        # Plot 2: Spreads
        plt.subplot(3, 1, 2)
        for product in spreads_log:
            plt.plot(timestamps[:len(spreads_log[product])], 
                    spreads_log[product], 
                    label=f'{product} Spread')
        plt.title("Bid-Ask Spreads")
        plt.xlabel("Timestamp")
        plt.ylabel("Spread")
        plt.grid(True)
        plt.legend()

        # Plot 3: Positions
        plt.subplot(3, 1, 3)
        position_data = pd.DataFrame([row['positions'] for row in equity_curve_log])
        for column in position_data.columns:
            plt.plot(timestamps, position_data[column], label=f'{column} Position')
        plt.title("Positions by Product")
        plt.xlabel("Timestamp")
        plt.ylabel("Position Size")
        plt.grid(True)
        plt.legend()

        plt.tight_layout()
        plt.savefig(f"{base_dir}/plots/performance_day_{day}.png")
        plt.close()

        # Print final summary
        final = equity_curve_log[-1]
        print("\nFinal Report")
        print("-" * 40)
        print(f"Final Inventory Value: {final['inventory_value']:.2f}")
        print(f"Final Total PnL: {final['total_pnl']:.2f}")
        print("\nPer-Asset Metrics saved to:", metrics_file)

if __name__ == "__main__":
    run_simulation()
