import json
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests

KST = timezone(timedelta(hours=9))

def get_html(url: str, encoding: str = "utf-8", use_proxy: bool = False) -> str:
    """직접 접속 시도 후 차단 시 우회 게이트웨이를 통해 HTML 확보"""
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
        "Referer": "https://www.google.co.kr/"
    }
    if not use_proxy:
        for browser in ["chrome124", "chrome120", "edge101"]:
            try:
                res = cf_requests.get(url, impersonate=browser, headers=headers, timeout=10)
                if res.status_code == 200 and len(res.text) > 500:
                    if encoding != "utf-8":
                        return res.content.decode(encoding, errors="replace")
                    return res.text
            except Exception:
                continue

    # 직접 접속 차단 시 무료 웹 프록시(AllOrigins / Corsproxy) 경유
    proxy_urls = [
        f"https://api.allorigins.win/raw?url={url}",
        f"https://corsproxy.io/?{url}"
    ]
    for p_url in proxy_urls:
        try:
            res = cf_requests.get(p_url, impersonate="chrome124", timeout=15)
            if res.status_code == 200 and len(res.text) > 500:
                if encoding != "utf-8":
                    return res.content.decode(encoding, errors="replace")
                return res.text
        except Exception:
            continue

    raise RuntimeError(f"접속 차단: {url}")

def get_markdown_via_jina(url: str) -> str:
    """Cloudflare가 강력한 사이트(아카라이브/퀘이사존 등)를 Jina Reader 엔진으로 우회 파싱"""
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
    if any(k in t for k in ["모니터", "노트북", "그래픽", "rtx", "라데온", "ssd", "nvme", "램", "마우스", "키보드", "충전기", "갤럭시", "아이폰", "아이패드", "맥북", "tv", "청소기", "가전", "스팀", "ps5", "ps4", "닌텐도", "스위치", "이어폰", "헤드셋", "에디파이어", "스피커"]):
        return "전자/PC"
    if any(k in t for k in ["생수", "커피", "우유", "닭가슴살", "프로틴", "라면", "만두", "과자", "초콜릿", "쌀", "비타민", "유산균", "치약", "샴푸", "물티슈", "세제", "휴지", "돼지", "소고기", "콜라", "사이다", "펩시", "음료", "메가커피", "kfc", "버거"]):
        return "식품/생필품"
    if any(k in t for k in ["나이키", "아디다스", "뉴발란스", "맨투맨", "후드", "바지", "자켓", "패딩", "운동화", "슬리퍼", "티셔츠", "언더아머", "셔츠", "코트", "가방", "양말"]):
        return "패션/의류"
    return "상품권/기타"

def clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s*\[\d+\]\s*$", "", text)

def is_expired(title: str) -> bool:
    return any(k in title for k in ["종료", "품절", "마감", "완료", "끌올", "공지", "규정", "블라인드"])

# 1. 뽐뿌 핫딜 (RSS)
def fetch_ppomppu():
    items = []
    try:
        xml_bytes = cf_requests.get("https://www.ppomppu.co.kr/rss.php?id=ppomppu", impersonate="chrome120", timeout=12).content
        xml_text = xml_bytes.decode("euc-kr", errors="replace")
        root = ET.fromstring(xml_text)
        for item in root.findall("./channel/item")[:20]:
            title = clean_title(item.findtext("title", ""))
            link = item.findtext("link", "").strip()
            if not title or is_expired(title):
                continue
            items.append({
                "title": title, "url": link, "source": "뽐뿌",
                "category": classify_category(title), "metric": "핫딜", "time": "실시간"
            })
        print(f"[성공] 뽐뿌: {len(items)}개")
    except Exception as e:
        print(f"[오류] 뽐뿌: {e}")
    return items

# 2. 클리앙 알뜰구매
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
                "title": title, "url": f"https://www.clien.net{href}", "source": "클리앙",
                "category": classify_category(title), "metric": "인기", "time": "최신"
            })
            if len(items) >= 20:
                break
        print(f"[성공] 클리앙: {len(items)}개")
    except Exception as e:
        print(f"[오류] 클리앙: {e}")
    return items

# 3. 루리웹 핫딜 (RSS)
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
                "title": title, "url": link, "source": "루리웹",
                "category": classify_category(title), "metric": "핫딜", "time": "실시간"
            })
        print(f"[성공] 루리웹: {len(items)}개")
    except Exception as e:
        print(f"[오류] 루리웹: {e}")
    return items

