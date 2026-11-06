import json
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests

KST = timezone(timedelta(hours=9))

def get_html(url: str, encoding: str = "utf-8") -> str:
    """최신 크롬 브라우저 위장 및 레퍼러 헤더 추가로 차단 우회"""
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
        "Referer": "https://www.google.com/"
    }
    for browser in ["chrome124", "chrome120", "safari17_0"]:
        try:
            res = cf_requests.get(url, impersonate=browser, headers=headers, timeout=15)
            if res.status_code == 200:
                if encoding != "utf-8":
                    return res.content.decode(encoding, errors="replace")
                return res.text
        except Exception:
            continue
    raise RuntimeError(f"접속 차단 또는 응답 없음: {url}")

def classify_category(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["모니터", "노트북", "그래픽", "rtx", "라데온", "ssd", "nvme", "램", "마우스", "키보드", "충전기", "갤럭시", "아이폰", "아이패드", "맥북", "tv", "청소기", "가전", "스팀", "ps5", "ps4", "닌텐도", "스위치", "이어폰", "헤드셋", "에디파이어", "스피커"]):
        return "전자/PC"
    if any(k in t for k in ["생수", "커피", "우유", "닭가슴살", "프로틴", "라면", "만두", "과자", "초콜릿", "쌀", "비타민", "유산균", "치약", "샴푸", "물티슈", "세제", "휴지", "돼지", "소고기", "콜라", "사이다", "펩시", "음료", "메가커피", "kfc", "버거"]):
        return "식품/생필품"
    if any(k in t for k in ["나이키", "아디다스", "뉴발란스", "맨투맨", "후드", "바지", "자켓", "패딩", "운동화", "슬리퍼", "티셔츠", "언더아머", "셔츠", "코트", "가방", "양말"]):
        return "패션/의류"
    return "상품권/기타"

def clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # 제목 끝에 붙는 댓글 수 [12] 제거
    return re.sub(r"\s*\[\d+\]\s*$", "", text)

def is_expired(title: str) -> bool:
    return any(k in title for k in ["종료", "품절", "마감", "완료", "끌올", "공지", "규정"])

# 1. 뽐뿌 핫딜 (공식 RSS 우회 + PC 테이블 이중 백업)
def fetch_ppomppu():
    items = []
    # 1순위: 차단 없는 공식 RSS 피드
    try:
        xml_bytes = cf_requests.get("https://www.ppomppu.co.kr/rss.php?id=ppomppu", impersonate="chrome120", timeout=12).content
        xml_text = xml_bytes.decode("euc-kr", errors="replace")
        root = ET.fromstring(xml_text)
        for item in root.findall("./channel/item")[:25]:
            title = clean_title(item.findtext("title", ""))
            link = item.findtext("link", "").strip()
            if not title or is_expired(title):
                continue
            items.append({
                "title": title,
                "url": link,
                "source": "뽐뿌",
                "category": classify_category(title),
                "metric": "핫딜",
                "time": "실시간"
            })
        if items:
            print(f"[성공] 뽐뿌 RSS: {len(items)}개")
            return items
    except Exception as e:
        print(f"[우회] 뽐뿌 RSS 실패, 웹 파싱 시도: {e}")

    # 2순위: PC 웹페이지 링크 패턴 추출
    try:
        html = get_html("https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu", encoding="euc-kr")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='view.php?id=ppomppu']"):
            title = clean_title(a.get_text())
            if len(title) < 6 or is_expired(title):
                continue
            href = a.get("href", "")
            link = f"https://www.ppomppu.co.kr/zboard/{href.lstrip('/')}" if not href.startswith("http") else href
            items.append({
                "title": title,
                "url": link,
                "source": "뽐뿌",
                "category": classify_category(title),
                "metric": "특가",
                "time": "최신"
            })
            if len(items) >= 20:
                break
        print(f"[성공] 뽐뿌 웹: {len(items)}개")
    except Exception as e:
        print(f"[오류] 뽐뿌 수집 실패: {e}")
    return items

# 2. 루리웹 핫딜 (RSS)
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
            items.append({
                "title": title,
                "url": link,
                "source": "루리웹",
                "category": classify_category(title),
                "metric": "핫딜",
                "time": "실시간"
            })
        print(f"[성공] 루리웹: {len(items)}개")
    except Exception as e:
        print(f"[오류] 루리웹 수집 실패: {e}")
    return items

