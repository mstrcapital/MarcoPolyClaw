"""
快速轮询交易监控器 (Fast Polling Monitor)
=========================================

比普通轮询更快 (10秒间隔)
检测目标地址的新交易并实时推送 Telegram

优化:
- 10秒快速轮询
- 差分检测 (只报变化)
- Telegram 实时推送
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Set
import aiohttp
from dotenv import load_dotenv

# 配置路径
CONFIG_DIR = Path(__file__).parent / "config"
load_dotenv(CONFIG_DIR / "tradersmonitor.env")

from wallet_info import get_wallet_info, get_profile_link

# API
DATA_API = "https://data-api.polymarket.com"

# 配置
MONITORED_WALLETS = os.getenv("MONITORED_WALLETS", "").split(",")
MONITORED_WALLETS = [w.strip().lower() for w in MONITORED_WALLETS if w.strip()]

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "10"))  # 10秒
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class TradeInfo:
    """交易信息"""
    condition_id: str
    market: str
    outcome: str
    size: float
    price: float
    value: float


# =============================================================================
# 快速监控器
# =============================================================================

class FastMonitor:
    """快速轮询监控器"""
    
    def __init__(self):
        self.previous_trades: dict[str, Set[str]] = {}  # wallet -> set of condition_ids
        self.is_running = False
        
        # 初始化
        for w in MONITORED_WALLETS:
            self.previous_trades[w] = set()
    
    async def get_positions(self, wallet: str) -> list[TradeInfo]:
        """获取钱包当前持仓"""
        url = f"{DATA_API}/positions"
        params = {"user": wallet}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
        except Exception as e:
            return []
        
        trades = []
        for p in data:
            # 过滤已平仓的
            current_value = float(p.get("currentValue", 0))
            if current_value <= 0:
                continue
            
            trade = TradeInfo(
                condition_id=p.get("conditionId", ""),
                market=p.get("title", ""),
                outcome=p.get("outcome", ""),
                size=float(p.get("size", 0)),
                price=float(p.get("avgPrice", 0)),
                value=current_value,
            )
            trades.append(trade)
        
        return trades
    
    def find_new_positions(self, wallet: str, current: list[TradeInfo]) -> list[TradeInfo]:
        """找新增仓位"""
        prev = self.previous_trades.get(wallet, set())
        current_ids = {t.condition_id for t in current}
        
        # 新增的
        new_ids = current_ids - prev
        
        return [t for t in current if t.condition_id in new_ids]
    
    async def send_telegram(self, message: str):
        """发送 Telegram 消息"""
        if not TELEGRAM_ENABLED or not TELEGRAM_BOT_TOKEN:
            return
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(url, json=data)
        except Exception as e:
            print(f"Telegram error: {e}")
    
    async def check_all(self):
        """检查所有钱包"""
        print(f"\n{'='*60}")
        print(f"🔍 Fast Scan ({SCAN_INTERVAL}s) - {len(MONITORED_WALLETS)} traders")
        print(f"{'='*60}")
        
        new_alerts = []
        
        for wallet in MONITORED_WALLETS:
            positions = await self.get_positions(wallet)
            new_positions = self.find_new_positions(wallet, positions)
            
            # 更新历史
            self.previous_trades[wallet] = {t.condition_id for t in positions}
            
            if new_positions:
                # 获取钱包信息
                info = get_wallet_info(wallet)
                profile_link = get_profile_link(wallet)
                
                print(f"\n🆕 {wallet}")
                print(f"   👤 {info.get('username', 'N/A')} | {info.get('pnl', 'N/A')}")
                for p in new_positions[:5]:  # 最多显示5个
                    print(f"   {p.market}")
                    print(f"   {p.outcome}: ${p.value:.2f}")
                
                # 生成 Telegram 消息
                msg = f"🆕 <b>{wallet}</b>\n"
                msg += f"👤 <a href=\"{profile_link}\">{info.get('username', 'N/A')}</a> | {info.get('pnl', 'N/A')}\n"
                for p in new_positions[:3]:
                    msg += f"• {p.market}\n"
                    msg += f"  {p.outcome}: ${p.value:.2f}\n"
                
                new_alerts.append(msg)
        
        # 发送 Telegram
        if new_alerts and TELEGRAM_ENABLED:
            full_msg = "🔔 <b>新仓位信号</b>\n\n" + "\n".join(new_alerts)
            await self.send_telegram(full_msg)
    
    async def start(self):
        """启动"""
        self.is_running = True
        
        print(f"\n🚀 Fast Monitor Started")
        print(f"   Interval: {SCAN_INTERVAL}s")
        print(f"   Telegram: {'✅' if TELEGRAM_ENABLED else '❌'}")
        
        while self.is_running:
            try:
                await self.check_all()
                await asyncio.sleep(SCAN_INTERVAL)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
                await asyncio.sleep(5)
        
        print("\n🛑 Stopped")
    
    def stop(self):
        self.is_running = False


# =============================================================================
# 主函数
# =============================================================================

async def main():
    if not MONITORED_WALLETS:
        print("❌ No wallets to monitor!")
        return
    
    monitor = FastMonitor()
    
    try:
        await monitor.start()
    except KeyboardInterrupt:
        monitor.stop()


if __name__ == "__main__":
    asyncio.run(main())
