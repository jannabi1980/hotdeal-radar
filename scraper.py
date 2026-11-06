import json
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests

KST = timezone(timedelta(hours=9))

def get_html(url: str, encoding: str = "utf-8") -> str:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
        "Referer": "https://www.google.co.kr/"
    }
    for browser in ["chrome124", "chrome120", "safari17_0"]:
        try:
            res = cf_requests.get(url, impersonate=browser, headers=headers, timeout=12)
            if res.status_code == 200 and len(res.content) > 500:
                if encoding != "utf-8":
                    return res.content.decode(encoding, errors="replace")
                return res.text
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
    return res.text

def classify_category(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["모니터", "노트북", "그래픽", "rtx", "라데온", "ssd", "nvme", "램", "마우스", "키보드", "충전기", "갤럭시", "아이폰", "아이패드", "맥북", "tv", "청소기", "가전", "스팀", "ps5", "ps4", "닌텐도", "스위치", "이어폰", "헤드셋", "에디파이어", "스피커", "요금제", "모바일", "wearos", "android", "케이블", "어댑터"]):
        return "전자/PC"
    if any(k in t for k in ["생수", "커피", "우유", "닭가슴살", "프로틴", "라면", "만두", "과자", "초콜릿", "쌀", "비타민", "유산균", "치약", "샴푸", "물티슈", "세제", "휴지", "돼지", "소고기", "콜라", "사이다", "펩시", "음료", "메가커피", "kfc", "버거", "샌드위치", "브레드", "햇반", "참치", "김치", "견과", "오트밀"]):
        return "식품/생필품"
    if any(k in t for k in ["나이키", "아디다스", "뉴발란스", "맨투맨", "후드", "바지", "자켓", "패딩", "운동화", "슬리퍼", "티셔츠", "언더아머", "셔츠", "코트", "가방", "양말", "크록스", "모자", "데님"]):
        return "패션/의류"
    return "상품권/기타"

def parse_deal_meta(title: str):
    """제목에서 가격(문자열/숫자) 및 무료배송 여부를 자동 추출"""
    free_ship = bool(re.search(r"무배|무료\s*배송|와우\s*무배|무료|free|/무\b", title, re.I))
    price_str = ""
    price_num = None

    # 1순위: 14,900원 / 17200원 패턴
    m_won = re.search(r"(\d{1,3}(?:,\d{3})+|\d{3,7})\s*원", title)
    if m_won:
        raw_num = int(m_won.group(1).replace(",", ""))
        if 100 <= raw_num <= 50000000:
            price_num = raw_num
            price_str = f"{raw_num:,}원"
    else:
        # 2순위: 달러($) 표시
        m_usd = re.search(r"(?:\$\s*(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s*(?:달러|불))", title)
        if m_usd:
            val = m_usd.group(1) or m_usd.group(2)
            price_str = f"${val}"
            price_num = int(float(val) * 1380)

    return price_str, price_num, free_ship

def clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*댓글\s*\d+개.*$", "", text)
    text = re.sub(r"\s*\[\d+\]\s*$", "", text)
    return text.strip()

def is_expired(title: str) -> bool:
    return any(k in title for k in ["종료", "품절", "마감", "완료", "끌올", "공지", "규정", "이용안내", "정보 안내", "블라인드", "필독"])

def build_item(title: str, url: str, source: str):
    price_str, price_num, free_ship = parse_deal_meta(title)
    return {
        "title": title,
        "url": url,
        "source": source,
        "category": classify_category(title),
        "price_str": price_str,
        "price_num": price_num,
        "free_ship": free_ship
    }

