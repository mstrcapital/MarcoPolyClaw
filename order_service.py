"""
订单服务 (Order Service)
=====================

基于 py_clob_client 的订单管理

功能:
- 限价单 (GTC, GTD)
- 市价单 (FOK, FAK)
- 订单管理 (查询/取消)
- 奖励查询

注意: Polymarket 订单限制:
- 最小股数: 5 股 (MIN_ORDER_SIZE_SHARES)
- 最小价值: $1 USDC (MIN_ORDER_VALUE_USDC)
"""

import asyncio
from dataclasses import dataclass
from typing import Optional
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    OrderArgs,
    MarketOrderArgs,
    CancelOrderParams,
)
from py_clob_client.constants import POLYGON_CHAIN_ID

from config import CLOB_API, WALLET_PRIVATE_KEY, PROXY_WALLET_ADDRESS
from polymarket_client import create_client


# =============================================================================
# 常量
# =============================================================================

# Polymarket 订单限制
MIN_ORDER_SIZE_SHARES = 5      # 最小股数
MIN_ORDER_VALUE_USDC = 1       # 最小价值 $1


# =============================================================================
# 数据模型
# =============================================================================

class Side:
    BUY = "BUY"
    SELL = "SELL"


class OrderType:
    GTC = "GTC"  # Good Till Cancelled
    GTD = "GTD"  # Good Till Date
    FOK = "FOK"  # Fill Or Kill
    FAK = "FAK"  # Fill And Kill


@dataclass
class Order:
    """订单信息"""
    order_id: str
    token_id: str
    side: str
    price: float
    size: float
    filled_size: float
    status: str  # open, filled, cancelled
    created_at: int


@dataclass
class OrderResult:
    """下单结果"""
    success: bool
    order_id: Optional[str] = None
    error_msg: Optional[str] = None
    transaction_hash: Optional[str] = None


@dataclass
class TradeInfo:
    """成交信息"""
    trade_id: str
    token_id: str
    side: str
    price: float
    size: float
    fee: float
    timestamp: int


# =============================================================================
# 订单服务
# =============================================================================

