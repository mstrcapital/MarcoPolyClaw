"""
15分钟暴跌套利策略 (DipArb Strategy)
=====================================

基于 poly-sdk DipArbService 逻辑的 Python 实现

策略原理：
1. 每个市场有一个 "price to beat"（开盘时的 Chainlink 价格）
2. 结算规则：
   - UP 赢：结束时价格 >= price to beat
   - DOWN 赢：结束时价格 < price to beat
3. 套利流程：
   - Leg1：检测暴跌 → 买入暴跌侧
   - Leg2：等待对冲条件 → 买入另一侧
   - 利润：总成本 < $1 时获得无风险利润

支持币种：BTC, ETH, SOL, XRP
支持周期：5m, 15m
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
import aiohttp

# 导入配置
from config import GAMMA_API, CLOB_API


# =============================================================================
# 常量配置
# =============================================================================

class DipArbSide(Enum):
    UP = "UP"
    DOWN = "DOWN"


class DipArbPhase(Enum):
    """套利阶段"""
    WAITING = "waiting"           # 等待开市
    LEG1_PENDING = "leg1_pending" # 等待 Leg1 信号
    LEG1_FILLED = "leg1_filled"   # Leg1 已执行
    COMPLETED = "completed"        # 套利完成


# 暴跌阈值配置
DEFAULT_DIP_THRESHOLD = 0.003     # 3% 跌幅触发 Leg1
DEFAULT_HEDGE_THRESHOLD = 0.005   # 5% 反弹触发 Leg2
DEFAULT_MIN_LIQUIDITY = 1000       # 最小流动性
DEFAULT_MAX_SLIPPAGE = 0.02        # 最大滑点 2%


# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class DipArbMarket:
    """15分钟市场配置"""
    name: str
    slug: str
    condition_id: str
    up_token_id: str
    down_token_id: str
    underlying: str          # BTC, ETH, SOL, XRP
    duration_minutes: int    # 5 或 15
    end_time: datetime
    price_to_beat: float = 0  # Chainlink 参考价格


@dataclass
class DipArbRound:
    """当前轮次状态"""
    round_id: str
    market: DipArbMarket
    phase: DipArbPhase = DipArbPhase.WAITING
    price_to_beat: float = 0
    
    # Leg1 状态
    leg1_side: Optional[DipArbSide] = None
    leg1_price: float = 0
    leg1_shares: float = 0
    leg1_token_id: str = ""
    
    # Leg2 状态
    leg2_side: Optional[DipArbSide] = None
    leg2_price: float = 0
    leg2_shares: float = 0
    
    # 盈亏
    total_cost: float = 0
    profit: float = 0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class DipArbSignal:
    """套利信号"""
    type: str               # "dip" 或 "hedge"
    side: DipArbSide
    current_price: float
    target_price: float
    shares: float
    token_id: str
    round_id: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class DipArbConfig:
    """策略配置"""
    coin: str = "all"                    # BTC, ETH, SOL, XRP, all
    duration: str = "15m"                 # 5m, 15m, all
    min_minutes_until_end: int = 5
    max_minutes_until_end: int = 60
    
    # 触发阈值
    dip_threshold: float = DEFAULT_DIP_THRESHOLD
    hedge_threshold: float = DEFAULT_HEDGE_THRESHOLD
    
    # 交易参数
    min_liquidity: float = DEFAULT_MIN_LIQUIDITY
    max_slippage: float = DEFAULT_MAX_SLIPPAGE
    split_orders: int = 1                  # 分单数量
    order_interval_ms: int = 100           # 订单间隔
    
    # 自动执行
    auto_execute: bool = False
    auto_merge: bool = True                # 自动合并仓位
    
    # 调试
    debug: bool = False


@dataclass
class DipArbStats:
    """统计信息"""
    rounds_monitored: int = 0
    rounds_successful: int = 0
    leg1_filled: int = 0
    leg2_filled: int = 0
    total_profit: float = 0
    total_spent: float = 0
    start_time: int = field(default_factory=lambda: int(time.time() * 1000))


# =============================================================================
# 市场扫描
# =============================================================================

class DipArbScanner:
    """15分钟暴跌套利扫描器"""
    
    def __init__(self, config: DipArbConfig = None):
        self.config = config or DipArbConfig()
        self.stats = DipArbStats()
        self.current_round: Optional[DipArbRound] = None
        self.is_running = False
        
        # 价格历史 (用于滑窗检测)
        self.price_history = []
        self.MAX_HISTORY_LENGTH = 100
        
        # 订单簿缓存
        self.up_asks = []
        self.down_asks = []
    
    async def scan_upcoming_markets(self) -> list[DipArbMarket]:
        """扫描即将开始的 UP/DOWN 市场"""
        
        # 搜索加密货币短期市场
        url = f"{GAMMA_API}/markets"
        
        params = {
            "limit": 50,
            "closed": "false",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                markets_data = await resp.json()
        
        results = []
        now = datetime.now()
        
        for market in markets_data:
            question = market.get("question", "")
            slug = market.get("slug", "")
            
            # 过滤 UP/DOWN 市场
            if not self._is_crypto_up_down(slug):
                continue
            
            # 解析币种和周期
            underlying, duration = self._parse_underlying_duration(slug)
            if not underlying:
                continue
            
            # 过滤币种
            if self.config.coin != "all" and underlying.upper() != self.config.coin.upper():
                continue
            
            # 过滤周期
            if self.config.duration != "all" and duration != self.config.duration:
                continue
            
            # 检查时间
            end_date = market.get("endDate")
            if not end_date:
                continue
            
            end_time = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            minutes_until_end = (end_time - now).total_seconds() / 60
            
            if minutes_until_end < self.config.min_minutes_until_end:
                continue
            if minutes_until_end > self.config.max_minutes_until_end:
                continue
            
            # 获取 token ID
            clob_token_ids = market.get("clobTokenIds", "[]")
            try:
                token_ids = json.loads(clob_token_ids)
            except:
                continue
            
            if len(token_ids) < 2:
                continue
            
            dip_market = DipArbMarket(
                name=question,
                slug=slug,
                condition_id=market.get("conditionId", ""),
                up_token_id=token_ids[0],
                down_token_id=token_ids[1],
                underlying=underlying,
                duration_minutes=duration,
                end_time=end_time,
            )
            
            results.append(dip_market)
        
        # 按结束时间排序
        results.sort(key=lambda x: x.end_time)
        return results
    
    def _is_crypto_up_down(self, slug: str) -> bool:
        """检查是否是加密货币 UP/DOWN 市场"""
        # 模式: btc-50000-15m, eth-2000-5m, etc
        patterns = [
            r"^btc-\d+-[bm]",      # btc-50000-15m
            r"^eth-\d+-[bm]",      # eth-2000-5m
            r"^sol-\d+-[bm]",      # sol-100-15m
            r"^xrp-\d+-[bm]",      # xrp-0.5-15m
        ]
        import re
        return any(re.match(p, slug.lower()) for p in patterns)
    
    def _parse_underlying_duration(self, slug: str) -> tuple[str, int]:
        """从 slug 解析币种和周期"""
        import re
        
        # btc-50000-15m -> btc, 15
        match = re.match(r"^(btc|eth|sol|xrp)-.+-(\d+)[bm]$", slug.lower())
        if match:
            underlying = match.group(1).upper()
            duration = int(match.group(2))
            return underlying, duration
        
        return "", 0
    
    async def find_best_market(self) -> Optional[DipArbMarket]:
        """找到最佳市场"""
        markets = await self.scan_upcoming_markets()
        
        if not markets:
            return None
        
        # 如果指定了币种，优先选择该币种
        if self.config.coin != "all":
            coin_markets = [m for m in markets if m.underlying.upper() == self.config.coin.upper()]
            if coin_markets:
                return coin_markets[0]
        
        return markets[0]
    
    # =============================================================================
    # 订单簿获取
    # =============================================================================
    
    async def get_orderbook(self, token_id: str) -> dict:
        """获取订单簿"""
        url = f"{CLOB_API}/orderbook"
        params = {"token_id": token_id}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return {"bids": [], "asks": []}
                return await resp.json()
    
    async def get_processed_orderbook(self, up_token_id: str, down_token_id: str) -> dict:
        """获取处理后的订单簿（考虑镜像订单）"""
        up_book = await self.get_orderbook(up_token_id)
        down_book = await self.get_orderbook(down_token_id)
        
        # 计算有效价格
        # Polymarket 订单簿镜像：买入 YES = 卖出 NO
        # 所以需要用有效价格计算
        
        up_asks = up_book.get("asks", [])
        down_asks = down_book.get("asks", [])
        
        return {
            "up_asks": up_asks[:10],    # Top 10 asks
            "down_asks": down_asks[:10],
            "spread": self._calculate_spread(up_asks, down_asks),
        }
    
    def _calculate_spread(self, up_asks: list, down_asks: list) -> dict:
        """计算价差"""
        if not up_asks or not down_asks:
            return {"long_arb_profit": 0, "short_arb_profit": 0}
        
        up_ask = float(up_asks[0][0])  # Best ask
        down_ask = float(down_asks[0][0])
        
        # Long arb: buy UP + buy DOWN -> 成本 = up + down
        total_cost = up_ask + down_ask
        long_arb_profit = max(0, 1 - total_cost)
        
        # Short arb 逻辑类似
        short_arb_profit = max(0, 1 - (up_ask + down_ask))
        
        return {
            "up_ask": up_ask,
            "down_ask": down_ask,
            "total_cost": total_cost,
            "long_arb_profit": long_arb_profit,
            "short_arb_profit": short_arb_profit,
        }
    
    # =============================================================================
    # 信号检测
    # =============================================================================
    
    async def check_for_signals(self, market: DipArbMarket) -> list[DipArbSignal]:
        """检查是否有交易信号"""
        signals = []
        
        # 获取订单簿
        book = await self.get_processed_orderbook(market.up_token_id, market.down_token_id)
        
        if not book["up_asks"] or not book["down_asks"]:
            return signals
        
        up_price = float(book["up_asks"][0][0])
        down_price = float(book["down_asks"][0][0])
        
        # 保存价格历史
        self.price_history.append({
            "timestamp": time.time(),
            "up_ask": up_price,
            "down_ask": down_price,
        })
        
        if len(self.price_history) > self.MAX_HISTORY_LENGTH:
            self.price_history.pop(0)
        
        # 检查是否有 price_to_beat
        if market.price_to_beat == 0:
            return signals
        
        # 计算当前价格相对于 price_to_beat 的变化
        up_change = (up_price - market.price_to_beat) / market.price_to_beat
        down_change = (down_price - market.price_to_beat) / market.price_to_beat
        
        # Leg1: 检测暴跌
        if self.current_round and self.current_round.phase == DipArbPhase.LEG1_PENDING:
            # 已经触发过 Leg1，不能重复
            pass
        else:
            # 检测 UP 侧暴跌
            if up_change < -self.config.dip_threshold:
                signal = DipArbSignal(
                    type="dip",
                    side=DipArbSide.UP,
                    current_price=up_price,
                    target_price=up_price,
                    shares=self._calculate_shares(up_price),
                    token_id=market.up_token_id,
                    round_id=f"{market.condition_id[:8]}_{int(time.time())}",
                )
                signals.append(signal)
            
            # 检测 DOWN 侧暴跌 (UP 涨 = DOWN 跌)
            if down_change < -self.config.dip_threshold:
                signal = DipArbSignal(
                    type="dip",
                    side=DipArbSide.DOWN,
                    current_price=down_price,
                    target_price=down_price,
                    shares=self._calculate_shares(down_price),
                    token_id=market.down_token_id,
                    round_id=f"{market.condition_id[:8]}_{int(time.time())}",
                )
                signals.append(signal)
        
        # Leg2: 检测对冲条件
        if self.current_round and self.current_round.phase == DipArbPhase.LEG1_FILLED:
            # Leg1 完成后，检查是否可以执行 Leg2
            hedge_side = DipArbSide.DOWN if self.current_round.leg1_side == DipArbSide.UP else DipArbSide.UP
            hedge_price = down_price if hedge_side == DipArbSide.DOWN else up_price
            
            # 对冲条件：价格回归或市场结束
            if up_change > -self.config.hedge_threshold or down_change > -self.config.hedge_threshold:
                signal = DipArbSignal(
                    type="hedge",
                    side=hedge_side,
                    current_price=hedge_price,
                    target_price=hedge_price,
                    shares=self.current_round.leg1_shares,
                    token_id=market.down_token_id if hedge_side == DipArbSide.DOWN else market.up_token_id,
                    round_id=self.current_round.round_id,
                )
                signals.append(signal)
        
        return signals
    
    def _calculate_shares(self, price: float, target_amount: float = 10) -> float:
        """计算买入股数"""
        # 确保满足 $1 最低限额
        min_shares = max(1, int(1 / price))
        shares = max(min_shares, int(target_amount / price))
        return float(shares)
    
    # =============================================================================
    # 运行循环
    # =============================================================================
    
    async def start(self, market: DipArbMarket):
        """启动监控"""
        self.is_running = True
        self.stats.start_time = int(time.time() * 1000)
        
        # 创建新轮次
        self.current_round = DipArbRound(
            round_id=f"{market.condition_id[:8]}_{int(time.time())}",
            market=market,
            phase=DipArbPhase.LEG1_PENDING,
            price_to_beat=market.price_to_beat,
        )
        
        print(f"[DipArb] Starting monitor: {market.name}")
        print(f"[DipArb] Underlying: {market.underlying}, Duration: {market.duration_minutes}m")
        print(f"[DipArb] End time: {market.end_time}")
        
        # 主循环
        while self.is_running:
            try:
                # 检查是否超时
                if datetime.now() > market.end_time:
                    print(f"[DipArb] Market ended")
                    break
                
                # 检查信号
                signals = await self.check_for_signals(market)
                
                for signal in signals:
                    print(f"[DipArb] Signal: {signal.type} {signal.side.value} @ {signal.current_price:.4f}")
                    
                    if self.config.auto_execute:
                        await self.execute_signal(signal)
                
                # 等待
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"[DipArb] Error: {e}")
                await asyncio.sleep(5)
        
        self.is_running = False
        self._print_stats()
    
    async def execute_signal(self, signal: DipArbSignal):
        """执行信号"""
        print(f"[DipArb] Executing {signal.type} signal: {signal.side.value}")
        # TODO: 实现实际交易逻辑
        # 这里调用 execution_engine
    
    def _print_stats(self):
        """打印统计信息"""
        print(f"\n[DipArb] === Stats ===")
        print(f"Rounds monitored: {self.stats.rounds_monitored}")
        print(f"Rounds successful: {self.stats.rounds_successful}")
        print(f"Leg1 filled: {self.stats.leg1_filled}")
        print(f"Leg2 filled: {self.stats.leg2_filled}")
        print(f"Total profit: ${self.stats.total_profit:.2f}")


# =============================================================================
# 主函数
# =============================================================================

async def main():
    """主函数"""
    config = DipArbConfig(
        coin="BTC",           # 只监控 BTC
        duration="15m",       # 15分钟周期
        dip_threshold=0.003,  # 3% 跌幅
        auto_execute=False,    # 先不自动执行
        debug=True,
    )
    
    scanner = DipArbScanner(config)
    
    # 找最佳市场
    market = await scanner.find_best_market()
    
    if market:
        print(f"[DipArb] Found market: {market.name}")
        await scanner.start(market)
    else:
        print("[DipArb] No suitable market found")


if __name__ == "__main__":
    asyncio.run(main())
