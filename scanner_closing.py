"""
尾盘/结算期扫描器 (Closing Scanner)
=====================================

策略: Dispute Window Arbitrage (结算期套利)
参考: @mikocrypto11 的 033033033 策略

原理:
1. 监控目标钱包的仓位
2. 当市场进入争议期/结算期时，结果已经"板上钉钉"
3. 在流动性崩塌前买入确定获胜的那一侧
4. 低风险套利

特点:
- 不需要预测结果 (结果已经确定)
- 利用"结算风险"取代"价格发现"
- 胜率极高
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import aiohttp

from config import GAMMA_API, CLOB_API


# =============================================================================
# 配置
# =============================================================================

# 要监控的钱包地址
MONITORED_WALLETS = [
    "0x033033033",  # 著名交易员
    # 可以添加更多
]

# 结算前几分钟开始监控
MINUTES_BEFORE_END = 30  # 结束前30分钟

# 最小流动性
MIN_LIQUIDITY = 1000


# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class WalletPosition:
    """钱包持仓"""
    address: str
    condition_id: str
    question: str
    yes_shares: float
    no_shares: float
    side: str  # "YES" or "NO"


@dataclass
class ClosingMarket:
    """尾盘市场"""
    condition_id: str
    question: str
    slug: str
    end_time: datetime
    minutes_left: int
    yes_price: float
    no_price: float
    volume: float
    liquidity: float
    resolved: bool = False


@dataclass
class ArbitrageSignal:
    """套利信号"""
    type: str           # "closing_arb"
    market: ClosingMarket
    side: str           # "YES" or "NO"
    current_price: float
    expected_price: float  # 结算时应该是 1.0
    profit_potential: float
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)


# =============================================================================
# 市场扫描
# =============================================================================

class ClosingScanner:
    """尾盘扫描器"""
    
    def __init__(self, monitored_wallets: list[str] = None):
        self.monitored_wallets = monitored_wallets or MONITORED_WALLETS
        self.positions_cache = {}
        self.is_running = False
    
    async def scan_closing_markets(self) -> list[ClosingMarket]:
        """扫描即将结束的市场"""
        url = f"{GAMMA_API}/markets"
        
        params = {
            "closed": "false",
            "limit": 100,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                markets_data = await resp.json()
        
        results = []
        now = datetime.now()
        
        for market in markets_data:
            end_date = market.get("endDate")
            if not end_date:
                continue
            
            end_time = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            minutes_left = int((end_time - now).total_seconds() / 60)
            
            # 只关心即将结束的市场
            if minutes_left > MINUTES_BEFORE_END * 2:  # 最多扫描 1 小时
                continue
            
            # 获取价格
            outcome_prices = market.get("outcomePrices", "[]")
            try:
                prices = json.loads(outcome_prices)
                yes_price = float(prices[0]) if len(prices) > 0 else 0
                no_price = float(prices[1]) if len(prices) > 1 else 0
            except:
                yes_price = 0
                no_price = 0
            
            closing_market = ClosingMarket(
                condition_id=market.get("conditionId", ""),
                question=market.get("question", ""),
                slug=market.get("slug", ""),
                end_time=end_time,
                minutes_left=minutes_left,
                yes_price=yes_price,
                no_price=no_price,
                volume=float(market.get("volume", 0)),
                liquidity=float(market.get("liquidity", 0)),
            )
            
            results.append(closing_market)
        
        # 按剩余时间排序
        results.sort(key=lambda x: x.minutes_left)
        return results
    
    async def get_wallet_positions(self, wallet: str) -> list[WalletPosition]:
        """获取钱包在某市场的持仓"""
        # 使用 Gamma API 的 positions 端点
        url = f"{GAMMA_API}/positions"
        params = {"address": wallet}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
        except:
            return []
        
        positions = []
        for p in data:
            position = WalletPosition(
                address=wallet,
                condition_id=p.get("conditionId", ""),
                question=p.get("question", ""),
                yes_shares=float(p.get("yesShares", 0)),
                no_shares=float(p.get("noShares", 0)),
                side="YES" if float(p.get("yesShares", 0)) > float(p.get("noShares", 0)) else "NO",
            )
            positions.append(position)
        
        return positions
    
    async def find_closing_opportunities(self) -> list[ArbitrageSignal]:
        """寻找尾盘套利机会"""
        signals = []
        
        # 1. 扫描即将结束的市场
        closing_markets = await self.scan_closing_markets()
        
        print(f"\n[Closing Scanner] Found {len(closing_markets)} closing markets")
        
        # 2. 监控目标钱包的持仓
        for wallet in self.monitored_wallets:
            positions = await self.get_wallet_positions(wallet)
            
            if positions:
                print(f"[Closing Scanner] {wallet}: {len(positions)} positions")
        
        # 3. 分析每个即将结束的市场
        for market in closing_markets:
            # 只关心临近结束的市场
            if market.minutes_left > MINUTES_BEFORE_END:
                continue
            
            # 检查流动性
            if market.liquidity < MIN_LIQUIDITY:
                continue
            
            # 寻找信号：价格已经很高/很低，但还没到 1.0
            # 这种情况说明结果基本确定，但还有套利空间
            
            # YES 侧接近 1.0 (Yes 几乎确定会赢)
            if market.yes_price > 0.85 and market.yes_price < 0.99:
                profit = 1.0 - market.yes_price
                signal = ArbitrageSignal(
                    type="closing_arb",
                    market=market,
                    side="YES",
                    current_price=market.yes_price,
                    expected_price=1.0,
                    profit_potential=profit,
                    reason=f"YES侧接近1.0 ({market.yes_price:.2f})，结果基本确定",
                )
                signals.append(signal)
            
            # NO 侧接近 1.0 (No 几乎确定会赢)
            if market.no_price > 0.85 and market.no_price < 0.99:
                profit = 1.0 - market.no_price
                signal = ArbitrageSignal(
                    type="closing_arb",
                    market=market,
                    side="NO",
                    current_price=market.no_price,
                    expected_price=1.0,
                    profit_potential=profit,
                    reason=f"NO侧接近1.0 ({market.no_price:.2f})，结果基本确定",
                )
                signals.append(signal)
        
        # 按利润排序
        signals.sort(key=lambda x: x.profit_potential, reverse=True)
        return signals
    
    async def start(self, interval: int = 30):
        """启动扫描"""
        self.is_running = True
        print(f"[Closing Scanner] Starting...")
        print(f"[Closing Scanner] Monitoring wallets: {self.monitored_wallets}")
        
        while self.is_running:
            try:
                signals = await self.find_closing_opportunities()
                
                if signals:
                    print(f"\n[Closing Scanner] === Signals ===")
                    for s in signals[:5]:
                        print(f"  {s.side} @ {s.current_price:.4f} -> {s.expected_price:.4f}")
                        print(f"    Profit: {s.profit_potential*100:.2f}%")
                        print(f"    Market: {s.market.question[:50]}...")
                        print(f"    Time: {s.market.minutes_left} min left")
                        print()
                else:
                    print(f"[Closing Scanner] No opportunities found")
                
                await asyncio.sleep(interval)
                
            except Exception as e:
                print(f"[Closing Scanner] Error: {e}")
                await asyncio.sleep(5)
    
    def stop(self):
        """停止扫描"""
        self.is_running = False
        print("[Closing Scanner] Stopped")


# =============================================================================
# 主函数
# =============================================================================

async def main():
    scanner = ClosingScanner()
    await scanner.start(interval=60)


if __name__ == "__main__":
    asyncio.run(main())
