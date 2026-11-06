import json
import os
import re
import html as html_lib
from collections import Counter
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests

KST = timezone(timedelta(hours=9))

def smart_decode(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp949", errors="replace")

def get_html(url: str) -> str:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
        "Referer": "https://www.google.co.kr/"
    }
    for browser in ["chrome124", "chrome120", "safari17_0"]:
        try:
            res = cf_requests.get(url, impersonate=browser, headers=headers, timeout=12)
            if res.status_code == 200 and len(res.content) > 500:
                return smart_decode(res.content)
        except Exception:
            continue
    raise RuntimeError(f"접속 차단: {url}")

def get_markdown_via_jina(url: str) -> str:
    jina_url = f"https://r.jina.ai/{url}"
    res = cf_requests.get(
        jina_url,
        headers={"Accept-Language": "ko-KR,ko;q=0.9", "X-Return-Format": "markdown"},
        timeout=20
    )
    res.raise_for_status()
    return smart_decode(res.content)

def load_previous_timestamps() -> dict:
    if not os.path.exists("data.json"):
        return {}
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return {item["url"]: item.get("timestamp") for item in data.get("items", []) if item.get("timestamp")}
    except Exception:
        return {}

def parse_time_to_ts(raw_time: str, now_ts: int) -> int:
    if not raw_time:
        return now_ts
    s = raw_time.strip()
    try:
        dt = parsedate_to_datetime(s)
        return int(dt.timestamp())
    except Exception:
        pass

    if "방금" in s or "초 전" in s:
        return now_ts - 30
    m_min = re.search(r"(\d+)\s*분\s*전", s)
    if m_min:
        return now_ts - int(m_min.group(1)) * 60
    m_hr = re.search(r"(\d+)\s*시간\s*전", s)
    if m_hr:
        return now_ts - int(m_hr.group(1)) * 3600
    m_hm = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
    if m_hm:
        now_dt = datetime.now(KST)
        dt = now_dt.replace(hour=int(m_hm.group(1)), minute=int(m_hm.group(2)), second=0, microsecond=0)
        if dt > now_dt:
            dt -= timedelta(days=1)
        return int(dt.timestamp())
    return now_ts

def format_rel_time(ts: int, now_ts: int) -> str:
    diff = max(0, now_ts - ts)
    if diff < 60:
        return "방금 전"
    if diff < 3600:
        return f"{diff // 60}분 전"
    if diff < 86400:
        return f"{diff // 3600}시간 전"
    return f"{diff // 86400}일 전"

def classify_category(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["모니터", "노트북", "그래픽", "rtx", "라데온", "ssd", "nvme", "램", "마우스", "키보드", "충전기", "갤럭시", "아이폰", "아이패드", "맥북", "tv", "청소기", "가전", "스팀", "ps5", "ps4", "닌텐도", "스위치", "이어폰", "헤드셋", "에디파이어", "스피커", "요금제", "모바일", "케이블", "어댑터", "마우스"]):
        return "전자/PC"
    if any(k in t for k in ["생수", "커피", "우유", "닭가슴살", "프로틴", "라면", "만두", "과자", "초콜릿", "빼빼로", "쌀", "비타민", "유산균", "치약", "샴푸", "물티슈", "세제", "휴지", "돼지", "소고기", "콜라", "사이다", "펩시", "음료", "메가커피", "kfc", "버거", "샌드위치", "브레드", "빵", "감귤", "햇반", "참치", "김치", "물티슈"]):
        return "식품/생필품"
    if any(k in t for k in ["나이키", "아디다스", "뉴발란스", "맨투맨", "후드", "바지", "자켓", "야상", "리바이스", "패딩", "운동화", "슬리퍼", "티셔츠", "언더아머", "셔츠", "코트", "가방", "양말", "크록스", "모자"]):
        return "패션/의류"
    return "상품권/기타"

def parse_deal_meta(title: str):
    free_ship = bool(re.search(r"무배|무료\s*배송|와우\s*무배|무료|free|/무\b", title, re.I))
    price_str = ""
    price_num = None

    m_won = re.search(r"(\d{1,3}(?:,\d{3})+|\d{3,7})\s*원", title)
    if m_won:
        raw_num = int(m_won.group(1).replace(",", ""))
        if 100 <= raw_num <= 50000000:
            price_num = raw_num
            price_str = f"{raw_num:,}원"
    else:
        m_usd = re.search(r"(?:\$\s*(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s*(?:달러|불))", title)
        if m_usd:
            val = m_usd.group(1) or m_usd.group(2)
            price_str = f"${val}"
            price_num = int(float(val) * 1380)

    return price_str, price_num, free_ship

