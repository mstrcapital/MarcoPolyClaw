"""
配置管理模块
统一管理扫描器和钱包配置
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 配置目录
CONFIG_DIR = Path(__file__).parent

# 加载配置
def load_config():
    """加载所有配置"""
    # 扫描器配置
    scanner_env = CONFIG_DIR / "scanner.env"
    if scanner_env.exists():
        load_dotenv(scanner_env)
    
    # 钱包配置
    wallet_env = CONFIG_DIR / "wallet.env"
    if wallet_env.exists():
        load_dotenv(wallet_env)

# 加载配置
load_config()

# =============================================================================
# API 配置
# =============================================================================

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# =============================================================================
# 扫描器配置
# =============================================================================

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "300"))
TAGS = os.getenv("POLYMARKET_TAGS", "crypto,bitcoin").split(",")
MIN_LIQUIDITY = float(os.getenv("MIN_LIQUIDITY", "10000"))
MIN_VOLUME = float(os.getenv("MIN_VOLUME", "5000"))
ARB_THRESHOLD = float(os.getenv("ARB_THRESHOLD", "0.01"))
HEDGE_MIN_COVERAGE = float(os.getenv("HEDGE_MIN_COVERAGE", "0.85"))
DB_PATH = os.getenv("DB_PATH", "scanner_state.db")
POSITIONS_FILE = os.getenv("POSITIONS_FILE", "positions.json")

# =============================================================================
# 钱包配置
# =============================================================================

WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")
POLYGON_RPC = os.getenv("POLYGON_RPC", "https://polygon-mainnet.core.chainstack.com/3d54e0ba6084dca5b1d25d10b300c738")
CLOB_API_KEY = os.getenv("CLOB_API_KEY", "")

# Proxy Wallet 配置 (py_clob_client)
PROXY_WALLET_ADDRESS = os.getenv("PROXY_WALLET_ADDRESS", "")  # Proxy wallet 地址
SIGNATURE_TYPE = int(os.getenv("SIGNATURE_TYPE", "1"))  # 1 = POLY_PROXY (邮箱/Magic登录)

# 跟单配置
MONITORED_WALLETS = os.getenv("MONITORED_WALLETS", "").split(",") if os.getenv("MONITORED_WALLETS") else []
COPY_TRADE_DELAY_MS = int(os.getenv("COPY_TRADE_DELAY_MS", "500"))
SLIPPAGE_TOLERANCE = float(os.getenv("SLIPPAGE_TOLERANCE", "0.02"))

# Polygons
POLYGON_RPC = os.getenv("POLYGON_RPC", "https://polygon-mainnet.core.chainstack.com/3d54e0ba6084dca5b1d25d10b300c738")

# LLM 配置
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# =============================================================================
# 工具函数
# =============================================================================

def get_wallet_address() -> str:
    """从私钥获取钱包地址"""
    if not WALLET_PRIVATE_KEY:
        return ""
    from web3 import Web3
    w3 = Web3()
    acct = w3.eth.account.from_key(WALLET_PRIVATE_KEY)
    return acct.address

def has_wallet() -> bool:
    """是否已配置钱包"""
    return bool(WALLET_PRIVATE_KEY)

def has_llm() -> bool:
    """是否已配置 LLM"""
    return bool(OPENROUTER_API_KEY)

def has_copy_trader() -> bool:
    """是否已配置跟单"""
    return has_wallet() and bool(MONITORED_WALLETS)
