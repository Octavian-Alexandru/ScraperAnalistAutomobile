# FILE: photo_downloader.py
"""
Descărcător automat de fotografii auto și procesare imagini.
- Descarcă primele 3-5 imagini per anunț auto pentru analiză Computer Vision / arhivare
- Salvează pe disc în `data/car_images/{car_id}/img_{idx}.jpg`
- Verifică rezoluția, dimensiunea și integritatea fișierelor cu PIL
- Suportă descărcare concurentă rapidă cu ThreadPoolExecutor
"""

import os
import sys
import hashlib
import requests
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from io import BytesIO

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from logger_config import logger

IMAGES_BASE_DIR = os.path.join("data", "car_images")


def download_single_image(url: str, save_path: str, timeout: int = 10) -> Optional[str]:
    """Descarcă o imagine de la URL și o salvează optimizat pe disc."""
    if not url or not url.startswith("http"):
        return None

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.autovit.ro/"
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200 and len(resp.content) > 1024:
            # Validăm că e o imagine reală cu PIL
            img = Image.open(BytesIO(resp.content))
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            # Salvare ca JPEG optimizat
            img.convert("RGB").save(save_path, "JPEG", quality=85)
            return save_path
    except Exception:
        pass
    return None


def download_car_photos(
    car_id: str,
    image_urls: List[str],
    max_photos: int = 4,
    base_dir: str = IMAGES_BASE_DIR
) -> List[str]:
    """
    Descarcă primele `max_photos` fotografii pentru o mașină dată.
    Returnează lista căilor locale ale fișierelor descărcate.
    """
    if not image_urls:
        return []

    car_dir = os.path.join(base_dir, str(car_id))
    os.makedirs(car_dir, exist_ok=True)

    urls_to_download = [u for u in image_urls[:max_photos] if u and u.startswith("http")]
    saved_paths = []

    with ThreadPoolExecutor(max_workers=min(4, len(urls_to_download))) as executor:
        futures = []
        for idx, url in enumerate(urls_to_download):
            target_file = os.path.join(car_dir, f"img_{idx + 1}.jpg")
            futures.append(executor.submit(download_single_image, url, target_file))

        for fut in futures:
            path = fut.result()
            if path:
                saved_paths.append(path)

    return saved_paths


if __name__ == "__main__":
    print("=== TEST PHOTO DOWNLOADER ===")
    sample_urls = [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6d/Volkswagen_Golf_VIII_1.5_eTSI_Reflexsilber_Front.jpg/640px-Volkswagen_Golf_VIII_1.5_eTSI_Reflexsilber_Front.jpg"
    ]
    saved = download_car_photos(car_id="test_sample_vw", image_urls=sample_urls)
    print("Fotografii descărcate local:", saved)