def clean_title(text: str) -> str:
    text = html_lib.unescape(text)
    text = text.replace("*", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*댓글\s*\d+개.*$", "", text)
    text = re.sub(r"\s*\[\d+\]\s*$", "", text)
    text = re.sub(r"\s+20\d{2}\.\d{2}\.\d{2}.*$", "", text)
    text = re.sub(r"\s*\(\d+,\d+L\d+\)\s*$", "", text)
    return text.strip()

def is_expired_or_notice(title: str) -> bool:
    # 종료/품절만 확실히 걸르고 공지는 유연하게 허용
    return any(k in title for k in ["종료된", "품절입니다", "판매종료", "모바일 앱 이용 안내"])

def build_item(title: str, url: str, source: str, raw_time: str, prev_map: dict, now_ts: int):
    price_str, price_num, free_ship = parse_deal_meta(title)
    if raw_time:
        ts = parse_time_to_ts(raw_time, now_ts)
    else:
        ts = prev_map.get(url, now_ts)

    return {
        "title": title,
        "url": url,
        "source": source,
        "category": classify_category(title),
        "price_str": price_str,
        "price_num": price_num,
        "free_ship": free_ship,
        "timestamp": ts,
        "time_str": format_rel_time(ts, now_ts)
    }

def fetch_ppomppu(prev_map, now_ts):
    items = []
    try:
        res = cf_requests.get("https://www.ppomppu.co.kr/rss.php?id=ppomppu", impersonate="chrome120", timeout=12)
        xml_text = smart_decode(res.content)
        xml_text = re.sub(r'encoding=["\'][^"\']+["\']', 'encoding="utf-8"', xml_text, flags=re.I)
        root = ET.fromstring(xml_text.encode("utf-8"))
        for idx, item in enumerate(root.findall("./channel/item")[:25]):
            title = clean_title(item.findtext("title", ""))
            link = item.findtext("link", "").strip()
            pub_date = item.findtext("pubDate", "")
            if not title or is_expired_or_notice(title):
                continue
            items.append(build_item(title, link, "뽐뿌", pub_date, prev_map, now_ts - idx * 45))
        print(f"[성공] 뽐뿌: {len(items)}개")
    except Exception as e:
        print(f"[오류] 뽐뿌: {e}")
    return items

def fetch_ruliweb(prev_map, now_ts):
    items = []
    try:
        res = cf_requests.get("https://bbs.ruliweb.com/market/board/1020/rss", impersonate="chrome120", timeout=12)
        xml_text = smart_decode(res.content)
        root = ET.fromstring(xml_text.encode("utf-8"))
        for idx, item in enumerate(root.findall("./channel/item")[:25]):
            title = clean_title(item.findtext("title", ""))
            link = item.findtext("link", "").strip()
            pub_date = item.findtext("pubDate", "")
            if not title or is_expired_or_notice(title):
                continue
            items.append(build_item(title, link, "루리웹", pub_date, prev_map, now_ts - idx * 60))
        print(f"[성공] 루리웹: {len(items)}개")
    except Exception as e:
        print(f"[오류] 루리웹: {e}")
    return items

def fetch_clien(prev_map, now_ts):
    items = []
    try:
        html = get_html("https://m.clien.net/service/board/jirum")
        soup = BeautifulSoup(html, "html.parser")
        for idx, a in enumerate(soup.select("a.list_subject")):
            href = a.get("href", "").split("?")[0]
            if not re.search(r"/jirum/\d+$", href):
                continue
            title = clean_title(a.get_text())
            if len(title) < 4 or is_expired_or_notice(title):
                continue
            items.append(build_item(title, f"https://www.clien.net{href}", "클리앙", "", prev_map, now_ts - idx * 90))
            if len(items) >= 25:
                break
        print(f"[성공] 클리앙: {len(items)}개")
    except Exception as e:
        print(f"[오류] 클리앙: {e}")
    return items

def fetch_dealbada(prev_map, now_ts):
    items = []
    try:
        html = get_html("https://www.dealbada.com/bbs/board.php?bo_table=deal_domestic")
        soup = BeautifulSoup(html, "html.parser")
        for idx, a in enumerate(soup.select("a[href*='bo_table=deal_domestic&wr_id=']")):
            title = clean_title(a.get_text())
            if len(title) < 4 or is_expired_or_notice(title):
                continue
            href = a.get("href", "")
            link = href if href.startswith("http") else f"https://www.dealbada.com/bbs/{href.lstrip('/')}"
            items.append(build_item(title, link, "딜바다", "", prev_map, now_ts - idx * 75))
            if len(items) >= 25:
                break
        print(f"[성공] 딜바다: {len(items)}개")
    except Exception as e:
        print(f"[오류] 딜바다: {e}")
    return items

def fetch_eomisae(prev_map, now_ts):
    items = []
    try:
        html = get_html("https://eomisae.co.kr/fs")
        soup = BeautifulSoup(html, "html.parser")
        for idx, a in enumerate(soup.select("td.title a.hx, div.card_content h3 a")):
            href = a.get("href", "").split("?")[0]
            if not re.search(r"/fs/\d+$", href):
                continue
            title = clean_title(a.get_text())
            if len(title) < 4 or is_expired_or_notice(title):
                continue
            link = href if href.startswith("http") else f"https://eomisae.co.kr{href}"
            obj = build_item(title, link, "어미새", "", prev_map, now_ts - idx * 110)
            obj["category"] = "패션/의류"
            items.append(obj)
            if len(items) >= 25:
                break
        print(f"[성공] 어미새: {len(items)}개")
    except Exception as e:
        print(f"[오류] 어미새: {e}")
    return items

def fetch_etoland(prev_map, now_ts):
    items = []
    try:
        md = get_markdown_via_jina("https://etoland.co.kr/b/hotdeal/list")
        matches = re.findall(r"\[([^\]]+)\]\((https?://(?:www\.)?etoland\.co\.kr/[^\)]+)\)", md)
        for idx, (raw_title, link) in enumerate(matches):
            if "/list" in link or not re.search(r"\d+", link):
                continue
            title = clean_title(raw_title)
            if len(title) < 4 or is_expired_or_notice(title):
                continue
            items.append(build_item(title, link.split("?")[0], "이토랜드", "", prev_map, now_ts - idx * 80))
            if len(items) >= 25:
                break
        print(f"[성공] 이토랜드: {len(items)}개")
    except Exception as e:
        print(f"[오류] 이토랜드: {e}")
    return items

def fetch_quasarzone(prev_map, now_ts):
    items = []
    try:
        md = get_markdown_via_jina("https://quasarzone.com/bbs/qb_saleinfo")
        matches = re.findall(r"\[([^\]]+)\]\((https://quasarzone\.com/bbs/qb_saleinfo/views/\d+[^\)]*)\)", md)
        for idx, (raw_title, link) in enumerate(matches):
            title = clean_title(raw_title)
            if len(title) < 4 or is_expired_or_notice(title):
                continue
            items.append(build_item(title, link.split("?")[0], "퀘이사존", "", prev_map, now_ts - idx * 95))
            if len(items) >= 25:
                break
        print(f"[성공] 퀘이사존: {len(items)}개")
    except Exception as e:
        print(f"[오류] 퀘이사존: {e}")
    return items

def fetch_arcalive(prev_map, now_ts):
    items = []
    try:
        md = get_markdown_via_jina("https://arca.live/b/hotdeal")
        matches = re.findall(r"\[([^\]]+)\]\((https://arca\.live/b/hotdeal/\d+[^\)]*)\)", md)
        for idx, (raw_title, link) in enumerate(matches):
            title = clean_title(raw_title)
            if len(title) < 4 or is_expired_or_notice(title):
                continue
            items.append(build_item(title, link.split("?")[0], "아카라이브", "", prev_map, now_ts - idx * 70))
            if len(items) >= 25:
                break
        print(f"[성공] 아카라이브: {len(items)}개")
    except Exception as e:
        print(f"[오류] 아카라이브: {e}")
    return items

def interleave_lists(lists):
    result = []
    max_len = max((len(lst) for lst in lists), default=0)
    for i in range(max_len):
        for lst in lists:
            if i < len(lst):
                result.append(lst[i])
    return result

def extract_hot_keywords(items):
    stopwords = {"무료", "무배", "배송", "다양", "할인", "특가", "최대", "카드", "적립", "쿠폰", "만원", "천원", "핫딜", "예약", "가격", "인하", "판매", "전용"}
    words = []
    for item in items:
        tokens = re.findall(r"[가-힣a-zA-Z0-9]{2,8}", item["title"])
        for t in tokens:
            if not t.isdigit() and t not in stopwords:
                words.append(t)
    return [w for w, _ in Counter(words).most_common(10)] or ["쿠팡", "알리", "네이버", "지마켓", "스팀"]

def main():
    now_ts = int(datetime.now(KST).timestamp())
    prev_map = load_previous_timestamps()

    sources = [
        fetch_ppomppu(prev_map, now_ts),
        fetch_etoland(prev_map, now_ts),
        fetch_clien(prev_map, now_ts),
        fetch_ruliweb(prev_map, now_ts),
        fetch_dealbada(prev_map, now_ts),
        fetch_eomisae(prev_map, now_ts),
        fetch_quasarzone(prev_map, now_ts),
        fetch_arcalive(prev_map, now_ts),
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
        "items": unique_deals[:140]
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[{now_str}] 8개 사이트 최종 통합 {len(unique_deals)}개 핫딜 저장 완료.")

if __name__ == "__main__":
    main()
