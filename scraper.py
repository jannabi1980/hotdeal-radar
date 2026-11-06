import json
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests

KST = timezone(timedelta(hours=9))

def get_html(url: str, encoding: str = "utf-8") -> str:
    """크롬 브라우저 TLS 지문으로 위장해 Cloudflare 봇 차단을 우회"""
    res = cf_requests.get(
        url,
        impersonate="chrome120",
        headers={"Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8"},
        timeout=12
    )
    res.raise_for_status()
    if encoding != "utf-8":
        return res.content.decode(encoding, errors="replace")
    return res.text

def classify_category(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["모니터", "노트북", "그래픽", "rtx", "라데온", "ssd", "nvme", "램", "마우스", "키보드", "충전기", "갤럭시", "아이폰", "아이패드", "맥북", "tv", "청소기", "가전", "스팀", "ps5", "닌텐도", "스위치", "이어폰", "헤드셋"]):
        return "전자/PC"
    if any(k in t for k in ["생수", "커피", "우유", "닭가슴살", "프로틴", "라면", "만두", "과자", "쌀", "비타민", "유산균", "치약", "샴푸", "물티슈", "세제", "휴지", "돼지", "소고기", "콜라", "음료"]):
        return "식품/생필품"
    if any(k in t for k in ["나이키", "아디다스", "뉴발란스", "맨투맨", "후드", "바지", "자켓", "패딩", "운동화", "슬리퍼", "티셔츠", "언더아머", "셔츠", "코트", "가방", "양말"]):
        return "패션/의류"
    return "상품권/기타"

