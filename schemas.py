from pydantic import BaseModel, Field
from typing import Optional, Literal, List
from datetime import datetime

# Product catalog
class Product(BaseModel):
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price_usd: float = Field(..., ge=0, description="Price in USD")
    image_url: Optional[str] = Field(None, description="Product image URL")
    active: bool = Field(True, description="Whether product is available")

# Payment intent for a checkout
class PaymentIntent(BaseModel):
    product_id: str = Field(..., description="ID of the product being purchased")
    product_title: str = Field(..., description="Title snapshot at time of intent")
    amount_usd: float = Field(..., ge=0, description="Amount to collect in USD")
    currency: Literal['USDC', 'USDT', 'BTC'] = Field('USDC', description="Crypto currency to pay with")
    address: str = Field(..., description="Destination blockchain address")
    amount_crypto: float = Field(..., ge=0, description="Amount to send in crypto units")
    status: Literal['pending', 'confirmed', 'expired'] = Field('pending', description="Payment status")
    expires_at: Optional[datetime] = Field(None, description="Expiration timestamp for this intent")

# Order created when payment is confirmed
class Order(BaseModel):
    intent_id: str = Field(..., description="Payment intent ID")
    product_id: str = Field(..., description="Product ID")
    product_title: str = Field(..., description="Product title snapshot")
    amount_usd: float = Field(..., ge=0, description="Paid USD amount")
    currency: Literal['USDC', 'USDT', 'BTC'] = Field('USDC', description="Crypto currency paid")
    amount_crypto: float = Field(..., ge=0, description="Crypto amount paid")
    buyer_email: Optional[str] = Field(None, description="Email of buyer if provided")
