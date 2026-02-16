#!/usr/bin/env python3
"""Polymarket 套利扫描器启动器

用法:
    python3 runner.py              # 单次扫描
    python3 runner.py --continuous  # 持续扫描
    python3 runner.py --status     # 查看配置状态
    python3 runner.py --advanced   # 高级扫描 (支持策略选择)
    python3 runner.py --copy       # 启动跟单模式
"""

import asyncio
import argparse
import os
import sys
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from scanner_v2 import FullScanner, get_expiry_summary, get_time_bucket
from config import (
    has_wallet, has_llm, has_copy_trader,
    get_wallet_address, MONITORED_WALLETS,
    OPENROUTER_API_KEY, WALLET_PRIVATE_KEY
)

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "300"))

# 策略配置
STRATEGIES = {
    "default": {
        "min_win_rate": 0.70,
        "max_win_rate": 0.96,
        "min_price": 0.87,
        "max_price": 0.96,
        "max_hours": 2000,
        "min_liquidity": 1000,
    },
    "highprop": {
        "name": "高概率",
        "min_win_rate": 0.88,
        "max_win_rate": 0.96,
        "min_price": 0.87,
        "max_price": 0.96,
        "max_hours": 3,
        "min_liquidity": 3000,
    },
    "whale": {
        "name": "鲸鱼信号",
        "min_win_rate": 0.70,
        "max_win_rate": 0.99,
        "min_price": 0.50,
        "max_price": 0.99,
        "max_hours": 24,
        "min_liquidity": 5000,
    },
}

async def run_scan(scanner: FullScanner):
    """执行单次扫描"""
    async with scanner.client:
        result = await scanner.scan()
        
        # 到期时间统计
        expiry_stats = get_expiry_summary(list(scanner.markets.values()))
        
        print("\n" + "=" * 60)
        print("📊 Polymarket 扫描报告")
        print("=" * 60)
        print(f"市场总数:     {result['total_markets']}")
        print(f"有效市场:     {result['valid_markets']}")
        print(f"分组数量:     {result['groups']}")
        print(f"套利机会:     {result['arbitrage_opportunities']}")
        print(f"对冲机会:     {result['hedge_opportunities']}")
        
        print("\n⏰ 到期时间分布:")
        print(f"   <1h:   {expiry_stats.get('<1h', 0):>4} | 1-5h:  {expiry_stats.get('1-5h', 0):>4} | 5-10h: {expiry_stats.get('5-10h', 0):>4}")
        print(f"   10-24h: {expiry_stats.get('10-24h', 0):>4} | 24-48h: {expiry_stats.get('24-48h', 0):>4} | 48h+:   {expiry_stats.get('48h+', 0):>4} | N/A:    {expiry_stats.get('N/A', 0):>4}")
        
        print("=" * 60)
        
        # 显示最佳机会
        if scanner.hedges:
            print("\n🏆 最佳对冲机会:")
            for i, h in enumerate(scanner.hedges[:5], 1):
                profit_pct = (h.expected_profit / h.total_cost * 100) if h.total_cost > 0 else 0
                bucket = get_time_bucket(h.target_market.hours_until_expiry)
                expiry_str = f" | 到期: {bucket}" if bucket != "N/A" else ""
                print(f"  {i}. {h.target_market.question[:40]}...")
                print(f"     覆盖率: {h.coverage*100:.1f}%{expiry_str} | 成本: ${h.total_cost:.2f} | 利润: ${h.expected_profit:.2f} ({profit_pct:.1f}%)")
        
        if scanner.opportunities:
            print("\n🎯 套利机会:")
            for i, opp in enumerate(scanner.opportunities[:5], 1):
                bucket = get_time_bucket(opp.market_id)
                print(f"  {i}. {opp.question[:40]}...")
                print(f"     YES: ${opp.yes_price:.2f} NO: ${opp.no_price:.2f} 偏差: {opp.deviation*100:.1f}%")

async def continuous_scan():
    """持续扫描"""
    scanner = FullScanner()
    
    print(f"🔄 启动持续扫描 (间隔: {SCAN_INTERVAL}秒)")
    print("按 Ctrl+C 停止\n")
    
    try:
        while True:
            await run_scan(scanner)
            await asyncio.sleep(SCAN_INTERVAL)
    except KeyboardInterrupt:
        print("\n🛑 扫描已停止")

def show_status():
    """显示配置状态"""
    print("\n" + "=" * 60)
    print("⚙️  配置状态")
    print("=" * 60)
    
    # 扫描器配置
    from config import TAGS, SCAN_INTERVAL, MIN_LIQUIDITY, MIN_VOLUME
    print(f"\n📡 扫描器:")
    print(f"   标签: {TAGS}")
    print(f"   间隔: {SCAN_INTERVAL}秒")
    print(f"   最小流动性: ${MIN_LIQUIDITY:,.0f}")
    print(f"   最小成交量: ${MIN_VOLUME:,.0f}")
    
    # 钱包配置
    print(f"\n💰 钱包:")
    if has_wallet():
        addr = get_wallet_address()
        print(f"   ✅ 已配置: {addr[:10]}...{addr[-6:]}")
    else:
        print(f"   ❌ 未配置 (设置 wallet.env)")
    
    # LLM 配置
    print(f"\n🤖 LLM:")
    if has_llm():
        print(f"   ✅ 已配置")
    else:
        print(f"   ❌ 未配置 (设置 wallet.env OPENROUTER_API_KEY)")
    
    # 跟单配置
    print(f"\n📥 跟单:")
    if has_copy_trader():
        print(f"   ✅ 已配置")
        print(f"   监控钱包: {MONITORED_WALLETS}")
    else:
        print(f"   ❌ 未配置")
        print(f"   需要: wallet.env + MONITORED_WALLETS")
    
    print("=" * 60)

