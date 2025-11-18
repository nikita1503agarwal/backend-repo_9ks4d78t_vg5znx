"""
Database Schemas for Pakkhtun Biryani

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime

# Users
class User(BaseModel):
    phone: str = Field(..., description="Phone number as login")
    name: Optional[str] = Field(None, description="Full name")
    email: Optional[str] = Field(None, description="Email address")
    addresses: List[dict] = Field(default_factory=list, description="Saved addresses")
    favorites: List[str] = Field(default_factory=list, description="Favorite menu item ids")
    loyalty_points: int = Field(0, ge=0, description="Earned loyalty points")
    is_active: bool = Field(True)

# OTP session (short-lived)
class Otp(BaseModel):
    phone: str
    code: str
    expires_at: datetime
    verified: bool = False

# Menu
class MenuItem(BaseModel):
    title: str
    category: Literal[
        "Matka Biryanis", "Kebabs", "Rolls", "Combos", "Add-ons & Drinks"
    ]
    description: Optional[str] = None
    image_url: Optional[str] = None
    price_half: Optional[float] = Field(None, ge=0)
    price_full: float = Field(..., ge=0)
    is_signature: bool = False
    available: bool = True

class Coupon(BaseModel):
    code: str
    description: Optional[str] = None
    type: Literal["flat", "percent"] = "percent"
    value: float = Field(..., ge=0)
    min_order: float = Field(0, ge=0)
    active: bool = True

class Offer(BaseModel):
    title: str
    description: Optional[str] = None
    banner_url: Optional[str] = None
    active: bool = True

# Orders
class OrderItem(BaseModel):
    item_id: str
    title: str
    variant: Literal["half", "full"] = "full"
    quantity: int = Field(1, ge=1)
    unit_price: float = Field(..., ge=0)
    total_price: float = Field(..., ge=0)
    image_url: Optional[str] = None

class DeliveryAddress(BaseModel):
    label: Optional[str] = None
    line1: str
    line2: Optional[str] = None
    city: str = "Guwahati"
    state: str = "Assam"
    pincode: str
    lat: Optional[float] = None
    lng: Optional[float] = None

class Order(BaseModel):
    user_id: Optional[str] = None
    phone: str
    items: List[OrderItem]
    subtotal: float
    discount: float = 0
    delivery_fee: float = 0
    total: float
    delivery_type: Literal["delivery", "takeaway"] = "delivery"
    address: Optional[DeliveryAddress] = None
    payment_method: Literal["razorpay", "upi", "cod"] = "cod"
    payment_status: Literal["pending", "paid", "cod"] = "pending"
    status: Literal[
        "pending", "accepted", "being_prepared", "out_for_delivery", "delivered", "cancelled"
    ] = "pending"
    eta_minutes: Optional[int] = 30
    coupon_code: Optional[str] = None
    notes: Optional[str] = None

class Feedback(BaseModel):
    order_id: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
