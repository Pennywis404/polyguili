"""
Calcul exact des fees Polymarket.
Source officielle : https://docs.polymarket.com/trading/fees

Le fee est un TAKER fee, paye a l'entree (achat).
Collecte en shares sur les buy orders (tu recois moins de shares).
PAS de fee sur le payout a la resolution.
Arrondi a 4 decimales, minimum 0.0001 USDC.
"""

FEE_PARAMS: dict[str, dict] = {
    "crypto": {"fee_rate": 0.25, "exponent": 2},
    "sports": {"fee_rate": 0.0175, "exponent": 1},
}


def calculate_fee(num_shares: float, price: float, market_type: str = "crypto") -> float:
    """Calcule le taker fee exact en USDC."""
    if price <= 0.0 or price >= 1.0 or num_shares <= 0.0:
        return 0.0
    params = FEE_PARAMS[market_type]
    fee = num_shares * price * params["fee_rate"] * (price * (1 - price)) ** params["exponent"]
    fee = round(fee, 4)
    if 0 < fee < 0.0001:
        fee = 0.0001
    return fee


def effective_fee_rate(price: float, market_type: str = "crypto") -> float:
    """Taux de fee effectif en pourcentage pour un prix donne."""
    if price <= 0.0 or price >= 1.0:
        return 0.0
    params = FEE_PARAMS[market_type]
    return params["fee_rate"] * (price * (1 - price)) ** params["exponent"]


def shares_after_fee(amount_usdc: float, price: float, market_type: str = "crypto") -> float:
    """
    Nombre reel de shares recues apres fee.
    Le fee est collecte en shares sur les buy orders.
    """
    if price <= 0.0 or price >= 1.0 or amount_usdc <= 0.0:
        return 0.0
    gross_shares = amount_usdc / price
    fee_usdc = calculate_fee(gross_shares, price, market_type)
    fee_shares = fee_usdc / price
    return gross_shares - fee_shares


def arbitrage_profit(p1: float, p2: float, capital: float, market_type: str = "crypto") -> dict:
    """
    Calcul complet du profit d'arbitrage temporel.

    Args:
        p1: prix d'achat de la leg 1
        p2: prix d'achat de la leg 2
        capital: capital total en USDC

    Returns:
        dict avec tous les details du trade
    """
    s1 = capital * p1 / (p1 + p2)
    s2 = capital * p2 / (p1 + p2)

    gross_shares = capital / (p1 + p2)

    fee1 = calculate_fee(gross_shares, p1, market_type)
    fee2 = calculate_fee(gross_shares, p2, market_type)

    real_shares_1 = gross_shares - (fee1 / p1)
    real_shares_2 = gross_shares - (fee2 / p2)

    payout_if_side1_wins = real_shares_1 * 1.0
    payout_if_side2_wins = real_shares_2 * 1.0

    worst_payout = min(payout_if_side1_wins, payout_if_side2_wins)
    best_payout = max(payout_if_side1_wins, payout_if_side2_wins)

    return {
        "p1": p1,
        "p2": p2,
        "combined_cost": p1 + p2,
        "capital": capital,
        "stake_leg1": round(s1, 4),
        "stake_leg2": round(s2, 4),
        "gross_shares": round(gross_shares, 4),
        "fee_leg1": fee1,
        "fee_leg2": fee2,
        "total_fees": round(fee1 + fee2, 4),
        "gross_profit": round(gross_shares - capital, 4),
        "worst_case_profit": round(worst_payout - capital, 4),
        "best_case_profit": round(best_payout - capital, 4),
        "worst_case_roi": round((worst_payout - capital) / capital * 100, 4),
        "is_profitable": worst_payout > capital,
    }
