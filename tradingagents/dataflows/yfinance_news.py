"""yfinance-based news data fetching functions."""

import yfinance as yf
from datetime import datetime
from dateutil.relativedelta import relativedelta

from .config import get_config
from .stockstats_utils import yf_retry


def _tool_cap_int(key: str, default: int) -> int:
    value = get_config().get(key, default)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _truncate_summary(value: str) -> str:
    max_chars = _tool_cap_int("tool_output_news_summary_max_chars", 280)
    value = str(value or "").strip()
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def _render_news_article(title: str, publisher: str, summary: str, link: str) -> str:
    article = f"### {title} (source: {publisher})\n"
    if summary:
        article += f"{_truncate_summary(summary)}\n"
    if link:
        article += f"Link: {link}\n"
    return article + "\n"


def _extract_article_data(article: dict) -> dict:
    """Extract article data from yfinance news format (handles nested 'content' structure)."""
    # Handle nested content structure
    if "content" in article:
        content = article["content"]
        title = content.get("title", "No title")
        summary = content.get("summary", "")
        provider = content.get("provider", {})
        publisher = provider.get("displayName", "Unknown")

        # Get URL from canonicalUrl or clickThroughUrl
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        link = url_obj.get("url", "")

        # Get publish date
        pub_date_str = content.get("pubDate", "")
        pub_date = None
        if pub_date_str:
            try:
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return {
            "title": title,
            "summary": summary,
            "publisher": publisher,
            "link": link,
            "pub_date": pub_date,
        }
    else:
        # Fallback for flat structure
        return {
            "title": article.get("title", "No title"),
            "summary": article.get("summary", ""),
            "publisher": article.get("publisher", "Unknown"),
            "link": article.get("link", ""),
            "pub_date": None,
        }


def get_news_yfinance(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    Retrieve news for a specific stock ticker using yfinance.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        Formatted string containing news articles
    """
    try:
        max_articles = _tool_cap_int("tool_output_news_max_articles", 8)
        stock = yf.Ticker(ticker)
        news = yf_retry(lambda: stock.get_news(count=max_articles))

        if not news:
            return f"No news found for {ticker}"

        # Parse date range for filtering
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        rendered_articles = []
        filtered_count = 0

        for article in news:
            data = _extract_article_data(article)

            # Filter by date if publish time is available
            if data["pub_date"]:
                pub_date_naive = data["pub_date"].replace(tzinfo=None)
                if not (start_dt <= pub_date_naive <= end_dt + relativedelta(days=1)):
                    continue

            rendered_articles.append(
                _render_news_article(
                    data["title"],
                    data["publisher"],
                    data["summary"],
                    data["link"],
                )
            )
            filtered_count += 1
            if filtered_count >= max_articles:
                break

        if filtered_count == 0:
            return f"No news found for {ticker} between {start_date} and {end_date}"

        header = f"## {ticker} News, from {start_date} to {end_date}:\n\n"
        if filtered_count >= max_articles:
            header += f"# Output capped to {max_articles} articles.\n\n"
        return header + "".join(rendered_articles)

    except Exception as e:
        return f"Error fetching news for {ticker}: {str(e)}"


def get_global_news_yfinance(
    curr_date: str,
    look_back_days: int = 7,
    limit: int = 10,
) -> str:
    """
    Retrieve global/macro economic news using yfinance Search.

    Args:
        curr_date: Current date in yyyy-mm-dd format
        look_back_days: Number of days to look back
        limit: Maximum number of articles to return

    Returns:
        Formatted string containing global news articles
    """
    max_articles = _tool_cap_int("tool_output_news_max_articles", limit)
    limit = min(limit, max_articles)
    # Search queries for macro/global news
    search_queries = [
        "stock market economy",
        "Federal Reserve interest rates",
        "inflation economic outlook",
        "global markets trading",
    ]

    all_news = []
    seen_titles = set()

    try:
        for query in search_queries:
            search = yf_retry(lambda q=query: yf.Search(
                query=q,
                news_count=limit,
                enable_fuzzy_query=True,
            ))

            if search.news:
                for article in search.news:
                    # Handle both flat and nested structures
                    if "content" in article:
                        data = _extract_article_data(article)
                        title = data["title"]
                    else:
                        title = article.get("title", "")

                    # Deduplicate by title
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        all_news.append(article)

            if len(all_news) >= limit:
                break

        if not all_news:
            return f"No global news found for {curr_date}"

        # Calculate date range
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - relativedelta(days=look_back_days)
        start_date = start_dt.strftime("%Y-%m-%d")

        rendered_articles = []
        for article in all_news[:limit]:
            # Handle both flat and nested structures
            if "content" in article:
                data = _extract_article_data(article)
                # Skip articles published after curr_date (look-ahead guard)
                if data.get("pub_date"):
                    pub_naive = data["pub_date"].replace(tzinfo=None) if hasattr(data["pub_date"], "replace") else data["pub_date"]
                    if pub_naive > curr_dt + relativedelta(days=1):
                        continue
                title = data["title"]
                publisher = data["publisher"]
                link = data["link"]
                summary = data["summary"]
            else:
                title = article.get("title", "No title")
                publisher = article.get("publisher", "Unknown")
                link = article.get("link", "")
                summary = ""

            rendered_articles.append(_render_news_article(title, publisher, summary, link))

        header = f"## Global Market News, from {start_date} to {curr_date}:\n\n"
        if len(all_news) >= limit:
            header += f"# Output capped to {limit} articles.\n\n"
        return header + "".join(rendered_articles)

    except Exception as e:
        return f"Error fetching global news: {str(e)}"