# 1. 뽐뿌 핫딜 (EUC-KR 이중 인코딩 깨짐 완벽 해결)
def fetch_ppomppu():
    items = []
    try:
        res = cf_requests.get("https://www.ppomppu.co.kr/rss.php?id=ppomppu", impersonate="chrome120", timeout=12)
        xml_text = res.content.decode("cp949", errors="replace")
        xml_text = re.sub(r'encoding=["\']euc-kr["\']', 'encoding="utf-8"', xml_text, flags=re.I)
        root = ET.fromstring(xml_text.encode("utf-8"))
        for item in root.findall("./channel/item")[:20]:
            title = clean_title(item.findtext("title", ""))
            link = item.findtext("link", "").strip()
            if not title or is_expired(title):
                continue
            items.append(build_item(title, link, "뽐뿌"))
        print(f"[성공] 뽐뿌: {len(items)}개")
    except Exception as e:
        print(f"[오류] 뽐뿌: {e}")
    return items

# 2. 이토랜드 핫딜 (신규 추가 - 직접 접속 + Jina 이중 백업)
def fetch_etoland():
    items = []
    url = "https://etoland.co.kr/b/hotdeal/list"
    try:
        html = get_html(url, encoding="cp949")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='/b/hotdeal/'], a[href*='bo_table=hotdeal']"):
            href = a.get("href", "").split("?")[0]
            if "/list" in href or not re.search(r"\d+", href):
                continue
            for tag in a.select(".cmt_num, .comment_cnt, .cnt"):
                tag.decompose()
            title = clean_title(a.get_text())
            if len(title) < 6 or is_expired(title):
                continue
            link = href if href.startswith("http") else f"https://etoland.co.kr{href}"
            items.append(build_item(title, link, "이토랜드"))
            if len(items) >= 20:
                break
    except Exception:
        pass

    if not items:
        try:
            md = get_markdown_via_jina(url)
            matches = re.findall(r"\[([^\]]+)\]\((https?://(?:www\.)?etoland\.co\.kr/[^\)]+)\)", md)
            for raw_title, link in matches:
                if "/list" in link or not re.search(r"\d+", link):
                    continue
                title = clean_title(raw_title)
                if len(title) < 6 or is_expired(title):
                    continue
                items.append(build_item(title, link.split("?")[0], "이토랜드"))
                if len(items) >= 20:
                    break
        except Exception as e:
            print(f"[오류] 이토랜드: {e}")

    print(f"[성공] 이토랜드: {len(items)}개")
    return items

# 3. 클리앙 알뜰구매 (닉네임·날짜·조회수 찌꺼기 완벽 제거)
def fetch_clien():
    items = []
    try:
        html = get_html("https://m.clien.net/service/board/jirum")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a.list_subject[href*='/service/board/jirum/']"):
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

            if len(title) < 6 or is_expired(title):
                continue
            items.append(build_item(title, f"https://www.clien.net{href}", "클리앙"))
            if len(items) >= 20:
                break
        print(f"[성공] 클리앙: {len(items)}개")
    except Exception as e:
        print(f"[오류] 클리앙: {e}")
    return items

# 4. 루리웹 핫딜 (RSS)
def fetch_ruliweb():
    items = []
    try:
        xml_text = get_html("https://bbs.ruliweb.com/market/board/1020/rss")
        root = ET.fromstring(xml_text.encode("utf-8"))
        for item in root.findall("./channel/item")[:20]:
            title = clean_title(item.findtext("title", ""))
            link = item.findtext("link", "").strip()
            if not title or is_expired(title):
                continue
            items.append(build_item(title, link, "루리웹"))
        print(f"[성공] 루리웹: {len(items)}개")
    except Exception as e:
        print(f"[오류] 루리웹: {e}")
    return items

# 5. 딜바다 국내핫딜 (댓글수 꼬리표 및 이용안내 공지 제거)
def fetch_dealbada():
    items = []
    try:
        html = get_html("https://www.dealbada.com/bbs/board.php?bo_table=deal_domestic")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='bo_table=deal_domestic&wr_id=']"):
            for cnt_span in a.select("span.cnt_cmt, span.sound_only"):
                cnt_span.decompose()
            title = clean_title(a.get_text())
            if len(title) < 6 or is_expired(title):
                continue
            href = a.get("href", "")
            link = href if href.startswith("http") else f"https://www.dealbada.com/bbs/{href.lstrip('/')}"
            items.append(build_item(title, link, "딜바다"))
            if len(items) >= 20:
                break
        print(f"[성공] 딜바다: {len(items)}개")
    except Exception as e:
        print(f"[오류] 딜바다: {e}")
    return items

