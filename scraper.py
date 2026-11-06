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
    """바이트 데이터를 분석해 UTF-8과 CP949(EUC-KR) 중 깨지지 않는 인코딩으로 자동 해독"""
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
    """기존 data.json에서 URL별 최초 수집 시각(timestamp)을 읽어와 시간 계산 유지"""
    if not os.path.exists("data.json"):
        return {}
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return {item["url"]: item.get("timestamp") for item in data.get("items", []) if item.get("timestamp")}
    except Exception:
        return {}

def parse_time_to_ts(raw_time: str, now_ts: int) -> int:
    """사이트별 시간 문자열('5분 전', '14:30', RFC822 등)을 Unix Timestamp(초)로 변환"""
    if not raw_time:
        return now_ts
    s = raw_time.strip()

    # 1. RFC 822 (RSS pubDate 포맷)
    try:
        dt = parsedate_to_datetime(s)
        return int(dt.timestamp())
    except Exception:
        pass

    # 2. '방금', 'N분 전', 'N시간 전'
    if "방금" in s or "초 전" in s:
        return now_ts - 30
    m_min = re.search(r"(\d+)\s*분\s*전", s)
    if m_min:
        return now_ts - int(m_min.group(1)) * 60
    m_hr = re.search(r"(\d+)\s*시간\s*전", s)
    if m_hr:
        return now_ts - int(m_hr.group(1)) * 3600

    # 3. 'HH:MM' (오늘 작성된 글 시각)
    m_hm = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
    if m_hm:
        now_dt = datetime.now(KST)
        dt = now_dt.replace(hour=int(m_hm.group(1)), minute=int(m_hm.group(2)), second=0, microsecond=0)
        if dt > now_dt:
            dt -= timedelta(days=1)
        return int(dt.timestamp())

    return now_ts

def format_rel_time(ts: int, now_ts: int) -> str:
    """서버 측 기본 상대 시간 문자열 생성"""
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
    if any(k in t for k in ["모니터", "노트북", "그래픽", "rtx", "라데온", "ssd", "nvme", "램", "마우스", "키보드", "충전기", "갤럭시", "아이폰", "아이패드", "맥북", "tv", "청소기", "가전", "스팀", "ps5", "ps4", "닌텐도", "스위치", "이어폰", "헤드셋", "에디파이어", "스피커", "요금제", "모바일", "케이블", "어댑터"]):
        return "전자/PC"
    if any(k in t for k in ["생수", "커피", "우유", "닭가슴살", "프로틴", "라면", "만두", "과자", "초콜릿", "빼빼로", "쌀", "비타민", "유산균", "치약", "샴푸", "물티슈", "세제", "휴지", "돼지", "소고기", "콜라", "사이다", "펩시", "음료", "메가커피", "kfc", "버거", "샌드위치", "브레드", "빵", "감귤", "햇반", "참치", "김치"]):
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
    # 1. &amp; 등 HTML 특수문자 엔티티 복원
    text = html_lib.unescape(text)
    # 2. 마크다운 볼드(**) 기호 제거
    text = text.replace("*", "")
    text = re.sub(r"\s+", " ", text).strip()
    # 3. 댓글수 및 뒤에 붙은 날짜/조회수 찌꺼기 제거
    text = re.sub(r"\s*댓글\s*\d+개.*$", "", text)
    text = re.sub(r"\s*\[\d+\]\s*$", "", text)
    text = re.sub(r"\s+20\d{2}\.\d{2}\.\d{2}.*$", "", text)
    # 4. 아카라이브 등 끝에 붙는 '(댓글수,추천수L시간)' 패턴 제거 (예: (3950,54L15))
    text = re.sub(r"\s*\(\d+,\d+L\d+\)\s*$", "", text)
    return text.strip()

def is_expired_or_notice(title: str) -> bool:
    # 깨진 문자()가 포함된 글은 즉시 차단
    if "" in title:
        return True
    bad_words = [
        "종료", "품절", "마감", "완료", "끌올", "공지", "규정", "이용안내", "이용 안내",
        "정보 안내", "블라인드", "필독", "notice", "인기글 이벤트", "포인트 이벤트", "채널 알림"
    ]
    t_low = title.lower()
    return any(k in t_low for k in bad_words)

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