# 4. 딜바다 국내핫딜
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
                "title": title, "url": link, "source": "딜바다",
                "category": classify_category(title), "metric": "핫딜", "time": "최신"
            })
            if len(items) >= 20:
                break
        print(f"[성공] 딜바다: {len(items)}개")
    except Exception as e:
        print(f"[오류] 딜바다: {e}")
    return items

# 5. 어미새 패션/직구 핫딜 (URL 패턴 파서)
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
            items.append({
                "title": title, "url": link, "source": "어미새",
                "category": "패션/의류", "metric": "패션딜", "time": "최신"
            })
            if len(items) >= 20:
                break
        print(f"[성공] 어미새: {len(items)}개")
    except Exception as e:
        print(f"[오류] 어미새: {e}")
    return items

# 6. 퀘이사존 지름/할인정보 (우회 게이트웨이 경유)
def fetch_quasarzone():
    items = []
    try:
        md = get_markdown_via_jina("https://quasarzone.com/bbs/qb_saleinfo")
        # 마크다운 링크 패턴 [제목](https://quasarzone.com/bbs/qb_saleinfo/views/숫자) 추출
        matches = re.findall(r"\[([^\]]+)\]\((https://quasarzone\.com/bbs/qb_saleinfo/views/\d+[^\)]*)\)", md)
        for raw_title, link in matches:
            title = clean_title(raw_title)
            if len(title) < 6 or is_expired(title) or "진행중" == title:
                continue
            clean_link = link.split("?")[0]
            items.append({
                "title": title, "url": clean_link, "source": "퀘이사존",
                "category": classify_category(title), "metric": "특가", "time": "최신"
            })
            if len(items) >= 20:
                break
        print(f"[성공] 퀘이사존(우회): {len(items)}개")
    except Exception as e:
        print(f"[오류] 퀘이사존: {e}")
    return items

# 7. 아카라이브 핫딜 (우회 게이트웨이 경유)
def fetch_arcalive():
    items = []
    try:
        md = get_markdown_via_jina("https://arca.live/b/hotdeal")
        matches = re.findall(r"\[([^\]]+)\]\((https://arca\.live/b/hotdeal/\d+[^\)]*)\)", md)
        for raw_title, link in matches:
            title = clean_title(raw_title)
            if len(title) < 6 or is_expired(title):
                continue
            clean_link = link.split("?")[0]
            items.append({
                "title": title, "url": clean_link, "source": "아카라이브",
                "category": classify_category(title), "metric": "핫딜", "time": "실시간"
            })
            if len(items) >= 20:
                break
        print(f"[성공] 아카라이브(우회): {len(items)}개")
    except Exception as e:
        print(f"[오류] 아카라이브: {e}")
    return items

# 8. 쿨엔조이 지름/알뜰정보 (프록시 우회)
def fetch_coolenjoy():
    items = []
    try:
        md = get_markdown_via_jina("https://coolenjoy.net/bbs/jirum")
        matches = re.findall(r"\[([^\]]+)\]\((https://coolenjoy\.net/bbs/jirum/\d+[^\)]*)\)", md)
        for raw_title, link in matches:
            title = clean_title(raw_title)
            if len(title) < 6 or is_expired(title):
                continue
            clean_link = link.split("?")[0]
            items.append({
                "title": title, "url": clean_link, "source": "쿨엔조이",
                "category": classify_category(title), "metric": "특가", "time": "최신"
            })
            if len(items) >= 20:
                break
        print(f"[성공] 쿨엔조이(우회): {len(items)}개")
    except Exception as e:
        print(f"[오류] 쿨엔조이: {e}")
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
    stopwords = {"무료", "무배", "배송", "다양", "할인", "특가", "최대", "카드", "적립", "쿠폰", "만원", "천원", "핫딜", "예약", "가격", "인하", "판매", "전용", "진행중"}
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
        fetch_clien(),
        fetch_ruliweb(),
        fetch_dealbada(),
        fetch_eomisae(),
        fetch_quasarzone(),
        fetch_arcalive(),
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
        "items": unique_deals[:140]
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[{now_str}] 최종 통합 {len(unique_deals)}개 핫딜 저장 완료.")

if __name__ == "__main__":
    main()
