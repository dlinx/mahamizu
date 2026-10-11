import os
import json
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv
from extract_tables_gemini import extract_and_enrich_tables
import urllib.parse
import sys

CACHE_FILE = "downloads/extracted_tables_cached.json"


def load_mongo_config():
    load_dotenv()
    mongo_uri = os.environ.get("mahamizu_MONGODB_URI")
    if not mongo_uri:
        raise ValueError("Set mahamizu_MONGODB_URI in .env file")
    # Try to extract database from URI
    parsed = urllib.parse.urlparse(mongo_uri)
    mongo_db = None
    if parsed.path:
        mongo_db = parsed.path.lstrip('/')
        # Remove any query parameters that might be attached (though urlparse should have separated query)
        if '?' in mongo_db:
            mongo_db = mongo_db.split('?')[0]
    # If still not found, try to get from env var
    if not mongo_db:
        mongo_db = os.environ.get("mahamizu_MONGODB_DATABASE")
    if not mongo_db:
        raise ValueError("Could not determine MongoDB database. Set mahamizu_MONGODB_DATABASE or ensure URI includes a database name.")
    return mongo_uri, mongo_db


def init_db(client, mongo_db):
    db = client[mongo_db]
    collection_name = "water_reservoir_daily_reports"

    # Drop existing collection to ensure clean schema
    if collection_name in db.list_collection_names():
        db[collection_name].drop()
        print(f"Dropped existing collection: {collection_name}")

    # Create time-series collection
    db.create_collection(
        collection_name,
        timeseries={
            "timeField": "report_date",
            "metaField": "state",
            "granularity": "hours"
        }
    )
    print(f"Created time-series collection: {collection_name}")

    collection = db[collection_name]
    # Create indexes for common queries (only on scalar fields)
    collection.create_index([("state", 1)])
    collection.create_index([("created_at", -1)])
    # Note: regions and districts are arrays, cannot be indexed in time-series
    return collection


def save_tables_to_db(tables_data, collection):
    """Save pre-enriched tables directly to MongoDB."""
    if not tables_data:
        print("No tables to save")
        return

    result = collection.insert_many(tables_data)
    print(f"Inserted {len(result.inserted_ids)} documents")


def load_cached_tables():
    """Load cached tables from JSON file for testing without Gemini API calls."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            tables = json.load(f)
        # Convert ISO strings back to datetime objects for time-series
        for table in tables:
            if isinstance(table.get('created_at'), str):
                table['created_at'] = datetime.fromisoformat(table['created_at'].replace('Z', '+00:00'))
            if isinstance(table.get('report_date'), str):
                table['report_date'] = datetime.fromisoformat(table['report_date'].replace('Z', '+00:00'))
            # Also convert nested dams if they have datetime strings
            for dam in table.get('dams', []):
                if isinstance(dam.get('created_at'), str):
                    dam['created_at'] = datetime.fromisoformat(dam['created_at'].replace('Z', '+00:00'))
                if isinstance(dam.get('report_date'), str):
                    dam['report_date'] = datetime.fromisoformat(dam['report_date'].replace('Z', '+00:00'))
        return tables
    return None


def save_cached_tables(tables_data):
    """Save tables to cache file."""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(tables_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"Cached tables saved to {CACHE_FILE}")


def main():
    # Check for test mode flag
    use_cache = "--use-cache" in sys.argv
    cache_only = "--cache-only" in sys.argv

    # Load configs
    load_dotenv()  # For Gemini API key and model
    mongo_uri, mongo_db = load_mongo_config()

    # Extract tables from PDF
    pdf_path = os.path.join("downloads", "Today's-Storage-ReportMarathi-11-10-2026.pdf")
    if not os.path.exists(pdf_path):
        pdf_path = os.path.join("downloads", "water_status.pdf")
        if not os.path.exists(pdf_path):
            print("PDF not found")
            return

    if cache_only:
        print("Loading tables from cache...")
        tables_data = load_cached_tables()
        if tables_data is None:
            print("No cache found. Run without --cache-only first.")
            return
    elif use_cache:
        print("Loading tables from cache...")
        tables_data = load_cached_tables()
        if tables_data is None:
            print("No cache found. Extracting from PDF...")
            tables_data = extract_and_enrich_tables(pdf_path)
            save_cached_tables(tables_data)
    else:
        print("Extracting and enriching tables from PDF...")
        tables_data = extract_and_enrich_tables(pdf_path)
        save_cached_tables(tables_data)

    print(f"Extracted and enriched {len(tables_data)} tables")

    # Save to MongoDB
    print("Connecting to MongoDB...")
    try:
        client = MongoClient(mongo_uri)
        collection = init_db(client, mongo_db)
        save_tables_to_db(tables_data, collection)
        client.close()
        print("Successfully saved tables to MongoDB")
    except Exception as e:
        print(f"Database error: {e}")


if __name__ == "__main__":
    main()