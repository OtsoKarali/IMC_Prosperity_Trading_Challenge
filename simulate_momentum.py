import pandas as pd
from datamodel import Order, OrderDepth, TradingState, Symbol
from typing import Dict, List
import json
from MomentumTrader import Trader
import os
import sys
import matplotlib.pyplot as plt
from collections import defaultdict

def ensure_output_dirs():
    """Create output directories if they don't exist"""
    base_dir = "MomentumTrading"
    subdirs = ["data", "plots", "logs"]
    
    for subdir in [base_dir] + [f"{base_dir}/{d}" for d in subdirs]:
        if not os.path.exists(subdir):
            os.makedirs(subdir)
    return base_dir

def build_order_depth(row):
    depth = OrderDepth()
    # Just use level 1 data as that's what the momentum trader uses
    bid_price = row.get('bid_price_1')
    bid_volume = row.get('bid_volume_1')
    ask_price = row.get('ask_price_1')
    ask_volume = row.get('ask_volume_1')
    
    if pd.notna(bid_price) and pd.notna(bid_volume):
        depth.buy_orders[float(bid_price)] = float(bid_volume)
    if pd.notna(ask_price) and pd.notna(ask_volume):
        depth.sell_orders[float(ask_price)] = -float(ask_volume)
    return depth

def run_simulation():
    # Create output directories
    base_dir = ensure_output_dirs()
    
    # Load data
    day = sys.argv[1] if len(sys.argv) > 1 else "-1"
    price_file = f"PriceData/prices_round_1_day_{day}.csv"
    print(f"Simulating momentum strategy with price data from: {price_file}")

    if not os.path.exists(price_file):
        print(f"Error: Price data file not found at {price_file}")
        return

    # Initialize
    prices_df = pd.read_csv(price_file, sep=";")
    timestamps = sorted(prices_df['timestamp'].unique())
    trader = Trader()
    
    position = defaultdict(int)
    order_log = []
    equity_curve_log = []
    last_prices = {}

    # Open log file for real-time logging
    log_file = f"{base_dir}/logs/simulation_day_{day}.log"
    with open(log_file, 'w') as f:
        f.write(f"Starting simulation for day {day}\n")
        
        # Simulate each timestamp
        for t in timestamps:
            snapshot = prices_df[prices_df['timestamp'] == t]
            
            # Build order depths for this timestamp
            order_depths = {}
            for _, row in snapshot.iterrows():
                product = row['product']
                order_depths[product] = build_order_depth(row)
                
                # Calculate mid price if we have both sides
                if order_depths[product].buy_orders and order_depths[product].sell_orders:
                    best_bid = max(order_depths[product].buy_orders.keys())
                    best_ask = min(order_depths[product].sell_orders.keys())
                    last_prices[product] = (best_bid + best_ask) / 2

            # Create state and get trader actions
            state = TradingState(
                timestamp=t,
                listings={product: Symbol(product) for product in order_depths.keys()},
                order_depths=order_depths,
                own_trades={},
                market_trades={},
                position=dict(position),
                observations=None,
                traderData=""
            )

            try:
                orders, _, _ = trader.run(state)

                # Process orders
                for product, order_list in orders.items():
                    for order in order_list:
                        # Update position and log the trade
                        position[product] += order.quantity
                        order_log.append([t, product, order.price, order.quantity])

                # Calculate portfolio value
                unrealized = sum(pos * last_prices[product] for product, pos in position.items() if product in last_prices)
                
                equity_curve_log.append({
                    "timestamp": t,
                    "positions": dict(position),
                    "unrealized_value": unrealized
                })

                # Print and log status every 100 timestamps
                if int(t) % 100 == 0:
                    status = f"\nTime {t}:\n"
                    status += f"Positions: {dict(position)}\n"
                    status += f"Unrealized Value: {unrealized:.2f}\n"
                    status += "------------------------\n"
                    print(status)
                    f.write(status)

            except Exception as e:
                error_msg = f"Error at timestamp {t}: {str(e)}\n"
                print(error_msg)
                f.write(error_msg)
                continue

        if not equity_curve_log:
            msg = "No trades were executed during simulation\n"
            print(msg)
            f.write(msg)
            return

        # Save results
        output_file = f"{base_dir}/data/trades_day_{day}.csv"
        equity_file = f"{base_dir}/data/equity_day_{day}.csv"
        plot_file = f"{base_dir}/plots/equity_curve_day_{day}.png"

        pd.DataFrame(order_log, columns=["timestamp", "product", "price", "quantity"]).to_csv(output_file, index=False)
        pd.DataFrame(equity_curve_log).to_csv(equity_file, index=False)

        # Final report
        final = equity_curve_log[-1]
        final_report = "\nFinal Results:\n"
        final_report += f"Final Positions: {final['positions']}\n"
        final_report += f"Final Unrealized Value: {final['unrealized_value']:.2f}\n"
        print(final_report)
        f.write(final_report)

        # Plot equity curve
        timestamps = [row['timestamp'] for row in equity_curve_log]
        equity_values = [row['unrealized_value'] for row in equity_curve_log]

        plt.figure(figsize=(12, 5))
        plt.plot(timestamps, equity_values, label='Portfolio Value', color='blue')
        plt.title("Momentum Strategy Equity Curve")
        plt.xlabel("Timestamp")
        plt.ylabel("Value")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.savefig(plot_file)
        plt.close()

        f.write(f"\nResults saved to:\n")
        f.write(f"Trades: {output_file}\n")
        f.write(f"Equity curve: {equity_file}\n")
        f.write(f"Plot: {plot_file}\n")

if __name__ == "__main__":
    run_simulation() 