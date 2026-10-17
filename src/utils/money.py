def format_brl(amount_in_cents: int) -> str:
    """15000 → "R$ 150,00". Só para mensagens: o valor de verdade viaja em centavos."""
    reais, cents = divmod(amount_in_cents, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{cents:02d}"
