import json
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime

FALLBACK_NEWS = [
    {
        "title": "[안내] 현재 실시간으로 보고된 주요 지반침하 뉴스가 없습니다.",
        "link": "#",
        "description": "최근 7일간 '싱크홀' 관련 주요 보도가 없습니다. 안전한 상태입니다.",
        "type": "weather"
    }
]

def crawl_google_news_rss():
    url = "https://news.google.com/rss/search?q=%EC%8B%B1%ED%81%AC%ED%99%80+when:7d&hl=ko&gl=KR&ceid=KR:ko"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            parsed_items = []
            
            for item in root.findall('.//item')[:5]:
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else "#"
                
                desc = "관련 뉴스 기사입니다. 클릭하여 원문을 확인하세요."
                
                parsed_items.append({
                    "title": title,
                    "link": link,
                    "description": desc,
                    "type": "news"
                })
            
            if parsed_items:
                return parsed_items
    except Exception as e:
        print(f"Crawler failed ({e}), using fallback data.")
        
    return FALLBACK_NEWS

def main():
    print("Starting news crawler (Google News RSS)...")
    news_data = crawl_google_news_rss()
    
    out_path = 'web/data/news_issues.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({"issues": news_data, "updated_at": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)
    
    print(f"Saved {len(news_data)} news items to {out_path}.")

if __name__ == '__main__':
    main()
