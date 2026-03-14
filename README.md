# foody

AI-powered food discovery backend built with **Python + FastAPI**.

## Features

| Function | Description |
|---|---|
| `GetRestaurantNearby(location, radius)` | Finds nearby restaurants via Google Places API with TTL caching |
| `ExtractMenuUrl(restaurant, providers)` | Resolves menu URLs from Menulog, DoorDash, or the restaurant's own site |
| `ExtractMenu(url, provider, extractors)` | Parses menus using HTML parsing, AI (OpenAI), or OCR |
| `EstimateNutrition(item, estimator)` | Estimates calories/macros via OpenAI or USDA FoodData Central |
| `AnalyzeUserPreferenceProfile(profile)` | Maps goals to calorie targets and macro splits |
| `StoreUserProfile(profile)` | Persists user profiles (goal, macros, restrictions, budget, history) |
| `RankingTopMenu(profile, items, N)` | Scores and returns the top-N items matched to the user's profile |

## Project Structure

```
foody/
├── app/
│   ├── main.py              # FastAPI app & REST endpoints
│   ├── config.py            # Settings (reads .env)
│   ├── models/              # Pydantic data models
│   │   ├── restaurant.py    # Restaurant, Location
│   │   ├── menu.py          # MenuItem
│   │   ├── nutrition.py     # NutritionEstimate
│   │   └── user.py          # UserProfile, GoalType, MacroSplits
│   ├── services/            # Core business logic
│   │   ├── restaurant_service.py
│   │   ├── menu_service.py
│   │   ├── nutrition_service.py
│   │   ├── user_service.py
│   │   └── ranking_service.py
│   ├── providers/           # Menu URL providers
│   │   ├── menulog.py
│   │   ├── doordash.py
│   │   └── restaurant_site.py
│   ├── extractors/          # Menu content extractors
│   │   ├── web_fetcher.py   # HTML parser
│   │   ├── ai_extractor.py  # OpenAI-based
│   │   └── ocr_extractor.py # OCR stub
│   └── cache/
│       └── restaurant_cache.py  # TTL in-memory cache
├── tests/                   # pytest test suite
├── data/                    # User profile storage (auto-created)
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── .env.example
```

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your API keys
```

Required API keys:
- `GOOGLE_PLACES_API_KEY` – [Google Cloud Console](https://console.cloud.google.com/)
- `OPENAI_API_KEY` – [OpenAI](https://platform.openai.com/)
- `USDA_API_KEY` – [FoodData Central](https://fdc.nal.usda.gov/api-guide.html) (free)

### 3. Run the server

```bash
uvicorn app.main:app --reload
```

Interactive API docs: http://localhost:8000/docs

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/restaurants/nearby` | Find restaurants near a location |
| `POST` | `/restaurant/menu-url` | Resolve a restaurant's menu URL |
| `POST` | `/menu/extract` | Extract structured items from a menu URL |
| `POST` | `/nutrition/estimate` | Estimate nutrition for a menu item |
| `GET` | `/user/{user_id}/profile` | Retrieve a user profile |
| `PUT` | `/user/{user_id}/profile` | Create or update a user profile |
| `DELETE` | `/user/{user_id}/profile` | Delete a user profile |
| `POST` | `/menu/rank` | Rank menu items for a user |

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest
```
