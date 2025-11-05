import os
import math
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import Product, PaymentIntent, Order

app = FastAPI(title="Crypto Store API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Utility helpers ----------

def collection(name: str):
    return db[name]


def usd_to_crypto(amount_usd: float, currency: str) -> float:
    # Mock spot prices: USDC/USDT are $1, BTC is $60,000
    if currency in ("USDC", "USDT"):
        return round(amount_usd, 2)
    if currency == "BTC":
        return round(amount_usd / 60000.0, 8)
    return amount_usd


def random_address(prefix: str = "USDC") -> str:
    # Generate a mock blockchain address
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz123456789"
    core = "".join(secrets.choice(alphabet) for _ in range(34))
    return f"{prefix}_{core}"


# ---------- Schemas for requests ----------

class CreateProductRequest(BaseModel):
    title: str
    description: Optional[str] = None
    price_usd: float
    image_url: Optional[str] = None
    active: bool = True


class CheckoutRequest(BaseModel):
    product_id: str
    currency: str = "USDC"  # USDC, USDT, BTC
    buyer_email: Optional[str] = None


class WebhookMockRequest(BaseModel):
    intent_id: str
    secret: str


# ---------- Health ----------

@app.get("/")
def root():
    return {"status": "ok", "service": "crypto-store"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# ---------- Products ----------

@app.get("/products", response_model=List[Product])
def list_products():
    docs = get_documents("product", {"active": True})
    # Remove Mongo _id for response model
    for d in docs:
        d.pop("_id", None)
    return docs


@app.post("/products")
def create_product(req: CreateProductRequest):
    pid = create_document("product", Product(**req.model_dump()))
    return {"id": pid}


# ---------- Checkout & Payments ----------

@app.post("/checkout")
def create_checkout(req: CheckoutRequest):
    # Fetch product
    prod = db["product"].find_one({"_id": {"$exists": True}, "active": True, "title": {"$exists": True}})
    # Fallback: find by id when provided
    if req.product_id:
        from bson import ObjectId
        try:
            found = db["product"].find_one({"_id": ObjectId(req.product_id)})
            if found:
                prod = found
        except Exception:
            pass
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    amount_usd = float(prod.get("price_usd", 0))
    currency = req.currency.upper()
    address = random_address(currency)
    amount_crypto = usd_to_crypto(amount_usd, currency)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    intent = PaymentIntent(
        product_id=str(prod.get("_id")),
        product_title=prod.get("title", ""),
        amount_usd=amount_usd,
        currency=currency, 
        address=address,
        amount_crypto=amount_crypto,
        status="pending",
        expires_at=expires_at,
    )
    intent_id = create_document("paymentintent", intent)

    # Store buyer email on intent if provided
    if req.buyer_email:
        db["paymentintent"].update_one({"_id": db["paymentintent"].find_one({"_id": {"$exists": True}})["_id"]}, {"$set": {"buyer_email": req.buyer_email}})

    return {"intent_id": intent_id, "address": address, "currency": currency, "amount_crypto": amount_crypto, "amount_usd": amount_usd}


@app.get("/payments/{intent_id}")
def get_payment_status(intent_id: str):
    from bson import ObjectId
    try:
        doc = db["paymentintent"].find_one({"_id": ObjectId(intent_id)})
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid intent id")
    if not doc:
        raise HTTPException(status_code=404, detail="Payment intent not found")
    # Response
    doc_out = {k: v for k, v in doc.items() if k != "_id"}
    doc_out["intent_id"] = intent_id
    return doc_out


@app.post("/webhook/mock/crypto")
def webhook_mark_paid(req: WebhookMockRequest):
    # Simple secret to allow marking as paid in demo
    expected = os.getenv("WEBHOOK_MOCK_SECRET", "demo-secret")
    if req.secret != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from bson import ObjectId
    try:
        oid = ObjectId(req.intent_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid intent id")

    intent = db["paymentintent"].find_one({"_id": oid})
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    if intent.get("status") == "confirmed":
        return {"status": "already_confirmed"}

    # Mark as confirmed
    db["paymentintent"].update_one({"_id": oid}, {"$set": {"status": "confirmed", "confirmed_at": datetime.now(timezone.utc)}})

    # Create order document
    order = Order(
        intent_id=req.intent_id,
        product_id=intent.get("product_id", ""),
        product_title=intent.get("product_title", ""),
        amount_usd=float(intent.get("amount_usd", 0)),
        currency=intent.get("currency", "USDC"),
        amount_crypto=float(intent.get("amount_crypto", 0)),
    )
    order_id = create_document("order", order)
    return {"status": "confirmed", "order_id": order_id}


# ---------- Dashboard ----------

@app.get("/dashboard/summary")
def dashboard_summary():
    total_products = db["product"].count_documents({})
    total_orders = db["order"].count_documents({})
    total_revenue = 0.0
    for o in db["order"].find({}):
        try:
            total_revenue += float(o.get("amount_usd", 0))
        except Exception:
            pass
    recent_orders = []
    for o in db["order"].find({}).sort("created_at", -1).limit(5):
        o.pop("_id", None)
        recent_orders.append(o)
    return {
        "total_products": total_products,
        "total_orders": total_orders,
        "total_revenue": round(total_revenue, 2),
        "recent_orders": recent_orders,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
