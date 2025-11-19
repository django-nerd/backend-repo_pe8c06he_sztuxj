import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
from bson import ObjectId
from datetime import datetime, timezone

from database import db

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StatusUpdate(BaseModel):
    status: str = Field(..., description="pending|processing|shipped|delivered|cancelled")


# Helpers

def serialize_id(doc):
    if not doc:
        return doc
    doc["id"] = str(doc.pop("_id"))
    # Convert datetimes to isoformat
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.astimezone(timezone.utc).isoformat()
    return doc


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    import os
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


# ---------------- Orders API ----------------

ORDERS_COL = "order"


@app.get("/api/orders")
def list_orders(
    q: Optional[str] = Query(None, description="Search by order number, customer name, or email"),
    status: Optional[str] = Query(None, description="Filter by order status"),
    sort: Optional[str] = Query("-created_at", description="Sort field, prefix with - for desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    filter_query = {}
    if q:
        filter_query["$or"] = [
            {"order_number": {"$regex": q, "$options": "i"}},
            {"customer_name": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
        ]
    if status:
        filter_query["status"] = status

    # Sorting
    sort_field = sort.lstrip("-")
    direction = -1 if sort.startswith("-") else 1

    total = db[ORDERS_COL].count_documents(filter_query)

    cursor = (
        db[ORDERS_COL]
        .find(filter_query)
        .sort(sort_field, direction)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    items = [serialize_id(doc) for doc in cursor]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    try:
        doc = db[ORDERS_COL].find_one({"_id": ObjectId(order_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order id")
    if not doc:
        raise HTTPException(status_code=404, detail="Order not found")
    return serialize_id(doc)


@app.patch("/api/orders/{order_id}/status")
def update_order_status(order_id: str, payload: StatusUpdate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    try:
        oid = ObjectId(order_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order id")

    result = db[ORDERS_COL].update_one(
        {"_id": oid}, {"$set": {"status": payload.status, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")
    doc = db[ORDERS_COL].find_one({"_id": oid})
    return serialize_id(doc)


class SeedItem(BaseModel):
    product_name: str
    quantity: int
    price: float

class SeedOrder(BaseModel):
    order_number: str
    customer_name: str
    email: str
    status: str = "pending"
    total_amount: float
    items: List[SeedItem]


@app.post("/api/orders/seed")
def seed_orders():
    """Create a few demo orders for testing the admin UI."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    demo_orders = [
        {
            "order_number": "ORD-1001",
            "customer_name": "Ava Nguyen",
            "email": "ava@example.com",
            "status": "pending",
            "total_amount": 89.5,
            "items": [
                {"product_name": "Velvet Matte Lipstick", "quantity": 1, "price": 24.5},
                {"product_name": "Hydra Glow Serum", "quantity": 1, "price": 65.0},
            ],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        },
        {
            "order_number": "ORD-1002",
            "customer_name": "Liam Patel",
            "email": "liam@example.com",
            "status": "processing",
            "total_amount": 42.0,
            "items": [
                {"product_name": "Silk Finish Foundation", "quantity": 1, "price": 42.0},
            ],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        },
        {
            "order_number": "ORD-1003",
            "customer_name": "Maya Khan",
            "email": "maya@example.com",
            "status": "shipped",
            "total_amount": 120.0,
            "items": [
                {"product_name": "Radiant Blush Palette", "quantity": 1, "price": 55.0},
                {"product_name": "Ultra Define Mascara", "quantity": 2, "price": 32.5},
            ],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        },
    ]

    db[ORDERS_COL].insert_many(demo_orders)
    return {"inserted": len(demo_orders)}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
