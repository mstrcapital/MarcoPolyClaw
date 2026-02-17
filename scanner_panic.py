"""
恐慌价差套利扫描器 (Panic Arbitrage Scanner)
=========================================

策略: 等待群众恐慌买入一边，然后买对面便宜的那边

条件:
1. 5分钟市场 (5m)
2. 一边价格 > 0.85 (群众恐慌买高)
3. 另一边价格 < 0.15 (便宜)
4. 买入便宜的那边，等价格回归
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
import aiohttp

from config import GAMMA_API


# =============================================================================
# 配置
# =============================================================================

MINUTES_BEFORE_END = 5  # 结束前5分钟
MIN_LIQUIDITY = 100


# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class PanicOpportunity:
    """恐慌套利机会"""
    market: str
    slug: str
    condition_id: str
    end_time: datetime
    minutes_left: int
    
    # 价格
    up_price: float
    down_price: float
    
    # 机会分析
    panic_side: str      # 恐慌买入的那边
    cheap_side: str      # 便宜的那边
    cheap_price: float
    potential_profit: float  # 潜在利润
    
    # 原因
    reason: str


# =============================================================================
# 扫描器
# =============================================================================

class PanicArbitrageScanner:
    """恐慌价差套利扫描器"""
    
    async def scan(self) -> list[PanicOpportunity]:
        """扫描恐慌套利机会"""
        
        # 获取5分钟市场
        url = f"{GAMMA_API}/markets"
        params = {
            "closed": "false",
            "limit": 200,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                markets = await resp.json()
        
        opportunities = []
        now = datetime.now()
        
        for m in markets:
            slug = m.get("slug", "")
            
            # 只关心5分钟市场
            if not ("5m" in slug.lower() or "-5-" in slug.lower()):
                continue
            
            # 获取时间
            end_date = m.get("endDate")
            if not end_date:
                continue
            
            # Parse with timezone
            if end_date.endswith('Z'):
                end_time = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            else:
                end_time = datetime.fromisoformat(end_date)
            
            # 计算分钟差 (统一为 UTC)
            now_utc = datetime.now(end_time.tzinfo) if end_time.tzinfo else now
            minutes_left = int((end_time - now_utc).total_seconds() / 60)
            
            # 过滤即将结束的市场
            if minutes_left < 0 or minutes_left > MINUTES_BEFORE_END * 3:
                continue
            
            # 获取价格
            outcome_prices = m.get("outcomePrices", "[]")
            try:
                prices = json.loads(outcome_prices)
                up_price = float(prices[0]) if len(prices) > 0 else 0
                down_price = float(prices[1]) if len(prices) > 1 else 0
            except:
                continue
            
            # 获取流动性
            liquidity = float(m.get("liquidity", 0))
            
            if liquidity < MIN_LIQUIDITY:
                continue
            
            # 检测恐慌模式
            # 模式1: UP > 0.85, DOWN < 0.15 (群众恐慌买UP)
            if up_price > 0.85 and down_price < 0.15:
                opportunity = PanicOpportunity(
                    market=m.get("question", ""),
                    slug=slug,
                    condition_id=m.get("conditionId", ""),
                    end_time=end_time,
                    minutes_left=minutes_left,
                    up_price=up_price,
                    down_price=down_price,
                    panic_side="UP",
                    cheap_side="DOWN",
                    cheap_price=down_price,
                    potential_profit=1.0 - down_price,
                    reason=f"UP恐慌上涨到{up_price:.2f}，DOWN跌到{down_price:.2f}",
                )
                opportunities.append(opportunity)
            
            # 模式2: DOWN > 0.85, UP < 0.15 (群众恐慌买DOWN)
            elif down_price > 0.85 and up_price < 0.15:
                opportunity = PanicOpportunity(
                    market=m.get("question", ""),
                    slug=slug,
                    condition_id=m.get("conditionId", ""),
                    end_time=end_time,
                    minutes_left=minutes_left,
                    up_price=up_price,
                    down_price=down_price,
                    panic_side="DOWN",
                    cheap_side="UP",
                    cheap_price=up_price,
                    potential_profit=1.0 - up_price,
                    reason=f"DOWN恐慌上涨到{down_price:.2f}，UP跌到{up_price:.2f}",
                )
                opportunities.append(opportunity)
        
        # 按剩余时间排序
        opportunities.sort(key=lambda x: x.minutes_left)
        return opportunities
    
    async def print_opportunities(self):
        """打印机会"""
        print("\n" + "="*60)
        print("😱 恐慌价差套利扫描器")
        print("="*60)
        
        opportunities = await self.scan()
        
        if opportunities:
            print(f"\n🎯 发现 {len(opportunities)} 个机会:\n")
            
            for i, o in enumerate(opportunities[:10], 1):
                print(f"{i}. {o.market[:50]}...")
                print(f"   ⏰ 剩余: {o.minutes_left} 分钟")
                print(f"   📊 价格: UP={o.up_price:.2f} | DOWN={o.down_price:.2f}")
                print(f"   💰 建议: 买入 {o.cheap_side} @ {o.cheap_price:.2f}")
                print(f"   📈 潜在利润: {o.potential_profit*100:.1f}%")
                print(f"   📝 {o.reason}")
                print()
        else:
            print("\n❌ 暂无可用机会")


# =============================================================================
# 主函数
# =============================================================================

async def main():
    scanner = PanicArbitrageScanner()
    await scanner.print_opportunities()


if __name__ == "__main__":
    asyncio.run(main())
