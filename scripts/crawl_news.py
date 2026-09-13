import json
import urllib.request
import urllib.error
import re
from datetime import datetime

FALLBACK_NEWS = [
    {
        "title": "[단독] 9호선 공사 지연 연장... 지반 침하 우려",
        "link": "https://news.naver.com",
        "description": "9호선 4단계 연장 공사 구간에서 지반 약화 징후가 발견되어 공사가 일시 중단되었습니다.",
        "type": "subway_construction"
    },
    {
        "title": "삼성역 환승센터 철근 빠짐 논란... 안전 진단 시급",
        "link": "https://news.naver.com",
        "description": "영동대로 복합환승센터(삼성역) 지하 공사 현장에서 철근 누락이 발견되어...",
        "type": "subway_construction"
    },
    {
        "title": "종로구 노후 상수도관 파열... 일대 도로 통제",
        "link": "https://news.naver.com",
        "description": "어젯밤 종로구 인근에서 30년 넘은 노후 상수도관이 파열되어 도로가 침수되었습니다.",
        "type": "pipe_issue"
    },
    {
        "title": "수도권 집중호우... 지반 침하 및 싱크홀 우려",
        "link": "https://news.naver.com",
        "description": "밤사이 내린 폭우로 인해 서울 도심 곳곳에서 지반 침하 징후가 보고되고 있습니다.",
        "type": "weather"
    }
]

def crawl_naver_news_rss():
    url = "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=02&plink=RSSREADER"
    keywords = ["날씨", "기후", "싱크홀", "지반", "침하", "폭우", "호우"]
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            xml = response.read().decode('utf-8')
            items = re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)
            parsed_items = []
            
            for item in items:
                title_match = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', item)
                title = title_match.group(1) if title_match else ""
                
                desc_match = re.search(r'<description><!\[CDATA\[(.*?)\]\]></description>', item)
                desc = desc_match.group(1) if desc_match else ""
                
                # Check keywords
                text_to_check = title + " " + desc
                if not any(k in text_to_check for k in keywords):
                    continue
                
                link_match = re.search(r'<link>(.*?)</link>', item)
                link = link_match.group(1) if link_match else "#"
                
                parsed_items.append({
                    "title": title,
                    "link": link,
                    "description": desc[:80] + "...",
                    "type": "news"
                })
                
                if len(parsed_items) >= 5:
                    break
            
            if parsed_items:
                return parsed_items + FALLBACK_NEWS
    except Exception as e:
        print(f"Crawler failed ({e}), using fallback data.")
        
    return FALLBACK_NEWS

def main():
    print("Starting news crawler (filtered)...")
    news_data = crawl_naver_news_rss()
    
    out_path = 'web/data/news_issues.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({"issues": news_data, "updated_at": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)
    
    print(f"Saved {len(news_data)} news items to {out_path}.")

if __name__ == '__main__':
    main()