# 1. 뽐뿌 핫딜 (스마트 인코딩 감지 + pubDate 시간 추출)
def fetch_ppomppu(prev_map, now_ts):
    items = []
    try:
        res = cf_requests.get("https://www.ppomppu.co.kr/rss.php?id=ppomppu", impersonate="chrome120", timeout=12)
        xml_text = smart_decode(res.content)
        xml_text = re.sub(r'encoding=["\'][^"\']+["\']', 'encoding="utf-8"', xml_text, flags=re.I)
        root = ET.fromstring(xml_text.encode("utf-8"))
        for idx, item in enumerate(root.findall("./channel/item")[:20]):
            title = clean_title(item.findtext("title", ""))
            link = item.findtext("link", "").strip()
            pub_date = item.findtext("pubDate", "")
            if not title or is_expired_or_notice(title):
                continue
            obj = build_item(title, link, "뽐뿌", pub_date, prev_map, now_ts - idx * 45)
            items.append(obj)
        print(f"[성공] 뽐뿌: {len(items)}개")
    except Exception as e:
        print(f"[오류] 뽐뿌: {e}")
    return items

# 2. 루리웹 핫딜 (RSS + pubDate 실제 시간 추출 + &amp; 해독)
def fetch_ruliweb(prev_map, now_ts):
    items = []
    try:
        res = cf_requests.get("https://bbs.ruliweb.com/market/board/1020/rss", impersonate="chrome120", timeout=12)
        xml_text = smart_decode(res.content)
        root = ET.fromstring(xml_text.encode("utf-8"))
        for idx, item in enumerate(root.findall("./channel/item")[:20]):
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

# 3. 클리앙 알뜰구매 (작성 시간 추출)
def fetch_clien(prev_map, now_ts):
    items = []
    try:
        html = get_html("https://m.clien.net/service/board/jirum")
        soup = BeautifulSoup(html, "html.parser")
        for idx, row in enumerate(soup.select("div.list_item, a.list_subject")):
            a = row if row.name == "a" else row.select_one("a.list_subject")
            if not a:
                continue
            href = a.get("href", "").split("?")[0]
            if not re.search(r"/jirum/\d+$", href):
                continue
            subj_span = a.select_one("span.list_subject")
            if subj_span:
                for tag in subj_span.select(".shortname, .category, .icon_info"):
                    tag.decompose()
                raw_title = subj_span.get_text()
            else:
                raw_title = a.get_text()

            title = clean_title(raw_title)
            title = re.sub(r"\s+\d+\s+\d*\s*(상품정보|이벤트정보|알리정보|해외구매정보).*$", "", title)
            title = re.sub(r"^\d+\s+(?=\[|[가-힣a-zA-Z])", "", title)

            if len(title) < 6 or is_expired_or_notice(title):
                continue

            time_el = row.select_one("span.timestamp, span.time")
            raw_time = time_el.get_text() if time_el else ""
            url = f"https://www.clien.net{href}"
            items.append(build_item(title, url, "클리앙", raw_time, prev_map, now_ts - idx * 90))
            if len(items) >= 20:
                break
        print(f"[성공] 클리앙: {len(items)}개")
    except Exception as e:
        print(f"[오류] 클리앙: {e}")
    return items

# 4. 딜바다 국내핫딜
def fetch_dealbada(prev_map, now_ts):
    items = []
    try:
        html = get_html("https://www.dealbada.com/bbs/board.php?bo_table=deal_domestic")
        soup = BeautifulSoup(html, "html.parser")
        for idx, tr in enumerate(soup.select("div.tbl_head01 tbody tr")):
            # 상단 공지 행 제외
            if "bo_notice" in (tr.get("class") or []):
                continue
            a = tr.select_one("a[href*='bo_table=deal_domestic&wr_id=']")
            if not a:
                continue
            for cnt_span in a.select("span.cnt_cmt, span.sound_only"):
                cnt_span.decompose()
            title = clean_title(a.get_text())
            if len(title) < 6 or is_expired_or_notice(title):
                continue
            href = a.get("href", "")
            link = href if href.startswith("http") else f"https://www.dealbada.com/bbs/{href.lstrip('/')}"
            time_td = tr.select_one("td.td_datetime")
            raw_time = time_td.get_text() if time_td else ""
            items.append(build_item(title, link, "딜바다", raw_time, prev_map, now_ts - idx * 75))
            if len(items) >= 20:
                break
        print(f"[성공] 딜바다: {len(items)}개")
    except Exception as e:
        print(f"[오류] 딜바다: {e}")
    return items

