"""
执行层 (Execution Engine)
=======================

功能:
- 交易构造
- 私钥签名
- 下单执行
- 重试机制
- 失败处理

架构:
- TradeExecutor: 交易执行器
- OrderBuilder: 订单构造
- SignatureManager: 签名管理
- RetryPolicy: 重试策略
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from web3 import Web3
from loguru import logger

from config import POLYGON_RPC, GAMMA_API, CLOB_API

# =============================================================================
# 配置
# =============================================================================

# 合约地址
CTF_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8b8982E"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449AA84174"

# 交易配置
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))  # 秒
GAS_LIMIT = int(os.getenv("GAS_LIMIT", "300000"))
GAS_MULTIPLIER = float(os.getenv("GAS_MULTIPLIER", "1.2"))

# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class Order:
    """订单"""
    market_id: str
    question: str
    side: str  # YES or NO
    amount: float  # USD 金额
    price: float  # 价格限制
    
@dataclass
class TradeConfirmation:
    """交易确认"""
    success: bool
    order: Order
    tx_hash: Optional[str]
    error: Optional[str] = None
    filled_amount: float = 0
    average_price: float = 0
    timestamp: datetime = field(default_factory=datetime.now)

# =============================================================================
# 订单构造器
# =============================================================================

class OrderBuilder:
    """订单构造器"""
    
    @staticmethod
    def build_split_order(condition_id: str, amount_usd: float) -> dict:
        """构造 Split 订单 (USDC -> YES + NO)"""
        
        amount_wei = int(amount_usd * 1e6)  # USDC 6位小数
        
        # 构建交易数据
        tx_data = {
            "to": CTF_ADDRESS,
            "value": 0,
            "data": {
                "method": "splitPosition",
                "params": {
                    "collateral": USDC_ADDRESS,
                    "parentCollectionId": "0x" + "00" * 32,
                    "conditionId": condition_id,
                    "partition": [1, 2],  # YES, NO
                    "amount": amount_wei
                }
            }
        }
        
        return tx_data
    
    @staticmethod
    def build_clob_order(token_id: str, side: str, amount: float, price: float) -> dict:
        """构造 CLOB 订单"""
        
        # 数量 = 金额 / 价格
        quantity = int(amount / price * 1e6)  # 代币 6 位小数
        
        order = {
            "token_id": token_id,
            "side": side,  # BUY or SELL
            "quantity": quantity,
            "price": price
        }
        
        return order

# =============================================================================
# 签名管理器
# =============================================================================

class SignatureManager:
    """签名管理器"""
    
    def __init__(self, private_key: str):
        self.w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))
        self.account = self.w3.eth.account.from_key(private_key)
        self.address = self.account.address
        
        logger.info(f"签名管理器初始化: {self.address}")
    
    def sign_transaction(self, tx: dict) -> str:
        """签名交易"""
        # 构建交易
        tx["from"] = self.address
        tx["nonce"] = self.w3.eth.get_transaction_count(self.address)
        tx["gas"] = int(tx.get("gas", GAS_LIMIT) * GAS_MULTIPLIER)
        tx["gasPrice"] = self.w3.eth.gas_price
        tx["chainId"] = 137  # Polygon
        
        # 签名
        signed = self.account.sign_transaction(tx)
        
        # 发送
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        
        return self.w3.to_hex(tx_hash)
    
    def sign_and_send(self, tx: dict) -> tuple[str, bool]:
        """签名并发送交易"""
        try:
            tx_hash = self.sign_transaction(tx)
            return tx_hash, True
        except Exception as e:
            logger.error(f"签名/发送失败: {e}")
            return "", False

# =============================================================================
# 交易执行器
# =============================================================================

class TradeExecutor:
    """交易执行器"""
    
    def __init__(self, private_key: str):
        self.w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))
        self.signer = SignatureManager(private_key)
        self.order_builder = OrderBuilder()
        
        # CTF 合约
        self.ctf_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(CTF_ADDRESS),
            abi=self._get_ctf_abi()
        )
        
        logger.info("交易执行器初始化完成")
    
    async def execute_split(self, condition_id: str, amount: float) -> TradeConfirmation:
        """执行 Split (买入 YES + NO)"""
        
        order = Order(
            market_id=condition_id,
            question="",
            side="BOTH",
            amount=amount,
            price=0
        )
        
        # 构建交易
        amount_wei = int(amount * 1e6)
        
        try:
            tx = self.ctf_contract.functions.splitPosition(
                Web3.to_checksum_address(USDC_ADDRESS),
                bytes(32),  # parentCollectionId
                bytes.fromhex(condition_id[2:] if condition_id.startswith("0x") else condition_id),
                [1, 2],  # partition
                amount_wei
            ).build_transaction({
                "from": self.signer.address,
                "nonce": self.w3.eth.get_transaction_count(self.signer.address),
                "gas": GAS_LIMIT,
                "gasPrice": self.w3.eth.gas_price,
                "chainId": 137
            })
            
            # 签名并发送
            tx_hash, success = self.signer.sign_and_send(tx)
            
            if success:
                # 等待确认
                receipt = self._wait_for_receipt(tx_hash)
                
                return TradeConfirmation(
                    success=receipt["status"] == 1,
                    order=order,
                    tx_hash=tx_hash,
                    filled_amount=amount if receipt["status"] == 1 else 0
                )
            else:
                return TradeConfirmation(
                    success=False,
                    order=order,
                    tx_hash="",
                    error="签名/发送失败"
                )
                
        except Exception as e:
            return TradeConfirmation(
                success=False,
                order=order,
                tx_hash="",
                error=str(e)
            )
    
    async def execute_clob_order(self, token_id: str, side: str, amount: float, price: float) -> dict:
        """执行 CLOB 订单"""
        
        try:
            import aiohttp
            
            # 计算数量
            quantity = int(amount / price * 1e6)
            
            # 构建订单
            order_data = {
                "token_id": token_id,
                "side": side.upper(),
                "quantity": str(quantity),
                "price": str(price)
            }
            
            # 发送订单
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"{CLOB_API}/orders",
                    json=order_data
                )
                
                if resp.status == 200:
                    result = await resp.json()
                    return {
                        "success": True,
                        "order_id": result.get("orderID"),
                        "filled": result.get("filled", 0)
                    }
                else:
                    error = await resp.text()
                    return {
                        "success": False,
                        "error": error
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def execute_buy_and_sell(self, condition_id: str, market_id: str, 
                                   yes_token: str, no_token: str,
                                   amount: float, yes_price: float, no_price: float) -> dict:
        """执行买入 + 卖出 (套利)"""
        
        results = {
            "split": None,
            "sell": None,
            "success": False
        }
        
        # 1. Split USDC -> YES + NO
        split_result = await self.execute_split(condition_id, amount)
        results["split"] = split_result
        
        if not split_result.success:
            results["error"] = split_result.error
            return results
        
        # 2. 卖出不想要的一侧
        # 假设买入 YES，卖出 NO
        if yes_price > no_price:
            # YES 更贵，卖出 NO
            sell_token = no_token
            sell_price = no_price
            sell_side = "SELL"
        else:
            # NO 更贵，卖出 YES
            sell_token = yes_token
            sell_price = yes_price
            sell_side = "SELL"
        
        # 卖出
        sell_result = await self.execute_clob_order(
            sell_token, sell_side, amount, sell_price
        )
        results["sell"] = sell_result
        
        results["success"] = sell_result.get("success", False)
        
        return results
    
    def _wait_for_receipt(self, tx_hash: str, timeout: int = 60) -> dict:
        """等待交易收据"""
        start = datetime.now()
        
        while (datetime.now() - start).seconds < timeout:
            try:
                receipt = self.w3.eth.get_transaction_receipt(tx_hash)
                if receipt:
                    return receipt
            except:
                pass
            
            asyncio.sleep(2)
        
        return {"status": 0}
    
    def _get_ctf_abi(self) -> list:
        """获取 CTF 合约 ABI (简化版)"""
        return [
            {
                "inputs": [
                    {"name": "collateral", "type": "address"},
                    {"name": "parentCollectionId", "type": "bytes"},
                    {"name": "conditionId", "type": "bytes"},
                    {"name": "partition", "type": "uint256[]"},
                    {"name": "amount", "type": "uint256"}
                ],
                "name": "splitPosition",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]

# =============================================================================
# 重试策略
# =============================================================================

class RetryPolicy:
    """重试策略"""
    
    def __init__(self, max_retries: int = MAX_RETRIES, base_delay: int = RETRY_DELAY):
        self.max_retries = max_retries
        self.base_delay = base_delay
    
    async def execute(self, func, *args, **kwargs):
        """执行带重试"""
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                
                # 检查结果
                if isinstance(result, dict) and not result.get("success", True):
                    last_error = result.get("error", "Unknown error")
                    logger.warning(f"执行失败 (尝试 {attempt + 1}): {last_error}")
                else:
                    return result
                    
            except Exception as e:
                last_error = str(e)
                logger.warning(f"执行异常 (尝试 {attempt + 1}): {e}")
            
            # 重试延迟 (指数退避)
            if attempt < self.max_retries:
                delay = self.base_delay * (2 ** attempt)
                logger.info(f"等待 {delay}秒后重试...")
                await asyncio.sleep(delay)
        
        return {
            "success": False,
            "error": f"重试 {self.max_retries + 1} 次后仍失败: {last_error}"
        }

# =============================================================================
# 示例
# =============================================================================

if __name__ == "__main__":
    # 测试
    print("Execution Engine initialized")
    print(f"CTF: {CTF_ADDRESS}")
    print(f"USDC: {USDC_ADDRESS}")
