import os
import json
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# 1. Use the new standard Google GenAI SDK and Pydantic
from google import genai
from pydantic import BaseModel, Field


# 2. Define the exact JSON structure you want using Pydantic
class TableSchema(BaseModel):
    table_index: int = Field(description="The table number")
    headers: list[str] = Field(description="List of column headers")
    rows: list[list[str]] = Field(description="List of rows, where each row is a list of cell values")
    context: str | None = Field(None, description="Surrounding text describing the table")


class ExtractedTables(BaseModel):
    tables: list[TableSchema]


def load_config():
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")

    # 3. Upgrade to the latest recommended default model
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    print(f"Using model: {model_name}")

    if not api_key:
        raise ValueError("Set GEMINI_API_KEY in .env file")
    return api_key, model_name


def extract_report_date(context: str, filename: str):
    """Extract report date from context or filename. Returns datetime object for time-series."""
    from datetime import datetime
    date_patterns = [
        r'(\d{1,2}/\d{1,2}/\d{4})',  # DD/MM/YYYY
        r'(\d{2}-\d{2}-\d{4})',      # DD-MM-YYYY
    ]
    for pattern in date_patterns:
        match = re.search(pattern, context)
        if match:
            date_str = match.group(1)
            if '/' in date_str:
                date_str = date_str.replace('/', '-')
            try:
                return datetime.strptime(date_str, "%d-%m-%Y")
            except ValueError:
                pass

    filename_match = re.search(r'(\d{2}-\d{2}-\d{4})', filename)
    if filename_match:
        try:
            return datetime.strptime(filename_match.group(1), "%d-%m-%Y")
        except ValueError:
            pass

    # Fallback: return current date
    return datetime.utcnow()


def determine_report_type(context: str) -> str:
    """Determine report type based on context content."""
    if 'तुलनात्मक' in context:
        return "comparative"
    elif 'धरणाचे नाव' in context:
        return "detailed_dam_wise"
    elif 'एकूण' in context and 'प्रकल्प' in context:
        return "summary_by_project_size"
    else:
        return "daily_storage"


def determine_table_category(context: str) -> str:
    """Determine table category from context."""
    if 'तुलनात्मक' in context and 'मोठे' in context and 'मध्यम' in context and 'लघु' in context:
        return "summary_by_project_size"
    elif 'महाराष्ट्र राज्य (सर्व धरण)' in context:
        return "state_summary"
    elif 'धरणाचे नाव' in context:
        return "dam_wise_detailed"
    else:
        return "daily_storage"


def extract_region(context: str) -> str:
    """Extract region from context."""
    regions = [
        "नागपूर", "अमरावती", "छत्रपती संभाजीनगर",
        "नाशिक", "पुणे", "कोकण", "महाराष्ट्र राज्य"
    ]
    for region in regions:
        if region in context:
            return region
    return ""


def extract_project_type(context: str) -> str:
    """Extract project type from context."""
    types = ["मोठे प्रकल्प", "मध्यम प्रकल्प", "लघु प्रकल्प", "सर्व धरण", "महाराष्ट्र राज्य (सर्व धरण) प्रकल्प"]
    for ptype in types:
        if ptype in context:
            return ptype
    return ""


def extract_tables_from_pdf(pdf_path: str, api_key: str, model_name: str) -> str:
    # 4. Initialize the new Client instance (replaces genai.configure)
    client = genai.Client(api_key=api_key)

    # 5. New File API upload syntax
    pdf_file = client.files.upload(file=pdf_path)

    # The prompt can be much simpler now that Pydantic enforces the JSON schema
    prompt = "Extract all tables from this PDF document."

    # 6. Pass the Pydantic schema directly into the generation config
    response = client.models.generate_content(
        model=model_name,
        contents=[prompt, pdf_file],
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExtractedTables,
        ),
    )

    # Cleanup using new syntax
    client.files.delete(name=pdf_file.name)

    # Parse the response to get the tables list and return just that as JSON array
    parsed = ExtractedTables.model_validate_json(response.text)
    # Convert Pydantic models to dicts for JSON serialization
    tables = [table.model_dump() for table in parsed.tables]
    return json.dumps(tables)


