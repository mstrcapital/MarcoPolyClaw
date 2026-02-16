"""
风控层 (Risk Control Layer)
===========================

功能:
- 单市场敞口限制
- 资金分配管理
- 最大回撤检测
- 仓位净额化

仓位管理:
- 每个市场最大敞口 ≤ 总资金 5%
- 连续亏损自动停机
- 净额计算避免重复对冲
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional
from loguru import logger

# =============================================================================
# 配置
# =============================================================================

# 敞口限制
MAX_EXPOSURE_PCT = float(os.getenv("MAX_EXPOSURE_PCT", "0.05"))  # 5%
MAX_DRAWDOWN_PCT = float(os.getenv("MAX_DRAWDOWN_PCT", "0.10"))  # 10%

# 交易限制
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "5"))  # 5次连亏停机

# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class Position:
    """仓位"""
    market_id: str
    side: str  # YES or NO
    size: float  # 美元金额
    entry_price: float
    current_price: float = 0
    opened_at: datetime = field(default_factory=datetime.now)
    
    @property
    def pnl(self) -> float:
        """盈亏"""
        if self.side == "YES":
            return (self.current_price - self.entry_price) * self.size
        else:
            return (self.entry_price - self.current_price) * self.size
    
    @property
    def exposure(self) -> float口金额"""
        return abs(self.size)

