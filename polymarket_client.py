"""
Polymarket Client 初始化工具
基于 py_clob_client

用法:
    from polymarket_client import create_client
    
    client = create_client(
        private_key="0x...",      # Reveal 导出的 owner 私钥
        proxy_address="0x...",   # Proxy wallet 地址
    )
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载配置
CONFIG_DIR = Path(__file__).parent / "config"
load_dotenv(CONFIG_DIR / "wallet.env")

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON

from config import (
    WALLET_PRIVATE_KEY,
    PROXY_WALLET_ADDRESS,
    SIGNATURE_TYPE,
    CLOB_API_KEY,
)

# API Host
CLOB_HOST = "https://clob.polymarket.com"


def create_client(
    private_key: str = None,
    proxy_address: str = None,
    signature_type: int = None,
) -> ClobClient:
    """
    创建 Polymarket CLOB Client
    
    Args:
        private_key: Reveal 导出的 owner 私钥
        proxy_address: Proxy wallet 地址
        signature_type: 签名类型 (1 = POLY_PROXY)
    
    Returns:
        ClobClient 实例
    """
    # 使用参数或配置
    private_key = private_key or WALLET_PRIVATE_KEY
    proxy_address = proxy_address or PROXY_WALLET_ADDRESS
    signature_type = signature_type or SIGNATURE_TYPE
    
    if not private_key:
        raise ValueError("Private key is required")
    
    if not proxy_address:
        raise ValueError("Proxy wallet address is required")
    
    client = ClobClient(
        host=CLOB_HOST,
        key=private_key,           # owner 私钥，用于签名
        chain_id=POLYGON,         # Polygon 主网 (137)
        signature_type=signature_type,  # 2 = POLY_GNOSIS (邮箱)
        funder=proxy_address,      # 必须填 proxy 地址
    )
    
    return client


def get_client() -> ClobClient:
    """获取已配置的 Client (需要环境变量)"""
    return create_client()


# =============================================================================
# 快速示例
# =============================================================================

if __name__ == "__main__":
    # 示例用法
    print("Polymarket Client Helper")
    print("=" * 40)
    print("需要配置环境变量:")
    print("  WALLET_PRIVATE_KEY=0x...")
    print("  PROXY_WALLET_ADDRESS=0x...")
    print()
    print("或直接调用:")
    print('  client = create_client("0x...", "0x...")')
