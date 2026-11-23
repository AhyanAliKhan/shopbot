"""Demo catalog for a small seller. Loaded once into an empty database."""
from .db import Coupon, Product

PRODUCTS = [
    # id, name, category, price, stock, tags, rating, emoji, description
    ("P001", "Cloudstep Running Shoes", "footwear", 79.0, 25, "running,sport,mesh,lightweight", 4.6, "👟", "Lightweight mesh running shoes with a cushioned sole. Sizes 38-46."),
    ("P002", "Trailhound Hiking Boots", "footwear", 129.0, 12, "hiking,waterproof,leather,outdoor", 4.7, "🥾", "Waterproof leather hiking boots with ankle support. Sizes 39-46."),
    ("P003", "Everyday Canvas Sneakers", "footwear", 45.0, 40, "casual,canvas,vegan", 4.3, "👟", "Vegan canvas sneakers for daily wear. Sizes 36-45."),
    ("P004", "Cozy Wool Slippers", "footwear", 32.0, 18, "wool,indoor,warm", 4.5, "🧦", "Warm merino wool slippers with a rubber sole."),
    ("P005", "Organic Cotton Tee", "apparel", 22.0, 60, "cotton,organic,basic,vegan", 4.4, "👕", "Soft organic cotton t-shirt. Sizes XS-XXL, 6 colours."),
    ("P006", "Merino Wool Sweater", "apparel", 89.0, 15, "wool,winter,warm", 4.8, "🧶", "Fine-knit merino sweater, breathable and warm. Sizes S-XL."),
    ("P007", "Rainshield Jacket", "apparel", 110.0, 10, "rain,waterproof,outdoor,vegan", 4.6, "🧥", "Packable waterproof jacket with taped seams. Sizes S-XXL."),
    ("P008", "Flex Yoga Leggings", "apparel", 38.0, 30, "yoga,sport,stretch,vegan", 4.5, "🩱", "High-waist stretch leggings with a phone pocket. Sizes XS-XL."),
    ("P009", "Linen Summer Shirt", "apparel", 49.0, 22, "linen,summer,breathable", 4.2, "👔", "Relaxed-fit linen shirt for hot days. Sizes S-XL."),
    ("P010", "Leather Everyday Wallet", "accessories", 35.0, 35, "leather,gift,slim", 4.5, "👛", "Slim full-grain leather wallet with 6 card slots."),
    ("P011", "Canvas Tote Bag", "accessories", 18.0, 50, "canvas,eco,vegan,gift", 4.4, "👜", "Heavy-duty canvas tote with inner pocket."),
    ("P012", "Polarized Sunglasses", "accessories", 55.0, 20, "summer,uv,outdoor", 4.3, "🕶️", "UV400 polarized sunglasses with a hard case."),
    ("P013", "Steel Water Bottle 750ml", "accessories", 24.0, 45, "sport,eco,insulated,gift", 4.7, "🧴", "Double-wall insulated bottle, cold 24h / hot 12h."),
    ("P014", "Travel Backpack 30L", "accessories", 95.0, 9, "travel,laptop,waterproof", 4.6, "🎒", "30L backpack with padded 16-inch laptop sleeve."),
    ("P015", "Soy Wax Candle - Cedar", "home", 19.0, 40, "candle,gift,vegan,scented", 4.6, "🕯️", "Hand-poured soy candle, 45-hour burn, cedar and amber."),
    ("P016", "Ceramic Pour-Over Set", "home", 42.0, 14, "coffee,ceramic,gift,kitchen", 4.7, "☕", "Ceramic dripper, carafe and 2 cups."),
    ("P017", "Bamboo Cutting Board", "home", 27.0, 28, "kitchen,bamboo,eco", 4.4, "🪵", "Large bamboo board with juice groove."),
    ("P018", "Linen Throw Blanket", "home", 64.0, 11, "linen,bedroom,cozy", 4.5, "🛋️", "Stonewashed linen throw, 130x170 cm."),
    ("P019", "Natural Face Moisturizer", "beauty", 29.0, 33, "skincare,vegan,fragrance-free", 4.4, "🧴", "Fragrance-free daily moisturizer for sensitive skin."),
    ("P020", "Herbal Shampoo Bar", "beauty", 12.0, 55, "haircare,vegan,plastic-free,eco", 4.3, "🧼", "Plastic-free shampoo bar, ~80 washes."),
    ("P021", "Wireless Earbuds Pro", "electronics", 69.0, 16, "audio,bluetooth,sport", 4.4, "🎧", "Bluetooth 5.3 earbuds, 30h battery with case, sweat-resistant."),
    ("P022", "Portable Power Bank 10000mAh", "electronics", 34.0, 26, "travel,charging,usb-c", 4.5, "🔋", "Slim 10000mAh power bank with USB-C fast charge."),
    ("P023", "Smart Fitness Band", "electronics", 49.0, 0, "fitness,sport,tracker", 4.1, "⌚", "Heart-rate and sleep tracking band. 7-day battery."),
    ("P024", "Desk LED Lamp", "electronics", 39.0, 19, "home office,light,usb", 4.6, "💡", "Dimmable LED desk lamp with USB charging port."),
]

COUPONS = [("WELCOME10", 10, 0), ("BLOOM20", 20, 100), ("FREESHIP", 0, 0)]


def seed(s) -> None:
    for pid, name, cat, price, stock, tags, rating, emoji, desc in PRODUCTS:
        s.add(Product(id=pid, name=name, category=cat, price=price, stock=stock, tags=tags,
                      rating=rating, image=emoji, description=desc))
    for code, pct, min_sub in COUPONS:
        s.add(Coupon(code=code, percent_off=pct, min_subtotal=min_sub))