# 3. 아카라이브 핫딜 (URL 패턴 기반 만능 파서)
def fetch_arcalive():
    items = []
    try:
        html = get_html("https://arca.live/b/hotdeal")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href^='/b/hotdeal/']"):
            href = a.get("href", "").split("?")[0]
            # 게시글 번호(숫자)로 끝나는 링크만 선별
            if not re.search(r"/b/hotdeal/\d+$", href):
                continue
            if "notice" in (a.get("class") or []):
                continue
            title_el = a.select_one(".title")
            raw_title = title_el.get_text() if title_el else a.get_text()
            title = clean_title(raw_title)
            if len(title) < 6 or is_expired(title):
                continue
            badge_el = a.select_one(".badge")
            if badge_el and badge_el.get_text().strip() not in title:
                title = f"[{badge_el.get_text().strip()}] {title}"
            items.append({
                "title": title,
                "url": f"https://arca.live{href}",
                "source": "아카라이브",
                "category": classify_category(title),
                "metric": "핫딜",
                "time": "실시간"
            })
            if len(items) >= 20:
                break
        print(f"[성공] 아카라이브: {len(items)}개")
    except Exception as e:
        print(f"[오류] 아카라이브 수집 실패: {e}")
    return items

# 4. 퀘이사존 지름/할인정보 (URL 패턴 기반 만능 파서)
def fetch_quasarzone():
    items = []
    try:
        html = get_html("https://quasarzone.com/bbs/qb_saleinfo")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='/bbs/qb_saleinfo/views/']"):
            title_el = a.select_one(".ellipsis-with-reply-cnt")
            title = clean_title(title_el.get_text() if title_el else a.get_text())
            if len(title) < 6 or is_expired(title):
                continue
            href = a.get("href", "").split("?")[0]
            link = f"https://quasarzone.com{href}" if href.startswith("/") else href
            items.append({
                "title": title,
                "url": link,
                "source": "퀘이사존",
                "category": classify_category(title),
                "metric": "특가",
                "time": "최신"
            })
            if len(items) >= 20:
                break
        print(f"[성공] 퀘이사존: {len(items)}개")
    except Exception as e:
        print(f"[오류] 퀘이사존 수집 실패: {e}")
    return items

# 5. 클리앙 알뜰구매 (모바일 + PC URL 패턴 파서)
def fetch_clien():
    items = []
    try:
        html = get_html("https://m.clien.net/service/board/jirum")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='/service/board/jirum/']"):
            href = a.get("href", "").split("?")[0]
            if not re.search(r"/jirum/\d+$", href):
                continue
            title = clean_title(a.get_text())
            if len(title) < 6 or is_expired(title):
                continue
            items.append({
                "title": title,
                "url": f"https://www.clien.net{href}",
                "source": "클리앙",
                "category": classify_category(title),
                "metric": "인기",
                "time": "최신"
            })
            if len(items) >= 20:
                break
        print(f"[성공] 클리앙: {len(items)}개")
    except Exception as e:
        print(f"[오류] 클리앙 수집 실패: {e}")
    return items

# 6. 쿨엔조이 지름/알뜰정보
def fetch_coolenjoy():
    items = []
    try:
        html = get_html("https://coolenjoy.net/bbs/jirum")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='coolenjoy.net/bbs/jirum/']"):
            href = a.get("href", "").split("?")[0]
            if not re.search(r"/jirum/\d+$", href):
                continue
            title = clean_title(a.get_text())
            if len(title) < 6 or is_expired(title):
                continue
            items.append({
                "title": title,
                "url": href,
                "source": "쿨엔조이",
                "category": classify_category(title),
                "metric": "특가",
                "time": "최신"
            })
            if len(items) >= 20:
                break
        print(f"[성공] 쿨엔조이: {len(items)}개")
    except Exception as e:
        print(f"[오류] 쿨엔조이 수집 실패: {e}")
    return items

# 7. 딜바다 국내핫딜
def fetch_dealbada():
    items = []
    try:
        html = get_html("https://www.dealbada.com/bbs/board.php?bo_table=deal_domestic")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='bo_table=deal_domestic&wr_id=']"):
            title = clean_title(a.get_text())
            if len(title) < 6 or is_expired(title):
                continue
            href = a.get("href", "")
            link = href if href.startswith("http") else f"https://www.dealbada.com/bbs/{href.lstrip('/')}"
            items.append({
                "title": title,
                "url": link,
                "source": "딜바다",
                "category": classify_category(title),
                "metric": "핫딜",
                "time": "최신"
            })
            if len(items) >= 20:
                break
        print(f"[성공] 딜바다: {len(items)}개")
    except Exception as e:
        print(f"[오류] 딜바다 수집 실패: {e}")
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
        tokens = re.findall(r"[가-힣a-zA-Z0-9]{2,6}", item["title"])
        for t in tokens:
            if not t.isdigit() and not re.match(r"^\d+원$", t) and t not in stopwords:
                words.append(t)
    return [w for w, _ in Counter(words).most_common(10)] or ["쿠팡", "알리", "네이버", "지마켓"]

def main():
    sources = [
        fetch_ppomppu(),
        fetch_arcalive(),
        fetch_quasarzone(),
        fetch_clien(),
        fetch_ruliweb(),
        fetch_coolenjoy(),
        fetch_dealbada(),
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
        "items": unique_deals[:120]
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[{now_str}] 최종 통합 {len(unique_deals)}개 핫딜 저장 완료.")

if __name__ == "__main__":
    main()