class OrderService:
    """订单管理服务"""
    
    def __init__(self, client: ClobClient = None):
        self.client = client
    
    def _ensure_client(self) -> ClobClient:
        """确保 client 已初始化"""
        if self.client is None:
            self.client = create_client()
        return self.client
    
    # =========================================================================
    # 订单验证
    # =========================================================================
    
    def validate_order(self, size: float, price: float) -> tuple[bool, str]:
        """
        验证订单是否符合 Polymarket 限制
        
        Returns:
            (is_valid, error_message)
        """
        # 检查最小股数
        if size < MIN_ORDER_SIZE_SHARES:
            return False, f"Order size ({size}) is below minimum ({MIN_ORDER_SIZE_SHARES} shares)"
        
        # 检查最小价值
        order_value = size * price
        if order_value < MIN_ORDER_VALUE_USDC:
            return False, f"Order value (${order_value:.2f}) is below minimum (${MIN_ORDER_VALUE_USDC})"
        
        return True, ""
    
    # =========================================================================
    # 限价单
    # =========================================================================
    
    def create_limit_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
        order_type: str = OrderType.GTC,
        expiration: int = None,
    ) -> OrderResult:
        """
        创建限价单
        
        Args:
            token_id: Token ID
            side: BUY 或 SELL
            size: 股数
            price: 价格
            order_type: GTC (永久) 或 GTD (指定时间)
            expiration: GTD 订单的过期时间戳
        
        Returns:
            OrderResult
        """
        client = self._ensure_client()
        
        # 验证订单
        is_valid, error = self.validate_order(size, price)
        if not is_valid:
            return OrderResult(success=False, error_msg=error)
        
        try:
            order_args = OrderArgs(
                token_id=token_id,
                side=side,
                size=str(size),
                price=str(price),
            )
            
            # GTD 订单
            if order_type == OrderType.GTD and expiration:
                order_args.expiration = str(expiration)
            
            # 创建订单
            response = client.create_order(order_args)
            
            if response.get("success"):
                return OrderResult(
                    success=True,
                    order_id=response.get("orderID"),
                    transaction_hash=response.get("txHash"),
                )
            else:
                return OrderResult(
                    success=False,
                    error_msg=response.get("error", "Unknown error"),
                )
        
        except Exception as e:
            return OrderResult(success=False, error_msg=str(e))
    
    def create_limit_order_async(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
        order_type: str = OrderType.GTC,
        expiration: int = None,
    ) -> asyncio.coroutine:
        """异步版本"""
        return asyncio.coroutine(self.create_limit_order)(
            token_id, side, size, price, order_type, expiration
        )
    
    # =========================================================================
    # 市价单
    # =========================================================================
    
    def create_market_order(
        self,
        token_id: str,
        side: str,
        amount: float,
        order_type: str = OrderType.FOK,
    ) -> OrderResult:
        """
        创建市价单
        
        Args:
            token_id: Token ID
            side: BUY 或 SELL
            amount: 金额 (股数或 USDC)
            order_type: FOK (全部成交或取消) 或 FAK (部分成交)
        
        Returns:
            OrderResult
        """
        client = self._ensure_client()
        
        try:
            order_args = MarketOrderArgs(
                token_id=token_id,
                side=side,
                amount=str(amount),
            )
            
            response = client.create_market_order(order_args)
            
            if response.get("success"):
                return OrderResult(
                    success=True,
                    order_id=response.get("orderID"),
                    transaction_hash=response.get("txHash"),
                )
            else:
                return OrderResult(
                    success=False,
                    error_msg=response.get("error", "Unknown error"),
                )
        
        except Exception as e:
            return OrderResult(success=False, error_msg=str(e))
    
    # =========================================================================
    # 订单管理
    # =========================================================================
    
    def get_open_orders(self) -> list[Order]:
        """获取所有未成交订单"""
        client = self._ensure_client()
        
        try:
            orders = client.get_orders()
            return [
                Order(
                    order_id=o.get("orderID"),
                    token_id=o.get("token_id"),
                    side=o.get("side"),
                    price=float(o.get("price", 0)),
                    size=float(o.get("size", 0)),
                    filled_size=float(o.get("size", 0)) - float(o.get("remaining_size", 0)),
                    status=o.get("status", "open"),
                    created_at=int(o.get("created_at", 0)),
                )
                for o in orders
            ]
        except Exception as e:
            print(f"Error getting orders: {e}")
            return []
    
    def cancel_order(self, order_id: str) -> bool:
        """取消单个订单"""
        client = self._ensure_client()
        
        try:
            response = client.cancel_order(order_id)
            return response.get("success", False)
        except Exception as e:
            print(f"Error cancelling order: {e}")
            return False
    
    def cancel_all_orders(self) -> bool:
        """取消所有订单"""
        client = self._ensure_client()
        
        try:
            response = client.cancel_all_orders()
            return response.get("success", False)
        except Exception as e:
            print(f"Error cancelling orders: {e}")
            return False
    
    # =========================================================================
    # 历史成交
    # =========================================================================
    
    def get_fills(self, token_id: str = None) -> list[TradeInfo]:
        """获取成交历史"""
        client = self._ensure_client()
        
        try:
            fills = client.get_fills(token_id) if token_id else client.get_fills()
            return [
                TradeInfo(
                    trade_id=f.get("trade_id"),
                    token_id=f.get("token_id"),
                    side=f.get("side"),
                    price=float(f.get("price", 0)),
                    size=float(f.get("size", 0)),
                    fee=float(f.get("fee", 0)),
                    timestamp=int(f.get("timestamp", 0)),
                )
                for f in fills
            ]
        except Exception as e:
            print(f"Error getting fills: {e}")
            return []


# =============================================================================
# 快速函数
# =============================================================================

def get_order_service() -> OrderService:
    """获取 OrderService 实例"""
    return OrderService()


# =============================================================================
# 示例
# =============================================================================

if __name__ == "__main__":
    service = get_order_service()
    
    print("Order Service")
    print("=" * 40)
    
    # 获取未成交订单
    orders = service.get_open_orders()
    print(f"Open orders: {len(orders)}")
    
    for o in orders[:3]:
        print(f"  {o.order_id}: {o.side} {o.size} @ {o.price}")