def clean_title(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def is_expired(title: str) -> bool:
    return any(k in title for k in ["종료", "품절", "마감", "완료", "끌올"])

# 1. 아카라이브 핫딜 채널 (arca.live/b/hotdeal)
def fetch_arcalive():
    items = []
    url = "https://arca.live/b/hotdeal"
    try:
        html = get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("div.list-table a.vrow.hybrid, div.list-table a.vrow.column")
        for row in rows:
            if "notice" in row.get("class", []):
                continue
            title_el = row.select_one("span.title")
            if not title_el:
                continue
            badge_el = row.select_one("span.badge")
            badge = f"[{badge_el.get_text().strip()}] " if badge_el else ""
            title = clean_title(badge + title_el.get_text())
            if not title or is_expired(title) or "공지" in title:
                continue
            href = row.get("href", "")
            link = f"https://arca.live{href.split('?')[0]}" if href.startswith("/") else href
            rate_el = row.select_one("span.vcol.col-rate")
            rate = rate_el.get_text().strip() if rate_el else ""
            metric = f"추천 {rate}" if rate and rate != "0" else "핫딜"
            items.append({
                "title": title,
                "url": link,
                "source": "아카라이브",
                "category": classify_category(title),
                "metric": metric,
                "time": "실시간"
            })
            if len(items) >= 20:
                break
    except Exception as e:
        print(f"[오류] 아카라이브 수집 실패: {e}")
    return items

# 2. 퀘이사존 지름/할인정보
def fetch_quasarzone():
    items = []
    url = "https://quasarzone.com/bbs/qb_saleinfo"
    try:
        html = get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("div.market-info-list-cont")
        for row in rows[:20]:
            title_el = row.select_one("p.tit a.subject-link")
            if not title_el:
                continue
            title = clean_title(title_el.get_text())
            if not title or is_expired(title):
                continue
            href = title_el.get("href", "")
            link = f"https://quasarzone.com{href}" if href.startswith("/") else href
            price_el = row.select_one("span.text-orange")
            metric = price_el.get_text().strip() if price_el else "특가"
            items.append({
                "title": title,
                "url": link,
                "source": "퀘이사존",
                "category": "전자/PC",
                "metric": metric,
                "time": "최신"
            })
    except Exception as e:
        print(f"[오류] 퀘이사존 수집 실패: {e}")
    return items

# 3. 어미새 패션/직구 핫딜
def fetch_eomisae():
    items = []
    url = "https://eomisae.co.kr/fs"
    try:
        html = get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("h3.p_title a, td.title a.hx")[:20]:
            title = clean_title(a.get_text())
            if not title or is_expired(title) or "공지" in title:
                continue
            href = a.get("href", "")
            link = f"https://eomisae.co.kr{href}" if href.startswith("/") else href
            items.append({
                "title": title,
                "url": link,
                "source": "어미새",
                "category": "패션/의류",
                "metric": "패션딜",
                "time": "최신"
            })
    except Exception as e:
        print(f"[오류] 어미새 수집 실패: {e}")
    return items

# 4. 쿨엔조이 지름/알뜰정보
def fetch_coolenjoy():
    items = []
    url = "https://coolenjoy.net/bbs/jirum"
    try:
        html = get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        for row in soup.select("div.na-table div.d-md-table-row")[:20]:
            a = row.select_one("a.na-subject")
            if not a:
                continue
            title = clean_title(a.get_text())
            if not title or is_expired(title) or "공지" in title:
                continue
            link = a.get("href", "")
            items.append({
                "title": title,
                "url": link,
                "source": "쿨엔조이",
                "category": classify_category(title),
                "metric": "특가",
                "time": "최신"
            })
    except Exception as e:
        print(f"[오류] 쿨엔조이 수집 실패: {e}")
    return items

# 5. 루리웹 핫딜 (RSS)
def fetch_ruliweb():
    items = []
    url = "https://bbs.ruliweb.com/market/board/1020/rss"
    try:
        xml_text = get_html(url)
        root = ET.fromstring(xml_text.encode("utf-8"))
        for item in root.findall("./channel/item")[:20]:
            title = clean_title(item.findtext("title", ""))
            link = item.findtext("link", "")
            if not title or is_expired(title):
                continue
            items.append({
                "title": title,
                "url": link,
                "source": "루리웹",
                "category": classify_category(title),
                "metric": "핫딜",
                "time": "실시간"
            })
    except Exception as e:
        print(f"[오류] 루리웹 수집 실패: {e}")
    return items

# 6. 클리앙 알뜰구매
def fetch_clien():
    items = []
    url = "https://www.clien.net/service/board/jirum"
    try:
        html = get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        for row in soup.select("div.list_item.symph_row")[:20]:
            title_el = row.select_one("span.list_subject a.list_subject") or row.select_one("a.list_subject")
            if not title_el:
                continue
            title = clean_title(title_el.get_text())
            if not title or is_expired(title):
                continue
            href = title_el.get("href", "")
            link = f"https://www.clien.net{href}" if href.startswith("/") else href
            items.append({
                "title": title,
                "url": link,
                "source": "클리앙",
                "category": classify_category(title),
                "metric": "인기",
                "time": "최신"
            })
    except Exception as e:
        print(f"[오류] 클리앙 수집 실패: {e}")
    return items

# 7. 뽐뿌 뽐뿌게시판
def fetch_ppomppu():
    items = []
    url = "https://m.ppomppu.co.kr/new/bbs_list.php?id=ppomppu"
    try:
        html = get_html(url, encoding="euc-kr")
        soup = BeautifulSoup(html, "html.parser")
        for a in (soup.select("ul.bbsList li a.list_b_01n") or soup.select("a.noeffect"))[:20]:
            title_el = a.select_one("span.title") or a.select_one("strong")
            title = clean_title(title_el.get_text() if title_el else a.get_text())
            if not title or len(title) < 5 or is_expired(title):
                continue
            href = a.get("href", "")
            if "bbs_view.php" not in href:
                continue
            link = f"https://m.ppomppu.co.kr/new/{href.lstrip('/')}" if not href.startswith("http") else href
            items.append({
                "title": title,
                "url": link,
                "source": "뽐뿌",
                "category": classify_category(title),
                "metric": "특가",
                "time": "최신"
            })
    except Exception as e:
        print(f"[오류] 뽐뿌 수집 실패: {e}")
    return items

def interleave_lists(lists):
    """7개 사이트 글을 골고루 1개씩 지그재그로 교차 배치"""
    result = []
    max_len = max((len(lst) for lst in lists), default=0)
    for i in range(max_len):
        for lst in lists:
            if i < len(lst):
                result.append(lst[i])
    return result

def extract_hot_keywords(items):
    stopwords = {"무료", "무배", "배송", "다양", "할인", "특가", "최대", "카드", "적립", "쿠폰", "만원", "천원", "핫딜"}
    words = []
    for item in items:
        tokens = re.findall(r"[가-힣a-zA-Z0-9]{2,6}", item["title"])
        for t in tokens:
            if not t.isdigit() and t not in stopwords:
                words.append(t)
    return [w for w, _ in Counter(words).most_common(10)] or ["쿠팡", "알리", "네이버", "지마켓"]

def main():
    sources = [
        fetch_arcalive(),
        fetch_quasarzone(),
        fetch_ppomppu(),
        fetch_ruliweb(),
        fetch_clien(),
        fetch_eomisae(),
        fetch_coolenjoy(),
    ]
    
    mixed = interleave_lists(sources)
    seen = set()
    unique_deals = []
    for deal in mixed:
        if deal["url"] not in seen:
            seen.add(deal["url"])
            unique_deals.append(deal)

    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    payload = {
        "updated_at": now_str,
        "keywords": extract_hot_keywords(unique_deals),
        "items": unique_deals[:100]
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[{now_str}] 7개 사이트 총 {len(unique_deals)}개 핫딜 수집 완료.")

if __name__ == "__main__":
    main()
