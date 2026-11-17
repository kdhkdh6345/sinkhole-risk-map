import json
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

DAYS = 30          # 최근 며칠 이내 기사를 찾을지 (7일이면 기사가 없는 날이 많아 30일로 넓힘)
MAX_ITEMS = 5

FALLBACK_NEWS = [
    {
        "title": "[안내] 현재 실시간으로 보고된 주요 지반침하 뉴스가 없습니다.",
        "link": "#",
        "description": f"최근 {DAYS}일간 '싱크홀' 관련 주요 보도가 없습니다.",
        "type": "weather"
    }
]


def crawl_google_news_rss():
    # 검색어: 싱크홀 OR 땅꺼짐 OR 지반침하, 최근 DAYS일
    q = urllib.parse.quote(f"싱크홀 OR 땅꺼짐 OR 지반침하 when:{DAYS}d")
    url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            root = ET.fromstring(response.read())
        parsed = []
        for item in root.findall('.//item'):
            title = item.findtext('title') or ""
            link = item.findtext('link') or "#"
            source = item.findtext('source') or ""
            try:
                pub = parsedate_to_datetime(item.findtext('pubDate'))
            except Exception:
                pub = None
            date_txt = pub.astimezone().strftime('%Y-%m-%d') if pub else ""
            desc = " · ".join(x for x in (source, date_txt) if x) or "관련 뉴스 기사입니다."
            parsed.append((pub.timestamp() if pub else 0, {
                "title": title,
                "link": link,
                "description": desc + " — 클릭하여 원문을 확인하세요.",
                "date": date_txt,
                "type": "news"
            }))
        parsed.sort(key=lambda x: -x[0])          # 최신 기사부터
        items = [p for _, p in parsed[:MAX_ITEMS]]
        if items:
            return items
    except Exception as e:
        print(f"Crawler failed ({e}), using fallback data.")

    return FALLBACK_NEWS


def main():
    print(f"Starting news crawler (Google News RSS, 최근 {DAYS}일)...")
    news_data = crawl_google_news_rss()

    out_path = 'web/data/news_issues.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({"issues": news_data, "updated_at": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(news_data)} news items to {out_path}.")


if __name__ == '__main__':
    main()