@dataclass
class Account:
    """账户"""
   :
        """敞 address: str
    balance: float  # 可用资金
    positions: list[Position] = field(default_factory=list)
    total_pnl: float = 0
    consecutive_losses: int = 0
    
    @property
    def total_exposure(self) -> float:
        """总敞口"""
        return sum(p.exposure for p in self.positions)
    
    @property
    def max_exposure(self) -> float:
        """最大允许敞口"""
        return self.balance * MAX_EXPOSURE_PCT
    
    @property
    def drawdown_pct(self) -> float:
        """回撤百分比"""
        if self.balance == 0:
            return 0
        initial = self.balance + abs(self.total_pnl)
        if initial == 0:
            return 0
        return abs(self.total_pnl) / initial
    
    @property
    def is_stopped(self) -> bool:
        """是否应该停机"""
        return (
            self.drawdown_pct >= MAX_DRAWDOWN_PCT or
            self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES
        )

# =============================================================================
# 风控引擎
# =============================================================================

class RiskControlEngine:
    """风控引擎"""
    
    def __init__(self, initial_balance: float):
        self.initial_balance = initial_balance
        self.account = Account(
            address="",
            balance=initial_balance
        )
        self._trade_history: list[dict] = []
    
    def set_address(self, address: str):
        """设置钱包地址"""
        self.account.address = address
    
    def can_open_position(self, market_id: str, size: float) -> tuple[bool, str]:
        """检查是否可以开仓"""
        
        # 1. 检查总敞口
        new_exposure = self.account.total_exposure + size
        
        if new_exposure > self.account.max_exposure:
            return False, f"超出最大敞口: ${new_exposure:.2f} > ${self.account.max_exposure:.2f}"
        
        # 2. 检查单市场敞口
        market_exposure = sum(
            p.exposure for p in self.account.positions if p.market_id == market_id
        )
        
        if market_exposure + size > self.account.max_exposure:
            return False, f"单市场超限: ${market_exposure + size:.2f}"
        
        # 3. 检查停机状态
        if self.account.is_stopped:
            return False, f"账户已停机 (回撤: {self.account.drawdown_pct*100:.1f}% / 连亏: {self.account.consecutive_losses})"
        
        return True, "OK"
    
    def open_position(self, market_id: str, side: str, size: float, price: float) -> bool:
        """开仓"""
        
        # 检查
        can_trade, reason = self.can_open_position(market_id, size)
        if not can_trade:
            logger.warning(f"❌ 无法开仓: {reason}")
            return False
        
        # 创建仓位
        position = Position(
            market_id=market_id,
            side=side,
            size=size,
            entry_price=price,
            current_price=price
        )
        
        self.account.positions.append(position)
        
        # 冻结资金
        self.account.balance -= size
        
        logger.info(f"✅ 开仓: {side} {market_id[:20]}... ${size} @ ${price}")
        
        return True
    
    def close_position(self, market_id: str, price: float) -> float:
        """平仓"""
        
        # 查找仓位
        position = None
        for p in self.account.positions:
            if p.market_id == market_id:
                position = p
                break
        
        if not position:
            logger.warning(f"❌ 无仓位: {market_id}")
            return 0
        
        # 更新价格
        position.current_price = price
        
        # 计算盈亏
        pnl = position.pnl
        
        # 更新账户
        self.account.positions.remove(position)
        self.account.balance += position.size  # 返还本金
        self.account.balance += pnl  # 加上盈亏
        self.account.total_pnl += pnl
        
        # 更新连亏计数
        if pnl < 0:
            self.account.consecutive_losses += 1
        else:
            self.account.consecutive_losses = 0
        
        # 记录历史
        self._trade_history.append({
            "market_id": market_id,
            "side": position.side,
            "size": position.size,
            "entry_price": position.entry_price,
            "exit_price": price,
            "pnl": pnl,
            "timestamp": datetime.now().isoformat()
        })
        
        logger.info(f"💰 平仓: {market_id[:20]}... PnL: ${pnl:.2f}")
        
        return pnl
    
    def update_prices(self, prices: Dict[str, float]):
        """更新当前价格"""
        for position in self.account.positions:
            if position.market_id in prices:
                position.current_price = prices[position.market_id]
        
        # 更新账户总盈亏
        self.account.total_pnl = sum(p.pnl for p in self.account.positions)
    
    def get_net_position(self, market_id: str) -> Optional[Position]:
        """获取净额仓位"""
        for p in self.account.positions:
            if p.market_id == market_id:
                return p
        return None
    
    def get_all_positions(self) -> list[Position]:
        """获取所有仓位"""
        return self.account.positions
    
    def get_account_status(self) -> dict:
        """获取账户状态"""
        return {
            "balance": self.account.balance,
            "total_pnl": self.account.total_pnl,
            "drawdown_pct": self.account.drawdown_pct * 100,
            "total_exposure": self.account.total_exposure,
            "max_exposure": self.account.max_exposure,
            "positions_count": len(self.account.positions),
            "consecutive_losses": self.account.consecutive_losses,
            "is_stopped": self.account.is_stopped,
        }

# =============================================================================
# 资金分配器
# =============================================================================

class FundAllocator:
    """资金分配器"""
    
    def __init__(self, total_balance: float, num_accounts: int = 1):
        self.total_balance = total_balance
        self.num_accounts = num_accounts
    
    def allocate(self, account_idx: int = 0) -> float:
        """分配资金"""
        if self.num_accounts == 1:
            return self.total_balance
        
        # 按比例分配
        return self.total_balance / self.num_accounts
    
    def adjust_for_exposure(self, amount: float, current_exposure: float, max_exposure: float) -> float:
        """根据敞口调整金额"""
        available = max_exposure - current_exposure
        return min(amount, available)

# =============================================================================
# 示例
# =============================================================================

if __name__ == "__main__":
    # 创建风控引擎
    engine = RiskControlEngine(initial_balance=10000)
    engine.set_address("0x123...")
    
    # 检查是否可以开仓
    can_trade, reason = engine.can_open_position("market_1", 500)
    print(f"Can open: {can_trade} - {reason}")
    
    # 开仓
    engine.open_position("market_1", "YES", 500, 0.90)
    
    # 更新价格
    engine.update_prices({"market_1": 0.95})
    
    # 平仓
    pnl = engine.close_position("market_1", 0.95)
    print(f"PnL: ${pnl:.2f}")
    
    # 账户状态
    status = engine.get_account_status()
    print(f"\n账户状态:")
    print(f"  余额: ${status['balance']:.2f}")
    print(f"  总PnL: ${status['total_pnl']:.2f}")
    print(f"  回撤: {status['drawdown_pct']:.1f}%")
    print(f"  敞口: ${status['total_exposure']:.2f} / ${status['max_exposure']:.2f}")
    print(f"  停机: {status['is_stopped']}")