# 5. 어미새 패션/직구 핫딜 (상단 이벤트 공지 완벽 차단)
def fetch_eomisae(prev_map, now_ts):
    items = []
    try:
        html = get_html("https://eomisae.co.kr/fs")
        soup = BeautifulSoup(html, "html.parser")
        for idx, a in enumerate(soup.select("div.card_content h3 a, td.title a.hx")):
            href = a.get("href", "").split("?")[0]
            if not re.search(r"/fs/\d+$", href):
                continue
            title = clean_title(a.get_text())
            if len(title) < 8 or is_expired_or_notice(title):
                continue
            link = href if href.startswith("http") else f"https://eomisae.co.kr{href}"
            obj = build_item(title, link, "어미새", "", prev_map, now_ts - idx * 110)
            obj["category"] = "패션/의류"
            items.append(obj)
            if len(items) >= 20:
                break
        print(f"[성공] 어미새: {len(items)}개")
    except Exception as e:
        print(f"[오류] 어미새: {e}")
    return items

# 6. 이토랜드 핫딜 (UTF-8 스마트 해독으로 외계어 완벽 해결)
def fetch_etoland(prev_map, now_ts):
    items = []
    url = "https://etoland.co.kr/b/hotdeal/list"
    try:
        md = get_markdown_via_jina(url)
        matches = re.findall(r"\[([^\]]+)\]\((https?://(?:www\.)?etoland\.co\.kr/[^\)]+)\)", md)
        for idx, (raw_title, link) in enumerate(matches):
            if "/list" in link or not re.search(r"\d+", link):
                continue
            title = clean_title(raw_title)
            if len(title) < 8 or is_expired_or_notice(title):
                continue
            clean_link = link.split("?")[0]
            items.append(build_item(title, clean_link, "이토랜드", "", prev_map, now_ts - idx * 80))
            if len(items) >= 20:
                break
        print(f"[성공] 이토랜드: {len(items)}개")
    except Exception as e:
        print(f"[오류] 이토랜드: {e}")
    return items

# 7. 퀘이사존 지름/할인정보
def fetch_quasarzone(prev_map, now_ts):
    items = []
    try:
        md = get_markdown_via_jina("https://quasarzone.com/bbs/qb_saleinfo")
        matches = re.findall(r"\[([^\]]+)\]\((https://quasarzone\.com/bbs/qb_saleinfo/views/\d+[^\)]*)\)", md)
        for idx, (raw_title, link) in enumerate(matches):
            title = clean_title(raw_title)
            if len(title) < 8 or is_expired_or_notice(title) or title in ["진행중", "종료"]:
                continue
            items.append(build_item(title, link.split("?")[0], "퀘이사존", "", prev_map, now_ts - idx * 95))
            if len(items) >= 20:
                break
        print(f"[성공] 퀘이사존: {len(items)}개")
    except Exception as e:
        print(f"[오류] 퀘이사존: {e}")
    return items

# 8. 아카라이브 핫딜 (Notice 공지사항 및 괄호 꼬리표 완벽 제거)
def fetch_arcalive(prev_map, now_ts):
    items = []
    try:
        md = get_markdown_via_jina("https://arca.live/b/hotdeal")
        matches = re.findall(r"\[([^\]]+)\]\((https://arca\.live/b/hotdeal/\d+[^\)]*)\)", md)
        for idx, (raw_title, link) in enumerate(matches):
            if "notice" in raw_title.lower() or "이용 안내" in raw_title or "이용안내" in raw_title:
                continue
            title = clean_title(raw_title)
            if len(title) < 8 or is_expired_or_notice(title):
                continue
            items.append(build_item(title, link.split("?")[0], "아카라이브", "", prev_map, now_ts - idx * 70))
            if len(items) >= 20:
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
    """깨진 글자를 원천 차단하고 검증된 쇼핑몰 및 정상 한글/영문 명사만 추출"""
    stopwords = {
        "무료", "무배", "배송", "다양", "할인", "특가", "최대", "카드", "적립", "쿠폰",
        "만원", "천원", "핫딜", "예약", "가격", "인하", "판매", "전용", "진행중", "국내",
        "상품정보", "이벤트정보", "알리정보", "일시", "세일", "시리즈", "와우", "로켓", "오늘",
        "자사몰", "합30개", "작품", "신작", "모음"
    }
    words = []
    for item in items:
        brackets = re.findall(r"\[([가-힣a-zA-Z0-9]{2,8})\]", item["title"])
        for b in brackets:
            if not b.isdigit() and b not in stopwords:
                words.extend([b, b])
        tokens = re.findall(r"[가-힣]{2,6}", item["title"])
        for t in tokens:
            if t not in stopwords:
                words.append(t)
    return [w for w, _ in Counter(words).most_common(10)] or ["쿠팡", "알리", "네이버", "지마켓", "11번가"]

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
        "items": unique_deals[:130]
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[{now_str}] 8개 사이트 최종 통합 {len(unique_deals)}개 핫딜 저장 완료.")

if __name__ == "__main__":
    main()
