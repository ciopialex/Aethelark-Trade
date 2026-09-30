"""
News Intelligence Client.
Aggregates news from RSS feeds (Google News, Yahoo Finance) and Press Release wires.
Phase 2: "Source Zero" scanner.
"""

import httpx
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, urlparse, parse_qs
from datetime import datetime
from typing import TypedDict, Optional
from rich.console import Console
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger("aethelark.news")

console = Console()

class NewsItem(TypedDict):
    title: str
    link: str
    published: str  # ISO format optimized for sorting
    source: str     # "Reuters", "Business Wire", "Google News"
    sentiment: Optional[str] # Future use

class NewsClient:
    """
    Federated News Scraper (No API Keys).
    """
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self.client = httpx.Client(headers=self.headers, timeout=10.0, follow_redirects=True)

    def close(self):
        self.client.close()
    
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def fetch_google_news(self, ticker: str, limit: int = 10) -> list[NewsItem]:
        """
        Scrape Google News RSS for a ticker.
        Query: "{TICKER} stock"
        """
        query = quote_plus(f"{ticker} stock")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        
        try:
            response = self.client.get(url)
            response.raise_for_status()
            
            root = ET.fromstring(response.content)
            items = []
            
            for item in root.findall(".//item")[:limit]:
                title = item.find("title").text if item.find("title") is not None else "No Title"
                link = item.find("link").text if item.find("link") is not None else ""
                pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                source_elem = item.find("source")
                source = source_elem.text if source_elem is not None else "Google News"
                
                # Clean up title (Google News often does "Title - Source")
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0]
                    # If source was missing/generic, use the one from title
                    if source == "Google News":
                        source = parts[1]

                # Parse Date (RFC 822) -> ISO
                # Example: "Fri, 08 Feb 2026 15:00:00 GMT"
                try:
                    dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
                    iso_date = dt.isoformat()
                except ValueError:
                    iso_date = pub_date # Keep original if parse fails

                items.append({
                    "title": title,
                    "link": link,
                    "published": iso_date,
                    "source": source,
                    "sentiment": None
                })
                
            return items

        except Exception as e:
            console.print(f"[red]Error fetching Google News: {e}[/red]")
            return []

    def fetch_alpaca_news(self, ticker: str, limit: int = 5) -> list[NewsItem]:
        """
        Fetches professional financial wire news via Alpaca News API.
        No rate limits (429) and high-quality sources (Reuters, Benzinga, etc).
        """
        # Delay import heavily since this isn't globally needed
        from alpaca.data.historical.news import NewsClient
        from alpaca.data.requests import NewsRequest
        
        import os
        api_key = os.environ.get("ALPACA_API_KEY")
        api_sec = os.environ.get("ALPACA_SECRET_KEY")
        
        try:
            news_client = NewsClient(api_key, api_sec)
            request = NewsRequest(symbols=ticker, limit=limit, include_content=False)
            news = news_client.get_news(request)
            
            items = []
            articles = getattr(news, "news", news)
            if not isinstance(articles, (list, tuple)) and hasattr(news, "data"):
                articles = news.data
            
            # Final safety gate: ensure we are iterating over a list of objects
            if isinstance(articles, dict):
                articles = articles.get("news", articles.get("data", articles.get("articles", [])))
            
            if not isinstance(articles, (list, tuple)):
                logger.warning(f"Unexpected news response format: {type(articles)}")
                return []
                
            for article in articles:
                if isinstance(article, str):
                    continue
                # Alpaca provides canonical dates
                dt_iso = article.created_at.isoformat() if hasattr(article.created_at, "isoformat") else str(article.created_at)
                
                items.append({
                    "title": article.headline,
                    "link": article.url if hasattr(article, "url") and article.url else f"https://alpaca.markets/news/{article.id}",
                    "published": dt_iso,
                    "source": article.source if article.source else "Alpaca API",
                    "sentiment": None
                })
            return items
        except Exception as e:
            console.print(f"[red][{ticker}] Alpaca News Error: {e}[/red]")
            return []

    def get_aggregated_news(self, ticker: str, limit: int = 15) -> list[NewsItem]:
        """
        Combined feed from Google and Alpaca Native News API.
        Deduplicates by link/title.
        Sorts by newest first.
        """
        # Fetch sequentially to avoid overloading local net concurrency, but Google -> Alpaca
        google_news = self.fetch_google_news(ticker, limit=limit)
        alpaca_news = self.fetch_alpaca_news(ticker, limit=limit)
        
        combined = google_news + alpaca_news
        
        # Deduplicate
        seen_links = set()
        unique_news = []
        
        for news in combined:
            if news["link"] not in seen_links:
                unique_news.append(news)
                seen_links.add(news["link"])
        
        # Sort by date descending
        unique_news.sort(key=lambda x: x["published"] or "0000", reverse=True)
        
        return unique_news[:limit]