def parse_dam_row(headers: list, row: list, context: str, report_date, now) -> dict | None:
    """Parse a single dam row into a normalized document."""
    # Skip header/separator rows
    if not row or len(row) < 11:
        return None

    # Check if it's a section header (like "नागपूर प्रदेश", "मोठे प्रकल्प", "एकूण...")
    first_col = row[0].strip() if row[0] else ""
    if first_col in ["मोठे प्रकल्प", "मध्यम प्रकल्प", "लघु प्रकल्प", "एकूण मोठे प्रकल्प",
                      "एकूण मध्यम प्रकल्प", "एकूण लघु प्रकल्प", "एकूण महाराष्ट्र राज्य (सर्व धरण) प्रकल्प",
                      "सर्व प्रदेश मोठे प्रकल्प एकूण", "एकूण नागपूर प्रदेश", "एकूण अमरावती प्रदेश",
                      "एकूण छत्रपती संभाजीनगर प्रदेश", "एकूण नाशिक प्रदेश", "एकूण पुणे प्रदेश",
                      "एकूण कोकण प्रदेश", "बॅरेजेस बंधारे वगळता सर्व धरणे"]:
        return None

    # Skip district headers (like "नागपूर प्रदेश", "भंडारा", "चंद्रपूर", etc.)
    district_names = ["प्रदेश", "भंडारा", "चंद्रपूर", "गडचिरोली", "गोंदिया", "नागपूर", "वर्धा",
                       "अकोला", "अमरावती", "बुलढाणा", "यवतमाळ", "छत्रपती संभाजीनगर",
                       "बीड", "हिंगोली", "नांदेड", "धाराशिव", "लातूर", "परभणी",
                       "अहिल्यानगर", "जळगाव", "नाशिक", "कोल्हापूर", "पुणे", "सांगली",
                       "सातारा", "सोलापूर", "पालघर", "रायगड", "सिंधुदुर्ग", "ठाणे"]
    if any(d in first_col for d in district_names) and len(set(row)) == 1:
        return None

    # Parse numeric values from row
    try:
        doc = {
            "dam_name": row[1].strip() if len(row) > 1 else "",
            "serial_number": row[0].strip() if len(row) > 0 else "",
            "date": row[2].strip() if len(row) > 2 else "",
            "time": row[3].strip() if len(row) > 3 else "",
            "dead_storage_mcm": parse_float(row[4]) if len(row) > 4 else None,
            "live_storage_mcm": parse_float(row[5]) if len(row) > 5 else None,
            "total_design_storage_mcm": parse_float(row[6]) if len(row) > 6 else None,
            "current_live_storage_mcm": parse_float(row[7]) if len(row) > 7 else None,
            "current_total_storage_mcm": parse_float(row[8]) if len(row) > 8 else None,
            "percentage_today": row[9].strip() if len(row) > 9 else "",
            "percentage_last_year": row[10].strip() if len(row) > 10 else "",
        }
    except Exception:
        return None

    # Skip if no dam name
    if not doc["dam_name"]:
        return None

    # Add metadata
    doc.update({
        "region": extract_region(context),
        "district": extract_district(context, row),
        "project_type": extract_project_type(context),
        "report_date": report_date,
        "created_at": now,
        "units": "MCM",
    })

    return doc


def parse_float(value: str):
    """Parse float from string, handling Indian number format."""
    if not value or not value.strip():
        return None
    try:
        # Remove commas and convert
        cleaned = value.strip().replace(',', '')
        return float(cleaned)
    except ValueError:
        return None


