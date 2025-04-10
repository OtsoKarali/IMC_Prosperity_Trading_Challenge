import pandas as pd
from datamodel import Order, OrderDepth, TradingState, Symbol
from typing import Dict, List
import json
import numpy as np
from MeanReversionTrader import Trader
import os
import sys
import matplotlib.pyplot as plt
from collections import defaultdict

def calculate_market_stats(prices_df):
    """Calculate market statistics for each product"""
    stats = {}
    for product in prices_df['product'].unique():
        # Create a copy to avoid SettingWithCopyWarning
        product_data = prices_df[prices_df['product'] == product].copy()
        
        # Calculate spreads
        product_data.loc[:, 'spread'] = product_data['ask_price_1'] - product_data['bid_price_1']
        product_data.loc[:, 'mid_price'] = (product_data['ask_price_1'] + product_data['bid_price_1']) / 2
        product_data.loc[:, 'returns'] = product_data['mid_price'].pct_change()
        
        # Convert numpy types to Python native types for JSON serialization
        stats[product] = {
            'avg_spread': float(product_data['spread'].mean()),
            'min_spread': float(product_data['spread'].min()),
            'max_spread': float(product_data['spread'].max()),
            'volatility': float(product_data['returns'].std() * np.sqrt(len(product_data))),
            'price_range': {
                'min': float(product_data['mid_price'].min()),
                'max': float(product_data['mid_price'].max()),
                'mean': float(product_data['mid_price'].mean())
            }
        }
    return stats

def ensure_output_dirs():
    """Create output directories if they don't exist"""
    base_dir = "MeanReversionTrading"
    subdirs = ["data", "plots", "logs", "analysis"]
    
    for subdir in [base_dir] + [f"{base_dir}/{d}" for d in subdirs]:
        if not os.path.exists(subdir):
            os.makedirs(subdir)
    return base_dir

def build_order_depth(row):
    depth = OrderDepth()
    # Use level 1 data for order book
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
    print(f"Simulating mean reversion strategy with price data from: {price_file}")

    if not os.path.exists(price_file):
        print(f"Error: Price data file not found at {price_file}")
        return

    # Initialize
    prices_df = pd.read_csv(price_file, sep=";")
    
    # Calculate and save market statistics
    print("\nCalculating market statistics...")
    market_stats = calculate_market_stats(prices_df)
    stats_file = f"{base_dir}/analysis/market_stats_day_{day}.json"
    with open(stats_file, 'w') as f:
        json.dump(market_stats, f, indent=4)
    
    # Print market statistics
    print("\nMarket Statistics:")
    for product, stats in market_stats.items():
        print(f"\n{product}:")
        print(f"  Average Spread: {stats['avg_spread']:.2f}")
        print(f"  Volatility: {stats['volatility']:.4f}")
        print(f"  Price Range: {stats['price_range']['min']:.2f} - {stats['price_range']['max']:.2f}")
    
    timestamps = sorted(prices_df['timestamp'].unique())
    trader = Trader()
    
    position = defaultdict(int)
    order_log = []
    equity_curve_log = []
    last_prices = {}
    
    # Track mean reversion specific metrics
    price_history = defaultdict(list)
    zscore_values = defaultdict(list)

    # Open log file for real-time logging
    log_file = f"{base_dir}/logs/simulation_day_{day}.log"
    with open(log_file, 'w') as f:
        f.write(f"Starting mean reversion simulation for day {day}\n")
        
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
                    mid_price = (best_bid + best_ask) / 2
                    last_prices[product] = mid_price
                    
                    # Update price history and calculate z-score
                    price_history[product].append(mid_price)
                    if len(price_history[product]) > 15:  # Use 15-tick window
                        price_history[product].pop(0)
                        mean = np.mean(price_history[product])
                        std = np.std(price_history[product])
                        if std > 0:
                            zscore = (mid_price - mean) / std
                            zscore_values[product].append(zscore)

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
                orders, _, trader_state = trader.run(state)

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
                    "unrealized_value": unrealized,
                    "zscores": {p: zscore_values[p][-1] if zscore_values[p] else 0 for p in position.keys()}
                })

                # Print and log status every 100 timestamps
                if int(t) % 100 == 0:
                    status = f"\nTime {t}:\n"
                    status += f"Positions: {dict(position)}\n"
                    status += f"Unrealized Value: {unrealized:.2f}\n"
                    for product in position:
                        if zscore_values[product]:
                            status += f"{product} Z-Score: {zscore_values[product][-1]:.2f}\n"
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

        # Save detailed results
        output_file = f"{base_dir}/data/trades_day_{day}.csv"
        equity_file = f"{base_dir}/data/equity_day_{day}.csv"
        plot_file = f"{base_dir}/plots/equity_curve_day_{day}.png"
        
        # Save trade log with more details
        trades_df = pd.DataFrame(order_log, columns=["timestamp", "product", "price", "quantity"])
        trades_df.to_csv(output_file, index=False)
        
        # Save equity curve with z-scores
        pd.DataFrame(equity_curve_log).to_csv(equity_file, index=False)

        # Final report
        final = equity_curve_log[-1]
        final_report = "\nFinal Results:\n"
        final_report += f"Final Positions: {final['positions']}\n"
        final_report += f"Final Unrealized Value: {final['unrealized_value']:.2f}\n"
        print(final_report)
        f.write(final_report)

        # Enhanced visualization
        plt.figure(figsize=(15, 15))
        
        # Plot 1: Equity Curve
        plt.subplot(3, 1, 1)
        timestamps = [row['timestamp'] for row in equity_curve_log]
        equity_values = [row['unrealized_value'] for row in equity_curve_log]
        plt.plot(timestamps, equity_values, label='Portfolio Value', color='blue')
        plt.title("Mean Reversion Strategy Performance")
        plt.xlabel("Timestamp")
        plt.ylabel("Portfolio Value")
        plt.grid(True)
        plt.legend()

        # Plot 2: Z-Scores
        if zscore_values:
            plt.subplot(3, 1, 2)
            for product in zscore_values:
                plt.plot(timestamps[-len(zscore_values[product]):], 
                        zscore_values[product], 
                        label=f'{product} Z-Score')
            plt.axhline(y=1.5, color='r', linestyle='--', label='Upper Threshold')
            plt.axhline(y=-1.5, color='g', linestyle='--', label='Lower Threshold')
            plt.title("Z-Scores by Product")
            plt.xlabel("Timestamp")
            plt.ylabel("Z-Score")
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
        plt.savefig(plot_file)
        plt.close()

        f.write(f"\nResults saved to:\n")
        f.write(f"Trades: {output_file}\n")
        f.write(f"Equity curve: {equity_file}\n")
        f.write(f"Plot: {plot_file}\n")
        f.write(f"Market stats: {stats_file}\n")

if __name__ == "__main__":
    run_simulation() 