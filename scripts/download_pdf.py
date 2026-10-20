import os
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from datetime import datetime
from dotenv import load_dotenv


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


def load_config():
    load_dotenv()
    return {"pdf_url_template": os.getenv("PDF_URL_TEMPLATE")}


def create_session():
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    return session


def get_file_size(url, session):
    response = session.get(url, headers={"Range": "bytes=0-0"}, stream=True)
    response.raise_for_status()
    content_range = response.headers.get("Content-Range", "")
    if content_range:
        return int(content_range.split("/")[-1])
    return int(response.headers.get("Content-Length", 0))


def supports_range(url, session):
    response = session.get(url, headers={"Range": "bytes=0-0"}, stream=True)
    return response.headers.get("Accept-Ranges", "") == "bytes" or response.status_code == 206


def download_chunk(url, start, end, output_path, progress_bar, session):
    headers = {"Range": f"bytes={start}-{end}"}
    response = session.get(url, headers=headers, stream=True)
    response.raise_for_status()
    with open(output_path, "r+b") as f:
        f.seek(start)
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            progress_bar.update(len(chunk))


def download_pdf_multipart(url, output_path, num_chunks=8):
    session = create_session()
    file_size = get_file_size(url, session)
    if file_size == 0:
        print("Could not determine file size, falling back to single stream")
        download_pdf_single(url, output_path, session)
        return

    if not supports_range(url, session):
        print("Server does not support range requests, falling back to single stream")
        download_pdf_single(url, output_path, session)
        return

    chunk_size = file_size // num_chunks
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.truncate(file_size)

    with tqdm(total=file_size, unit="B", unit_scale=True, desc="Downloading") as pbar:
        with ThreadPoolExecutor(max_workers=num_chunks) as executor:
            futures = []
            for i in range(num_chunks):
                start = i * chunk_size
                end = file_size - 1 if i == num_chunks - 1 else (i + 1) * chunk_size - 1
                futures.append(executor.submit(download_chunk, url, start, end, output_path, pbar, session))
            for future in futures:
                future.result()

    print(f"Downloaded: {output_path}")


def download_pdf_single(url, output_path, session):
    response = session.get(url, stream=True)
    response.raise_for_status()
    total = int(response.headers.get("Content-Length", 0))
    with tqdm(total=total, unit="B", unit_scale=True, desc="Downloading") as pbar:
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                pbar.update(len(chunk))
    print(f"Downloaded: {output_path}")


def get_today_date_str():
    return datetime.now().strftime("%d-%m-%Y")


def main(date_str=None):
    config = load_config()
    if date_str is None:
        date_str = os.environ.get("PIPELINE_DATE", get_today_date_str())
    pdf_url = config["pdf_url_template"].format(date=date_str)
    # Save to project root downloads directory (not scripts/downloads)
    output_dir = Path(__file__).parent.parent / "downloads"
    output_dir.mkdir(exist_ok=True)
    filename = pdf_url.split("/")[-1]
    output_path = output_dir / "water_status.pdf"
    print(f"Downloading: {pdf_url}")
    download_pdf_multipart(pdf_url, output_path)


if __name__ == "__main__":
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(date_arg)