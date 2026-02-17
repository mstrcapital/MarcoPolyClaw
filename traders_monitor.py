"""
交易员监控器 (Traders Monitor)
============================

监控 tradersmonitor.env 中的交易员仓位
检测新开仓/平仓 并推送提醒
"""

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
import aiohttp
from dotenv import load_dotenv

# 配置路径
CONFIG_DIR = Path(__file__).parent / "config"
load_dotenv(CONFIG_DIR / "tradersmonitor.env")

# API
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "60"))
MIN_POSITION_VALUE = float(os.getenv("MIN_POSITION_VALUE", "10"))

MONITORED_WALLETS = os.getenv("MONITORED_WALLETS", "").split(",")
MONITORED_WALLETS = [w.strip() for w in MONITORED_WALLETS if w.strip()]

# 类别开关
MONITOR_SHORT_TERM = os.getenv("MONITOR_SHORT_TERM", "true").lower() == "true"
MONITOR_WEATHER = os.getenv("MONITOR_WEATHER", "true").lower() == "true"
MONITOR_NEGRISK = os.getenv("MONITOR_NEGRISK", "true").lower() == "true"
MONITOR_BASIC = os.getenv("MONITOR_BASIC", "true").lower() == "true"
MONITOR_ANALYSIS = os.getenv("MONITOR_ANALYSIS", "true").lower() == "true"
MONITOR_BTC_HF = os.getenv("MONITOR_BTC_HF", "true").lower() == "true"


# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class Position:
    """持仓"""
    condition_id: str
    question: str
    outcome: str
    size: float
    value: float
    price: float


@dataclass
class TraderState:
    """交易员状态"""
    address: str
    positions: list[Position] = field(default_factory=list)
    last_update: datetime = field(default_factory=datetime.now)


# =============================================================================
# 监控器
# =============================================================================

class TradersMonitor:
    """交易员监控器"""
    
    def __init__(self):
        self.states: dict[str, TraderState] = {}
        self.previous_states: dict[str, list[Position]] = {}
        self.is_running = False
        
        # 初始化状态
        for wallet in MONITORED_WALLETS:
            self.states[wallet] = TraderState(address=wallet)
    
    async def get_positions(self, wallet: str) -> list[Position]:
        """获取钱包持仓"""
        url = f"{DATA_API}/positions"
        params = {"user": wallet}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
        except Exception as e:
            print(f"Error getting positions for {wallet}: {e}")
            return []
        
        positions = []
        for p in data:
            size = float(p.get("size", 0))
            avg_price = float(p.get("avgPrice", 0))
            current_value = float(p.get("currentValue", 0))
            
            # Use current value or initial value
            value = current_value if current_value > 0 else size * avg_price
            
            if value < MIN_POSITION_VALUE:
                continue
            
            position = Position(
                condition_id=p.get("conditionId", ""),
                question=p.get("title", ""),
                outcome=p.get("outcome", ""),
                size=size,
                value=value,
                price=avg_price,
            )
            positions.append(position)
        
        return positions
    
    async def check_traders(self):
        """检查所有交易员"""
        print(f"\n{'='*60}")
        print(f"🔍 Scanning {len(MONITORED_WALLETS)} traders...")
        print(f"{'='*60}")
        
        for wallet in MONITORED_WALLETS:
            positions = await self.get_positions(wallet)
            prev_positions = self.previous_states.get(wallet, [])
            
            # 检测新仓
            current_ids = {p.condition_id for p in positions}
            prev_ids = {p.condition_id for p in prev_positions}
            
            new_positions = [p for p in positions if p.condition_id not in prev_ids]
            closed_positions = [p for p in prev_positions if p.condition_id not in current_ids]
            
            # 打印结果
            print(f"\n👤 {wallet[:10]}...")
            
            if new_positions:
                print(f"  🆕 NEW POSITIONS ({len(new_positions)}):")
                for p in new_positions:
                    print(f"     • {p.question[:40]}...")
                    print(f"       {p.outcome}: ${p.value:.2f} ({p.size:.1f} @ ${p.price:.2f})")
            
            if closed_positions:
                print(f"  ❌ CLOSED ({len(closed_positions)}):")
                for p in closed_positions:
                    print(f"     • {p.question[:40]}...")
            
            if not new_positions and not closed_positions:
                print(f"  ✅ No changes")
            
            # 更新状态
            self.previous_states[wallet] = positions
    
    async def start(self):
        """启动监控"""
        self.is_running = True
        print(f"\n🚀 Traders Monitor Started")
        print(f"   Wallets: {len(MONITORED_WALLETS)}")
        print(f"   Interval: {SCAN_INTERVAL}s")
        print(f"   Min Position: ${MIN_POSITION_VALUE}")
        
        while self.is_running:
            try:
                await self.check_traders()
                await asyncio.sleep(SCAN_INTERVAL)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
                await asyncio.sleep(5)
        
        print("\n🛑 Monitor stopped")
    
    def stop(self):
        """停止监控"""
        self.is_running = False


# =============================================================================
# 主函数
# =============================================================================

async def main():
    if not MONITORED_WALLETS:
        print("❌ No wallets to monitor!")
        print("   Set MONITORED_WALLETS in config/tradersmonitor.env")
        return
    
    monitor = TradersMonitor()
    
    # 处理 Ctrl+C
    try:
        await monitor.start()
    except KeyboardInterrupt:
        monitor.stop()


if __name__ == "__main__":
    asyncio.run(main())
