# REST & Streaming API Specification

Base URL: `http://localhost:8000/api/v1`

---

## 1. Unified Search Endpoint

* **Endpoint**: `POST /search`
* **Description**: Primary endpoint supporting AI search, classic boolean filters, and map exploration bounding boxes.

### Request Body (`application/json`)
```json
{
  "mode": "intelligent",
  "query_text": "آپارتمان دو خوابه نزدیک مترو با آسانسور تا سقف ۲۰ تومن اجاره",
  "neighborhoods": ["یوسف‌آباد", "امیرآباد"],
  "max_deposit_toman": 300000000,
  "max_rent_toman": 20000000,
  "min_area_sqm": 70,
  "rooms": 2,
  "requires_elevator": true,
  "requires_parking": true,
  "workplace_lat": 35.7022,
  "workplace_lon": 51.3533,
  "max_commute_mins": 40,
  "bbox": {
    "min_lat": 35.6800,
    "min_lon": 51.3500,
    "max_lat": 35.7500,
    "max_lon": 51.4500
  },
  "page": 1,
  "page_size": 20
}
```

### Response Body (`application/json`)
```json
{
  "natural_language_summary": "۳ مورد عالی با دسترسی پیاده زیر ۸ دقیقه به مترو و آسانسور پیدا شد که کاملاً در محدوده بودجه شما هستند.",
  "tier_1_results": [
    {
      "id": "teh-101",
      "title": "۸۵ متری نوساز رو به آفتاب، یوسف‌آباد",
      "neighborhood": "یوسف‌آباد",
      "deposit_toman": 300000000,
      "rent_toman": 18000000,
      "area_sqm": 85,
      "floor": 3,
      "has_elevator": true,
      "has_parking": true,
      "lat": 35.7250,
      "lon": 51.4050,
      "dist_to_metro_mins": 6.5,
      "commute_to_work_mins": 22.0,
      "utility_score": 0.885,
      "tier": 1,
      "trade_off_rationale": null
    }
  ],
  "tier_2_results": [
    {
      "id": "teh-204",
      "title": "۱۰۰ متری امیرآباد شمالی، فول امکانات",
      "neighborhood": "امیرآباد",
      "deposit_toman": 350000000,
      "rent_toman": 21000000,
      "area_sqm": 100,
      "floor": 4,
      "has_elevator": true,
      "has_parking": true,
      "lat": 35.7380,
      "lon": 51.3910,
      "dist_to_metro_mins": 11.0,
      "commute_to_work_mins": 28.0,
      "utility_score": 0.642,
      "tier": 2,
      "trade_off_rationale": "کمی فراتر از سقف بودجه، اما ۱۵ متر بزرگتر و دارای سالن پرده‌خور"
    }
  ],
  "total_count": 14
}
```

---

## 2. Conversational Chat Stream (SSE)

* **Endpoint**: `POST /chat/stream`
* **Content-Type**: `text/event-stream`
* **Description**: Real-time token streaming for Persian conversational dialogue.

### Request Body
```json
{
  "message": "یه خونه نزدیک مترو شادمان می‌خوام آسانسور داشته باشه ودیعه تا ۳۰۰ تومن",
  "history": [
    {"role": "user", "content": "سلام"},
    {"role": "assistant", "content": "سلام! چه منطقه‌ای از تهران مدنظرتان است؟"}
  ]
}
```

### Event Stream Format
```
data: {"event": "token", "content": "سه"}
data: {"event": "token", "content": " واحد"}
data: {"event": "token", "content": " مناسب"}
data: {"event": "token", "content": " در نزدیکی مترو شادمان پیدا شد..."}
data: {"event": "state_update", "extracted_intent": {"max_deposit": 300000000, "must_have_elevator": true, "target_neighborhoods": ["شادمان"]}}
data: {"event": "done"}
```

---

## 3. Transit Stations Endpoint

* **Endpoint**: `GET /transit/stations`
* **Response**: Returns geographic coordinates and line affiliations of all Metro and BRT stations for map overlays.
