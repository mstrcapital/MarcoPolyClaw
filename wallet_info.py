# Top 10 跟单钱包 (v1.2)
WALLET_INFO={
    "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d": {"username": "gabagool22", "pnl": "$866K"},
    "0xe9c6312464b52aa3eff13d822b003282075995c9": {"username": "kingofcoinflips", "pnl": "$508K"},
    "0x4ffe49ba2a4cae123536a8af4fda48faeb609f71": {"username": "planktonXD", "pnl": "$106K"},
    "0xd0bde12c58772999c61c2b8e0d31ba608c52a5d6": {"username": "Demphu.finite", "pnl": "$91.6K"},
    "0x70ec235a31eb35f243e2618d6ea3b5b8962bbb5d": {"username": "vague-sourdough", "pnl": "$59.9K"},
    "0x61276aba49117fd9299707d5d573652949d5c977": {"username": "MuseumOfBees", "pnl": "$60.9K"},
    "0x4460bf2c0aa59db412a6493c2c08970797b62970": {"username": "5min_PVP", "pnl": "$87K"},
    "0xc3e47dd79346216a72d1634fc8ed13d20658e7f9": {"username": "SpotTheAnamoly", "pnl": "N/A"},
    "0x594edb9112f526fa6a80b8f858a6379c8a2c1c11": {"username": "WeatherKing", "pnl": "$30K"},
    "0x36ae97e6d0e5d3624a1ac070dce1f1b0c26d1a49": {"username": "mqog1m", "pnl": "$15.5K"},
}

def get_wallet_info(wallet):
    """获取钱包信息"""
    # 尝试完整匹配
    w = wallet.lower()
    if w in WALLET_INFO:
        return WALLET_INFO[w]
    
    # 尝试前缀匹配
    for addr, info in WALLET_INFO.items():
        if addr.startswith(w[:10].lower()):
            return info
    
    return {"username": "Unknown", "pnl": "N/A"}

def get_profile_link(wallet):
    """获取Profile链接"""
    info = get_wallet_info(wallet)
    username = info.get("username", "")
    if username and username != "Unknown":
        return f"https://polymarket.com/@{username}"
    return f"https://polymarket.com/profile/{wallet}"
