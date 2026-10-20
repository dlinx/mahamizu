#!/usr/bin/env python3
"""
Pipeline: Download PDF -> Extract tables using Gemini -> Save to MongoDB

Usage:
    python scripts/pipeline.py                    # Uses current date
    python scripts/pipeline.py --date 17-10-2026  # Uses specific date
    python scripts/pipeline.py --use-cache        # Use cached extraction (skip Gemini)
    python scripts/pipeline.py --cache-only       # Only use cache, fail if no cache
"""

import sys
import os
import argparse
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.download_pdf import main as download_pdf_main
from scripts.extract_tables_gemini import extract_and_enrich_tables, load_config
from scripts.save_to_mongo import main as save_to_mongo_main, load_cached_tables, save_cached_tables, init_db, save_tables_to_db, load_mongo_config


def parse_args():
    parser = argparse.ArgumentParser(description="Water Reservoir Data Pipeline")
    parser.add_argument("--date", type=str, help="Date in DD-MM-YYYY format (default: today)")
    parser.add_argument("--use-cache", action="store_true", help="Use cached extraction if available, otherwise run Gemini")
    parser.add_argument("--cache-only", action="store_true", help="Only use cache, fail if no cache")
    parser.add_argument("--skip-download", action="store_true", help="Skip PDF download, use existing PDF")
    return parser.parse_args()


def get_date_str(args):
    if args.date:
        try:
            datetime.strptime(args.date, "%d-%m-%Y")
            return args.date
        except ValueError:
            print(f"Error: Invalid date format. Use DD-MM-YYYY")
            sys.exit(1)
    return datetime.now().strftime("%d-%m-%Y")


def run_pipeline(date_str, use_cache=False, cache_only=False, skip_download=False):
    from datetime import datetime
    from dotenv import load_dotenv
    import urllib.parse
    from pymongo import MongoClient
    from scripts.extract_tables_gemini import extract_and_enrich_tables, load_config
    from scripts.save_to_mongo import load_mongo_config, init_db, save_tables_to_db

    date_str = date_str
    print(f"Pipeline running for date: {date_str}")

    # Step 1: Download PDF
    if not skip_download:
        print("\n=== Step 1: Download PDF ===")
        os.environ["PIPELINE_DATE"] = date_str
        from scripts.download_pdf import main as download_pdf_main
        download_pdf_main(date_str)
    else:
        print("\n=== Step 1: Skipping PDF download ===")

    # Determine PDF path - download script saves as water_status.pdf in project root downloads/
    pdf_path = Path("downloads") / "water_status.pdf"
    if not pdf_path.exists():
        print(f"Error: PDF not found at {pdf_path}")
        sys.exit(1)

    print(f"\nUsing PDF: {pdf_path}")

    # Step 2: Extract tables using Gemini
    print("\n=== Step 2: Extract tables using Gemini ===")
    load_dotenv()
    api_key, model_name = load_config()

    if cache_only:
        print("Loading from cache only...")
        from scripts.save_to_mongo import load_cached_tables
        tables_data = load_cached_tables()
        if tables_data is None:
            print("Error: No cache found. Cannot proceed with --cache-only")
            sys.exit(1)
    elif use_cache:
        print("Checking cache...")
        from scripts.save_to_mongo import load_cached_tables
        tables_data = load_cached_tables()
        if tables_data is None:
            print("No cache found. Running Gemini extraction...")
            tables_data = extract_and_enrich_tables(str(pdf_path))
            from scripts.save_to_mongo import save_cached_tables
            save_cached_tables(tables_data)
    else:
        print("Running Gemini extraction...")
        tables_data = extract_and_enrich_tables(str(pdf_path))
        from scripts.save_to_mongo import save_cached_tables
        save_cached_tables(tables_data)

    print(f"Extracted and enriched {len(tables_data)} date documents")

    # Step 3: Save to MongoDB
    print("\n=== Step 3: Save to MongoDB ===")
    load_dotenv()
    mongo_uri, mongo_db = load_mongo_config()

    print("Connecting to MongoDB...")
    try:
        client = MongoClient(mongo_uri)
        collection = init_db(client, mongo_db)

        # Insert the data - time-series collections don't support replace_one
        # Use upsert with update_one or just insert (time-series auto-handles)
        for doc in tables_data:
            # Time-series collections don't support replace_one or upsert
            # Just insert; if duplicate, it will fail - we catch and skip
            try:
                collection.insert_one(doc)
                print(f"Inserted document for {doc['report_date']}")
            except Exception as e:
                if "duplicate" in str(e).lower() or "E11000" in str(e):
                    print(f"Document for {doc['report_date']} already exists. Skipping...")
                else:
                    raise

        client.close()
        print("Successfully saved to MongoDB")
    except Exception as e:
        print(f"Database error: {e}")
        sys.exit(1)

    print("\n=== Pipeline completed successfully ===")


def main():
    args = parse_args()

    if args.cache_only and args.use_cache:
        print("Error: Cannot use both --cache-only and --use-cache")
        sys.exit(1)

    date_str = get_date_str(args)
    run_pipeline(
        date_str=date_str,
        use_cache=args.use_cache,
        cache_only=args.cache_only,
        skip_download=args.skip_download
    )


if __name__ == "__main__":
    main()