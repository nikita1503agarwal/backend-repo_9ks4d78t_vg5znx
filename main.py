import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Literal, Dict, Any

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import MenuItem, Order, OrderItem, Coupon, Offer, User, DeliveryAddress

app = FastAPI(title="Pakkhtun Biryani API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------- Utilities ---------
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid objectid")
        return ObjectId(v)

def serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    doc = dict(doc)
    _id = doc.get("_id")
    if isinstance(_id, ObjectId):
        doc["id"] = str(_id)
        del doc["_id"]
    # convert datetimes to isoformat
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc

# --------- Health/Test ---------
@app.get("/")
def read_root():
    return {"message": "Pakkhtun Biryani API running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()[:10]
            response["database"] = "✅ Connected & Working"
    except Exception as e:
        response["database"] = f"⚠️ Error: {str(e)[:80]}"
    return response

# --------- Auth (OTP - simulated) ---------
class OtpRequest(BaseModel):
    phone: str

class OtpVerify(BaseModel):
    phone: str
    code: str

@app.post("/auth/otp/request")
def request_otp(payload: OtpRequest):
    code = "1234"  # Simulated OTP for demo
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    create_document("otp", {"phone": payload.phone, "code": code, "expires_at": expires_at, "verified": False})
    return {"success": True, "message": "OTP sent (demo uses 1234)"}

@app.post("/auth/otp/verify")
def verify_otp(payload: OtpVerify):
    rec = db["otp"].find_one({"phone": payload.phone}, sort=[("created_at", -1)])
    if not rec or rec.get("code") != payload.code:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    if rec.get("expires_at") and rec["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="OTP expired")
    # Upsert user
    user = db["user"].find_one({"phone": payload.phone})
    if not user:
        uid = create_document("user", User(phone=payload.phone).model_dump())
        user = db["user"].find_one({"_id": ObjectId(uid)})
    # mark verified
    db["otp"].update_many({"phone": payload.phone}, {"$set": {"verified": True}})
    token = payload.phone  # simple token for demo
    return {"token": token, "user": serialize(user)}

# Helper for auth
async def get_phone(x_user_phone: Optional[str] = Header(default=None)) -> Optional[str]:
    return x_user_phone

# --------- Offers / Coupons ---------
@app.get("/offers")
def get_offers():
    items = get_documents("offer", {"active": True}, limit=20)
    return [serialize(i) for i in items]

@app.get("/coupons")
def get_coupons():
    items = get_documents("coupon", {"active": True}, limit=50)
    return [serialize(i) for i in items]

class ApplyCouponPayload(BaseModel):
    code: str
    subtotal: float

@app.post("/cart/apply-coupon")
def apply_coupon(payload: ApplyCouponPayload):
    c = db["coupon"].find_one({"code": payload.code.upper(), "active": True})
    if not c:
        raise HTTPException(status_code=404, detail="Coupon not found")
    if payload.subtotal < float(c.get("min_order", 0)):
        return {"applied": False, "discount": 0.0, "reason": "Minimum order not met"}
    if c.get("type") == "flat":
        discount = float(c["value"])
    else:
        discount = payload.subtotal * float(c["value"]) / 100.0
    return {"applied": True, "discount": round(discount, 2), "code": c["code"], "detail": c.get("description")}

# --------- Menu ---------
@app.get("/menu/categories")
def get_categories():
    return ["Matka Biryanis", "Kebabs", "Rolls", "Combos", "Add-ons & Drinks"]

@app.get("/menu")
def get_menu(category: Optional[str] = Query(default=None)):
    filt = {"available": True}
    if category:
        filt["category"] = category
    items = get_documents("menuitem", filt, limit=200)
    return [serialize(i) for i in items]

class AdminMenuPayload(MenuItem):
    pass

@app.post("/admin/menu")
def admin_create_menu(item: AdminMenuPayload):
    _id = create_document("menuitem", item.model_dump())
    return {"id": _id}

@app.put("/admin/menu/{item_id}")
def admin_update_menu(item_id: str, payload: Dict[str, Any]):
    try:
        oid = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    db["menuitem"].update_one({"_id": oid}, {"$set": payload})
    doc = db["menuitem"].find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return serialize(doc)

@app.delete("/admin/menu/{item_id}")
def admin_delete_menu(item_id: str):
    try:
        oid = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    db["menuitem"].delete_one({"_id": oid})
    return {"deleted": True}

# --------- User Profile ---------
class AddressPayload(DeliveryAddress):
    pass

@app.get("/me")
def get_me(x_user_phone: Optional[str] = Header(default=None)):
    if not x_user_phone:
        raise HTTPException(status_code=401, detail="Missing phone header")
    u = db["user"].find_one({"phone": x_user_phone})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return serialize(u)

@app.post("/me/address")
def add_address(payload: AddressPayload, x_user_phone: Optional[str] = Header(default=None)):
    if not x_user_phone:
        raise HTTPException(status_code=401, detail="Missing phone header")
    db["user"].update_one({"phone": x_user_phone}, {"$push": {"addresses": payload.model_dump()}}, upsert=True)
    u = db["user"].find_one({"phone": x_user_phone})
    return serialize(u)

@app.post("/me/favorites/{item_id}")
def toggle_favorite(item_id: str, x_user_phone: Optional[str] = Header(default=None)):
    if not x_user_phone:
        raise HTTPException(status_code=401, detail="Missing phone header")
    u = db["user"].find_one({"phone": x_user_phone})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    favs = set(u.get("favorites", []))
    if item_id in favs:
        db["user"].update_one({"phone": x_user_phone}, {"$pull": {"favorites": item_id}})
        action = "removed"
    else:
        db["user"].update_one({"phone": x_user_phone}, {"$addToSet": {"favorites": item_id}})
        action = "added"
    return {"status": action}

# --------- Orders ---------
class CreateOrderPayload(BaseModel):
    phone: str
    items: List[OrderItem]
    delivery_type: Literal["delivery", "takeaway"] = "delivery"
    address: Optional[DeliveryAddress] = None
    coupon_code: Optional[str] = None
    payment_method: Literal["razorpay", "upi", "cod"] = "cod"

@app.post("/orders")
def create_order(payload: CreateOrderPayload):
    if not payload.items:
        raise HTTPException(status_code=400, detail="No items")
    # compute totals
    subtotal = sum([i.total_price for i in payload.items])
    delivery_fee = 0 if payload.delivery_type == "takeaway" else 20
    discount = 0.0
    if payload.coupon_code:
        c = db["coupon"].find_one({"code": payload.coupon_code.upper(), "active": True})
        if c and subtotal >= float(c.get("min_order", 0)):
            discount = (float(c["value"]) if c["type"] == "flat" else subtotal * float(c["value"]) / 100.0)
    total = max(0.0, subtotal - discount + delivery_fee)
    order_doc = Order(
        user_id=None,
        phone=payload.phone,
        items=payload.items,
        subtotal=subtotal,
        discount=round(discount, 2),
        delivery_fee=delivery_fee,
        total=round(total, 2),
        delivery_type=payload.delivery_type,
        address=payload.address,
        payment_method=payload.payment_method,
        payment_status=("cod" if payload.payment_method == "cod" else "pending"),
        status="pending",
        eta_minutes=35,
        coupon_code=payload.coupon_code,
    ).model_dump()
    oid = create_document("order", order_doc)
    order = db["order"].find_one({"_id": ObjectId(oid)})
    payment = None
    if payload.payment_method in ("razorpay", "upi"):
        # Simulated payment payload
        payment = {"gateway": payload.payment_method, "order_id": str(oid), "amount": order_doc["total"]}
    return {"order": serialize(order), "payment": payment}

@app.get("/orders/{order_id}")
def get_order(order_id: str):
    try:
        oid = ObjectId(order_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    o = db["order"].find_one({"_id": oid})
    if not o:
        raise HTTPException(status_code=404, detail="Not found")
    return serialize(o)

@app.get("/orders")
def list_my_orders(x_user_phone: Optional[str] = Header(default=None)):
    if not x_user_phone:
        raise HTTPException(status_code=401, detail="Missing phone header")
    items = list(db["order"].find({"phone": x_user_phone}).sort("created_at", -1).limit(50))
    return [serialize(i) for i in items]

@app.get("/track/{order_id}")
def track_order(order_id: str):
    return get_order(order_id)

# Admin order status update
class UpdateStatusPayload(BaseModel):
    status: Literal["accepted", "being_prepared", "out_for_delivery", "delivered", "cancelled"]

@app.post("/admin/orders/{order_id}/status")
def update_order_status(order_id: str, payload: UpdateStatusPayload):
    try:
        oid = ObjectId(order_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    upd = {"status": payload.status, "updated_at": datetime.now(timezone.utc)}
    if payload.status == "out_for_delivery":
        upd["eta_minutes"] = 15
    db["order"].update_one({"_id": oid}, {"$set": upd})
    o = db["order"].find_one({"_id": oid})
    return serialize(o)

# --------- Seed sample data ---------
@app.post("/admin/seed")
def seed_data():
    if db["menuitem"].count_documents({}) == 0:
        samples = [
            {
                "title": "Signature Matka Chicken Biryani",
                "category": "Matka Biryanis",
                "description": "Fragrant basmati, tender chicken, sealed in matka.",
                "image_url": "https://images.unsplash.com/photo-1604908554049-1e4f7f1e978a",
                "price_half": 199,
                "price_full": 349,
                "is_signature": True,
                "available": True,
            },
            {
                "title": "Mutton Matka Biryani",
                "category": "Matka Biryanis",
                "description": "Slow-cooked mutton with saffron basmati.",
                "image_url": "https://images.unsplash.com/photo-1551183053-bf91a1d81141",
                "price_half": 299,
                "price_full": 499,
                "is_signature": True,
                "available": True,
            },
            {
                "title": "Chicken Malai Kebab",
                "category": "Kebabs",
                "description": "Creamy, melt-in-mouth kebabs.",
                "image_url": "https://images.unsplash.com/photo-1562967914-608f82629710",
                "price_half": None,
                "price_full": 249,
                "available": True,
            },
            {
                "title": "Chicken Tikka Roll",
                "category": "Rolls",
                "description": "Char-grilled tikka wrapped in rumali roti.",
                "image_url": "https://images.unsplash.com/photo-1604908554049-1e4f7f1e978a",
                "price_half": None,
                "price_full": 179,
                "available": True,
            },
            {
                "title": "Family Combo",
                "category": "Combos",
                "description": "2 Matka Biryanis + 2 Kebabs + 4 Drinks",
                "image_url": "https://images.unsplash.com/photo-1544025162-d76694265947",
                "price_half": None,
                "price_full": 1099,
                "available": True,
            },
            {
                "title": "Gulab Jamun",
                "category": "Add-ons & Drinks",
                "description": "Soft, warm, and syrupy.",
                "image_url": "https://images.unsplash.com/photo-1604908176839-9c1790c595d4",
                "price_half": None,
                "price_full": 79,
                "available": True,
            },
        ]
        for s in samples:
            create_document("menuitem", s)
    if db["offer"].count_documents({}) == 0:
        create_document("offer", {
            "title": "Best Biryani – G Plus Guwahati Food Awards 2024",
            "description": "Celebrating our win with 15% off on Matka Biryanis!",
            "banner_url": "https://images.unsplash.com/photo-1606787366850-de6330128bfc",
            "active": True,
        })
    if db["coupon"].count_documents({}) == 0:
        create_document("coupon", {
            "code": "PAKKTUN15",
            "description": "15% off on orders above ₹499",
            "type": "percent",
            "value": 15,
            "min_order": 499,
            "active": True,
        })
    return {"seeded": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