def extract_district(context: str, row: list) -> str:
    """Extract district from context or row data."""
    districts = ["भंडारा", "चंद्रपूर", "गडचिरोली", "गोंदिया", "नागपूर", "वर्धा",
                 "अकोला", "अमरावती", "बुलढाणा", "यवतमाळ", "छत्रपती संभाजीनगर",
                 "बीड", "हिंगोली", "नांदेड", "धाराशिव", "लातूर", "परभणी",
                 "अहिल्यानगर", "जळगाव", "नाशिक", "कोल्हापूर", "पुणे", "सांगली",
                 "सातारा", "सोलापूर", "पालघर", "रायगड", "सिंधुदुर्ग", "ठाणे"]

    # Check context first
    for d in districts:
        if d in context:
            return d

    # Check if first column might be a district
    first_col = row[0].strip() if row[0] else ""
    for d in districts:
        if d in first_col:
            return d

    return ""


def extract_and_enrich_tables(pdf_path: str) -> list:
    """Extract tables from PDF and enrich with metadata for MongoDB storage.
    Returns ONE document per report_date with dams grouped by region."""
    api_key, model_name = load_config()

    # Get raw tables
    tables_json = extract_tables_from_pdf(pdf_path, api_key, model_name)
    tables = json.loads(tables_json)

    now = datetime.utcnow()
    pdf_filename = os.path.basename(pdf_path)

    # Group all data by report_date
    date_documents = {}

    for table in tables:
        context = table.get("context", "")
        report_date = extract_report_date(context, pdf_filename)
        headers = table.get("headers", [])
        rows = table.get("rows", [])
        category = determine_table_category(context)

        # Initialize date document if not exists
        if report_date not in date_documents:
            date_documents[report_date] = {
                "report_date": report_date,
                "created_at": now,
                "units": "MCM",
                "regions": {},  # region -> {dams: [], summaries: []}
                "state": "Maharashtra",
            }

        doc = date_documents[report_date]

        if category == "dam_wise_detailed":
            for row in rows:
                dam_doc = parse_dam_row(headers, row, context, report_date, now)
                if dam_doc:
                    region = dam_doc.get("region", "Unknown")
                    # Remove region and district from dam doc since they're implied by grouping
                    dam_doc.pop("region", None)
                    dam_doc.pop("district", None)

                    if region not in doc["regions"]:
                        doc["regions"][region] = {"dams": [], "summaries": []}
                    doc["regions"][region]["dams"].append(dam_doc)

        elif category in ["summary_by_project_size", "state_summary"]:
            summary_doc = {
                "category": category,
                "project_type": extract_project_type(context),
                "headers": headers,
                "rows": rows,
                "context": context,
            }
            region = extract_region(context) or "Unknown"
            if region not in doc["regions"]:
                doc["regions"][region] = {"dams": [], "summaries": []}
            doc["regions"][region]["summaries"].append(summary_doc)

    # Convert to list of documents, converting sets to lists
    result = []
    for report_date, data in date_documents.items():
        # Convert regions dict to final format
        regions_output = {}
        for region_name, region_data in data["regions"].items():
            regions_output[region_name] = {
                "dams": region_data["dams"],
                "summaries": region_data["summaries"],
                "dam_count": len(region_data["dams"]),
            }

        result.append({
            "report_date": report_date,
            "created_at": now,
            "units": "MCM",
            "state": "Maharashtra",
            "regions": regions_output,
        })

    return result

    # Convert to list of documents, converting sets to lists
    result = []
    for report_date, data in date_documents.items():
        data["regions"] = list(data["regions"])
        data["districts"] = list(data["districts"])
        data["total_dams"] = len(data["dams"])
        result.append(data)

    return result


def main():
    pdf_path = Path("downloads") / "water_status.pdf"

    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        return

    api_key, model_name = load_config()
    print("Extracting tables from PDF...")

    result = extract_tables_from_pdf(str(pdf_path), api_key, model_name)
    print(result)

    output_path = Path("downloads") / "extracted_tables.json"

    # Safety check: ensure the downloads directory actually exists before writing
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()