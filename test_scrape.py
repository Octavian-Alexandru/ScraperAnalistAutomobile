from scraper_olx import parse_listing_detail
from playwright.sync_api import sync_playwright

url = "https://www.olx.ro/d/oferta/volkswagen-caddy-max-IDjNnpp.html"

with sync_playwright() as p:
    browser = p.firefox.launch(headless=False)  # headless=False ca să vezi ce se întâmplă
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)
    html = page.content()
    data = parse_listing_detail(html, url)
    browser.close()

print(data)
