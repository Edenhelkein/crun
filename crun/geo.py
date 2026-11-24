"""几何工具：距离、方位、偏移、geohash。全部纯标准库。"""
import math

R_EARTH = 6371008.8
_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def haversine(a, b):
    """两点 (lat, lon) 球面距离，米。"""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R_EARTH * math.asin(min(1.0, math.sqrt(h)))


def bearing(a, b):
    """a -> b 方位角，度。"""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def offset(lat, lon, dn_m, de_m):
    """以米为单位向正北 dn、正东 de 偏移，返回新 (lat, lon)。"""
    dlat = dn_m / 111320.0
    dlon = de_m / (111320.0 * max(0.05, math.cos(math.radians(lat))))
    return lat + dlat, lon + dlon


def geohash_encode(lat, lon, precision=6):
    lat_i, lon_i = [-90.0, 90.0], [-180.0, 180.0]
    chars, even, bit, ch = [], True, 0, 0
    while len(chars) < precision:
        if even:
            mid = (lon_i[0] + lon_i[1]) / 2
            if lon >= mid:
                ch = (ch << 1) | 1
                lon_i[0] = mid
            else:
                ch <<= 1
                lon_i[1] = mid
        else:
            mid = (lat_i[0] + lat_i[1]) / 2
            if lat >= mid:
                ch = (ch << 1) | 1
                lat_i[0] = mid
            else:
                ch <<= 1
                lat_i[1] = mid
        even = not even
        bit += 1
        if bit == 5:
            chars.append(_B32[ch])
            ch, bit = 0, 0
    return "".join(chars)


def centroid(pts):
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)
