import math

# Raio médio da Terra, em km. A fórmula de haversine trata a Terra como
# esfera; o erro (até ~0,5%) é irrelevante perto do corte de 900 km/h.
EARTH_RADIUS_KM = 6371.0


def haversine_km(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    """A distância em linha reta, sobre a superfície da Terra, entre dois pontos."""
    phi_a = math.radians(latitude_a)
    phi_b = math.radians(latitude_b)
    delta_phi = math.radians(latitude_b - latitude_a)
    delta_lambda = math.radians(longitude_b - longitude_a)

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2

    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