async def start_copy_trader():
    """启动跟单模式"""
    from copy_trader_v2 import CopyTrader, PendingTxListener
    
    if not has_copy_trader():
        print("❌ 请先配置钱包和监控地址")
        print("   编辑 wallet.env:")
        print("   WALLET_PRIVATE_KEY=...")
        print("   MONITORED_WALLETS=0x123...,0x456...")
        return
    
    print(f"\n📥 启动跟单模式...")
    print(f"   监控: {MONITORED_WALLETS}")
    print(f"   钱包: {get_wallet_address()[:10]}...")
    
    # 启动跟单器
    trader = CopyTrader(WALLET_PRIVATE_KEY)
    
    # 启动监听
    from config import POLYGON_RPC
    listener = PendingTxListener(POLYGON_RPC)
    
    async def on_trade(trade):
        logger.info(f"📥 源交易: {trade.tx_hash[:20]}")
        result = await trader.execute_copy(trade)
        if result.success:
            logger.info(f"✅ 跟单成功!")
        else:
            logger.error(f"❌ 跟单失败: {result.error}")
    
    print("\n🚀 启动监控...")
    await listener.start(on_trade)

def main():
    parser = argparse.ArgumentParser(description="Polymarket 套利扫描器")
    parser.add_argument("--continuous", "-c", action="store_true", help="持续扫描")
    parser.add_argument("--status", "-s", action="store_true", help="查看配置状态")
    parser.add_argument("--advanced", "-a", action="store_true", help="高级扫描模式")
    parser.add_argument("--strategy", "-str", choices=list(STRATEGIES.keys()), 
                       default="default", help="选择扫描策略")
    parser.add_argument("--copy", "-o", action="store_true", help="启动跟单模式")
    parser.add_argument("--interval", "-i", type=int, default=SCAN_INTERVAL, help="扫描间隔(秒)")
    
    args = parser.parse_args()
    
    if args.status:
        show_status()
        return
    
    if args.copy:
        asyncio.run(start_copy_trader())
        return
    
    if args.advanced:
        # 高级扫描模式
        import advanced_scanner
        import sys
        
        strategy = STRATEGIES[args.strategy]
        
        # 更新全局参数
        advanced_scanner.MIN_WIN_RATE = strategy["min_win_rate"]
        advanced_scanner.MAX_WIN_RATE = strategy["max_win_rate"]
        advanced_scanner.MIN_PRICE = strategy["min_price"]
        advanced_scanner.MAX_PRICE = strategy["max_price"]
        advanced_scanner.MAX_HOURS = strategy["max_hours"]
        advanced_scanner.MIN_LIQUIDITY = strategy["min_liquidity"]
        
        async def run_advanced():
            from advanced_scanner import AdvancedScanner
            scanner = AdvancedScanner()
            result = await scanner.scan(["crypto", "finance"])
            
            print("\n" + "=" * 60)
            print(f"📊 策略: {strategy.get('name', args.strategy)}")
            print(f"   胜率: {strategy['min_win_rate']*100:.0f}%-{strategy['max_win_rate']*100:.0f}%")
            print(f"   价格: {strategy['min_price']:.2f}-{strategy['max_price']:.2f}")
            print(f"   到期: ≤{strategy['max_hours']}h | 深度: ≥${strategy['min_liquidity']:,.0f}")
            print("=" * 60)
            print(f"市场总数:     {result['total_markets']}")
            print(f"符合条件:     {result['filtered_count']}")
            print(f"信号数量:     {result['signals_count']}")
            print(f"套利机会:     {result['opportunities_count']}")
            print("=" * 60)
            
            signals = scanner.get_top_signals(10)
            if signals:
                print("\n🏆 Top 10 信号:")
                for i, s in enumerate(signals, 1):
                    print(f"{i}. {s.question[:45]}...")
                    print(f"   {s.side} @ ${s.price:.3f} | 胜率: {s.win_rate*100:.1f}% | 到期: {s.hours_until_expiry:.1f}h")
            
            opps = scanner.get_top_opportunities(5)
            if opps:
                print("\n🎯 Top 5 套利机会:")
                for i, o in enumerate(opps, 1):
                    print(f"{i}. {o.deviation*100:.2f}% | 预期: ${o.expected_profit:.3f}")
        
        asyncio.run(run_advanced())
        return
    
    if args.continuous:
        asyncio.run(continuous_scan())
    else:
        scanner = FullScanner()
        asyncio.run(run_scan(scanner))

if __name__ == "__main__":
    main()