# 6. 어미새 패션/직구 핫딜
def fetch_eomisae():
    items = []
    try:
        html = get_html("https://eomisae.co.kr/fs")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='/fs/']"):
            href = a.get("href", "").split("?")[0]
            if not re.search(r"/fs/\d+$", href):
                continue
            title = clean_title(a.get_text())
            if len(title) < 6 or is_expired(title):
                continue
            link = href if href.startswith("http") else f"https://eomisae.co.kr{href}"
            item = build_item(title, link, "어미새")
            item["category"] = "패션/의류"
            items.append(item)
            if len(items) >= 20:
                break
        print(f"[성공] 어미새: {len(items)}개")
    except Exception as e:
        print(f"[오류] 어미새: {e}")
    return items

# 7. 퀘이사존 지름/할인정보 (우회 게이트웨이)
def fetch_quasarzone():
    items = []
    try:
        md = get_markdown_via_jina("https://quasarzone.com/bbs/qb_saleinfo")
        matches = re.findall(r"\[([^\]]+)\]\((https://quasarzone\.com/bbs/qb_saleinfo/views/\d+[^\)]*)\)", md)
        for raw_title, link in matches:
            title = clean_title(raw_title)
            if len(title) < 6 or is_expired(title) or title in ["진행중", "종료"]:
                continue
            items.append(build_item(title, link.split("?")[0], "퀘이사존"))
            if len(items) >= 20:
                break
        print(f"[성공] 퀘이사존: {len(items)}개")
    except Exception as e:
        print(f"[오류] 퀘이사존: {e}")
    return items

# 8. 아카라이브 핫딜 (우회 게이트웨이)
def fetch_arcalive():
    items = []
    try:
        md = get_markdown_via_jina("https://arca.live/b/hotdeal")
        matches = re.findall(r"\[([^\]]+)\]\((https://arca\.live/b/hotdeal/\d+[^\)]*)\)", md)
        for raw_title, link in matches:
            title = clean_title(raw_title)
            if len(title) < 6 or is_expired(title):
                continue
            items.append(build_item(title, link.split("?")[0], "아카라이브"))
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
    """의미 없는 일반 명사를 배제하고 대괄호[쇼핑몰] 및 주요 브랜드/품목만 정밀 추출"""
    stopwords = {
        "무료", "무배", "배송", "다양", "할인", "특가", "최대", "카드", "적립", "쿠폰",
        "만원", "천원", "핫딜", "예약", "가격", "인하", "판매", "전용", "진행중", "국내",
        "상품정보", "이벤트정보", "알리정보", "일시", "세일", "시리즈", "와우", "로켓", "오늘"
    }
    words = []
    for item in items:
        # 1순위: 대괄호 [쇼핑몰/브랜드] 추출 (가중치 2배)
        brackets = re.findall(r"\[([가-힣a-zA-Z0-9]{2,8})\]", item["title"])
        for b in brackets:
            if not b.isdigit() and b not in stopwords:
                words.extend([b, b])
        # 2순위: 본문 주요 명사 추출
        tokens = re.findall(r"[가-힣a-zA-Z]{2,6}", item["title"])
        for t in tokens:
            if t not in stopwords:
                words.append(t)
    return [w for w, _ in Counter(words).most_common(10)] or ["쿠팡", "알리", "네이버", "지마켓", "11번가"]

def main():
    sources = [
        fetch_ppomppu(),
        fetch_etoland(),
        fetch_clien(),
        fetch_ruliweb(),
        fetch_dealbada(),
        fetch_eomisae(),
        fetch_quasarzone(),
        fetch_arcalive(),
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
        "items": unique_deals[:130]  # 기본 80개 노출 + 더보기 50개용 총 130개 저장
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[{now_str}] 8개 사이트 최종 통합 {len(unique_deals)}개 핫딜 저장 완료.")

if __name__ == "__main__":
    main()
