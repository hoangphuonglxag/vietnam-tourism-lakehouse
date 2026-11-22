# -*- coding: utf-8 -*-
"""
Build the Vietnam Tourism Power BI report (PBIP) end-to-end — Light Executive Theme:
  1. Render crisp Light Executive page backgrounds (HTML -> PNG via Edge headless 2x,
     so Vietnamese text is rasterised with Segoe UI and never breaks in Power BI)
  2. Register custom theme VietnamTourismLight.json + light backgrounds in the report
  3. Ensure all DAX measures & format strings across all 6 tables in the semantic model (TMDL)
  4. Generate all visuals pixel-aligned to the background frames with dark crisp text on white cards
Idempotent: safe to run many times.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(ROOT, "test.Report")
MODEL = os.path.join(ROOT, "test.SemanticModel")
PAGES_DIR = os.path.join(REPORT, "definition", "pages")
RES_DIR = os.path.join(REPORT, "StaticResources", "RegisteredResources")
BG_SRC = os.path.join(ROOT, "assets", "bg_src")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
VC_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.14.0/schema.json"

OBT = "gold_obt_place_360_profile"
PROV = "gold_fct_province_tourism_summary"
CAT = "gold_fct_category_tourism_summary"
YT = "gold_fct_youtube_video_performance"
MON = "gold_fct_place_monthly_growth"
SNAP = "gold_fct_place_snapshot_trajectory"
ALL_GOLD_TABLES = [OBT, PROV, CAT, YT, MON, SNAP]

# Light Executive Palette
TEAL = "#0D9488"   # Teal 600
BLUE = "#0284C7"   # Sky 600
CORAL = "#EA580C"  # Orange 600
GOLD = "#D97706"   # Amber 600
INDIGO = "#4F46E5" # Indigo 600
SLATE_900 = "#0F172A"
SLATE_800 = "#1E293B"
SLATE_700 = "#334155"
SLATE_600 = "#475569"
SLATE_500 = "#64748B"
SLATE_200 = "#E2E8F0"
SLATE_100 = "#F1F5F9"
SLATE_50 = "#F8FAFC"

# ----------------------------------------------------------------------------
# 1. LAYOUT (shared by background renderer and visual generator)
# ----------------------------------------------------------------------------
KPI_Y, KPI_H, KPI_W = 104, 128, 446
KPI_X = [32, 502, 972, 1442]
SLOTS = [
    (1236, "TỈNH / THÀNH", OBT, "province_name"),
    (1570, "NHÓM LOẠI HÌNH", OBT, "primary_category_group"),
]

PAGES = [
    {
        "id": "3b4dcee187a4889c3414", "name": "01 Tổng quan", "no": "01",
        "title": "TỔNG QUAN DU LỊCH", "sub": "Tài nguyên · chất lượng · sức hút truyền thông",
        "kpis": [
            ("🏛️", "ĐIỂM DU LỊCH", "Điểm đến đã kiểm định (OSM)", TEAL, OBT, "Total Places"),
            ("⭐", "ĐÁNH GIÁ GOOGLE", "Tổng lượt đánh giá thực tế", BLUE, OBT, "Total Google Reviews"),
            ("▶️", "LƯỢT XEM YOUTUBE", "Độ phủ truyền thông số", CORAL, OBT, "Total YouTube Views"),
            ("✨", "RATING TRUNG BÌNH", "Có trọng số theo lượt đánh giá", GOLD, OBT, "Weighted Rating"),
        ],
        "panels": [
            ("A", 32, 252, 920, 382, "Quy mô điểm đến theo tỉnh/thành", "Tự động mở rộng khi thu thập thêm tỉnh/thành mới", "obt_place_360", TEAL),
            ("B", 976, 252, 912, 382, "Cơ cấu loại hình du lịch", "Tỷ trọng điểm đến theo nhóm loại hình", "obt_place_360", BLUE),
            ("C", 32, 658, 920, 382, "Bảng năng lực du lịch tỉnh/thành", "Quy mô, chất lượng và điểm đến đầu tàu", "province_summary", GOLD),
            ("D", 976, 658, 912, 382, "Chất lượng trải nghiệm theo loại hình", "Rating có trọng số theo từng loại hình", "category_summary", CORAL),
        ],
    },
    {
        "id": "055bf5eca9e9dca463da", "name": "02 Định vị điểm đến", "no": "02",
        "title": "ĐỊNH VỊ ĐIỂM ĐẾN 360°", "sub": "Trải nghiệm thực tế × sức hút truyền thông số",
        "kpis": [
            ("🏆", "ĐIỂM SÁNG DẪN ĐẦU", "Rating ≥ 4.35 · Lượt xem ≥ 50K", TEAL, OBT, "Leading Hotspots"),
            ("💎", "NGỌC ẨN", "Rating ≥ 4.35 · Lượt xem < 50K", BLUE, OBT, "Hidden Gems"),
            ("⚠️", "BẪY TRUYỀN THÔNG", "Rating < 4.35 · Lượt xem ≥ 50K", CORAL, OBT, "Tourist Traps"),
            ("✨", "RATING TRUNG BÌNH", "Có trọng số theo lượt đánh giá", GOLD, OBT, "Weighted Rating"),
        ],
        "panels": [
            ("A", 32, 252, 1150, 788, "Ma trận định vị điểm đến", "Trục X: log₁₀(lượt xem)  ·  Trục Y: Google rating  ·  Bóng: lượng đánh giá", "4-quadrant", TEAL),
            ("B", 1206, 252, 682, 382, "Vòng đời phát triển điểm đến", "Phân bổ theo giai đoạn phát triển", "development_stage", GOLD),
            ("C", 1206, 658, 682, 382, "Top điểm đến nổi bật", "Xếp theo lượt xem YouTube", "obt_place_360", BLUE),
        ],
    },
    {
        "id": "page_social_buzz_2026", "name": "03 Mạng xã hội", "no": "03",
        "title": "SỨC LAN TỎA MẠNG XÃ HỘI", "sub": "Hiệu quả truyền thông YouTube & nhà sáng tạo",
        "kpis": [
            ("🎬", "VIDEO DU LỊCH", "Video gắn với điểm đến", TEAL, YT, "Video Count"),
            ("👁️", "LƯỢT XEM", "Tổng lượt xem mới nhất", BLUE, YT, "Video Views"),
            ("💬", "BÌNH LUẬN", "Bình luận đã thu thập", CORAL, YT, "Video Comments"),
            ("📹", "KÊNH SÁNG TẠO", "Travel vlogger / KOL / KOC", GOLD, YT, "Channel Count"),
        ],
        "panels": [
            ("A", 32, 252, 760, 788, "Top kênh YouTube theo lượt xem", "Nhà sáng tạo có sức ảnh hưởng lớn nhất", "youtube_channel", CORAL),
            ("B", 816, 252, 1072, 488, "Video du lịch viral nhất", "Lượt xem và thảo luận của khán giả", "video_performance", BLUE),
            ("C", 816, 764, 1072, 276, "Nhịp độ xuất bản video", "Số video mới theo tháng xuất bản", "published_month", TEAL),
        ],
    },
    {
        "id": "page_growth_season_2026", "name": "04 Tăng trưởng", "no": "04",
        "title": "TĂNG TRƯỞNG & XU HƯỚNG", "sub": "Đánh giá, chất lượng và nội dung theo thời gian",
        "kpis": [
            ("📈", "REVIEW MỚI", "Tổng lượt đánh giá phát sinh", TEAL, MON, "New Reviews"),
            ("✨", "RATING THEO THÁNG", "Điểm trung bình các tháng", GOLD, MON, "Avg Monthly Rating"),
            ("🎥", "VIDEO MỚI", "Video xuất bản mới", CORAL, MON, "New Videos"),
            ("📍", "ĐỊA ĐIỂM HOẠT ĐỘNG", "Có hoạt động đánh giá / video", BLUE, MON, "Active Places"),
        ],
        "panels": [
            ("A", 32, 252, 1856, 420, "Lượng review mới & rating trung bình theo năm", "Cột: số review mới  ·  Đường: rating trung bình", "monthly_growth", TEAL),
            ("B", 32, 696, 920, 344, "Cơ cấu cảm xúc đánh giá", "Tích cực · Trung lập · Tiêu cực theo năm", "sentiment", GOLD),
            ("C", 976, 696, 912, 344, "Video mới xuất bản theo năm", "Động lượng nội dung truyền thông", "media_momentum", CORAL),
        ],
    },
]

# ----------------------------------------------------------------------------
# 2. LIGHT EXECUTIVE BACKGROUNDS
# ----------------------------------------------------------------------------
BG_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1920px;height:1080px;overflow:hidden}
body{font-family:'Segoe UI',sans-serif;background:#F1F5F9;position:relative;color:#0F172A;
 background-image:radial-gradient(circle at 6% 0%,rgba(13,148,136,.07),transparent 36%),
 radial-gradient(circle at 96% 100%,rgba(2,132,199,.07),transparent 40%);}
.hdr{position:absolute;left:0;top:0;width:1920px;height:84px;background:#FFFFFF;
 border-bottom:1px solid #E2E8F0;box-shadow:0 4px 16px rgba(15,23,42,.05)}
.hdr-top{position:absolute;left:0;top:0;width:1920px;height:4px;
 background:linear-gradient(90deg,#0D9488 0%,#0284C7 55%,#D97706 100%)}
.logo{position:absolute;left:32px;top:22px;width:44px;height:44px;border-radius:12px;
 background:linear-gradient(135deg,#0D9488,#0284C7);box-shadow:0 4px 12px rgba(13,148,136,.28);
 display:flex;align-items:center;justify-content:center}
.brand{position:absolute;left:90px;top:20px;font-size:19px;font-weight:800;letter-spacing:.7px;color:#0F172A}
.brand b{color:#0D9488;font-weight:800}
.tag{position:absolute;left:90px;top:49px;font-size:12px;color:#475569;letter-spacing:.2px}
.vdiv{position:absolute;left:500px;top:22px;width:1px;height:42px;background:#CBD5E1}
.pno{position:absolute;left:524px;top:18px;font-size:11px;font-weight:700;letter-spacing:2.4px;color:#0D9488}
.ptitle{position:absolute;left:524px;top:37px;font-size:20px;font-weight:700;color:#0F172A;letter-spacing:.3px;white-space:nowrap}
.ptitle span{font-size:13px;font-weight:400;color:#475569;letter-spacing:0;margin-left:12px}
.slot{position:absolute;top:15px;width:310px;height:56px;border-radius:10px;
 background:#F8FAFC;border:1px solid #CBD5E1}
.slot i{position:absolute;left:12px;top:6px;font-style:normal;font-size:10px;font-weight:700;letter-spacing:1.4px;color:#0369A1}
.kpi{position:absolute;border-radius:14px;overflow:hidden;background:#FFFFFF;
 border:1px solid #E2E8F0;box-shadow:0 6px 20px rgba(15,23,42,.06)}
.kpi .bar{position:absolute;left:0;top:0;right:0;height:4px}
.kpi .lb{position:absolute;left:0;right:0;top:16px;text-align:center;font-size:12px;font-weight:700;letter-spacing:1.5px;color:#475569}
.kpi .sb{position:absolute;left:0;right:0;bottom:13px;text-align:center;font-size:12px;font-weight:600}
.pn{position:absolute;border-radius:16px;background:#FFFFFF;
 border:1px solid #E2E8F0;box-shadow:0 6px 22px rgba(15,23,42,.06)}
.pn .dot{position:absolute;left:22px;top:26px;width:9px;height:9px;border-radius:50%}
.pn .t{position:absolute;left:40px;top:16px;font-size:16.5px;font-weight:700;color:#0F172A;white-space:nowrap}
.pn .s{position:absolute;left:40px;top:42px;font-size:12.5px;color:#64748B;white-space:nowrap}
.pn .tg{position:absolute;right:20px;top:19px;font-family:Consolas,monospace;font-size:11px;font-weight:600;color:#334155;
 background:#F1F5F9;border:1px solid #E2E8F0;padding:3px 10px;border-radius:7px}
.pn .ln{position:absolute;left:20px;right:20px;top:70px;height:1px;background:#E2E8F0}
.ft{position:absolute;left:32px;bottom:11px;font-size:11px;color:#64748B}
.ft2{position:absolute;right:32px;bottom:11px;font-size:11px;color:#64748B}
"""

LOGO_SVG = ('<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2.4" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>')


def bg_html(page):
    h = [f"<!DOCTYPE html><html lang='vi'><head><meta charset='utf-8'><style>{BG_CSS}</style></head><body>"]
    h.append("<div class='hdr'><div class='hdr-top'></div>")
    h.append(f"<div class='logo'>{LOGO_SVG}</div>")
    h.append("<div class='brand'>VIETNAM <b>TOURISM</b> INTELLIGENCE</div>")
    h.append("<div class='tag'>Data Lakehouse · Trino × Apache Iceberg · Gold Layer</div>")
    h.append("<div class='vdiv'></div>")
    h.append(f"<div class='pno'>TRANG {page['no']} / 04</div>")
    h.append(f"<div class='ptitle'>{page['title']}<span>{page['sub']}</span></div>")
    for x, label, _, _ in SLOTS:
        h.append(f"<div class='slot' style='left:{x}px'><i>{label}</i></div>")
    h.append("</div>")
    for i, (icon, label, sub, color, _, _) in enumerate(page["kpis"]):
        x = KPI_X[i]
        h.append(f"<div class='kpi' style='left:{x}px;top:{KPI_Y}px;width:{KPI_W}px;height:{KPI_H}px'>"
                 f"<div class='bar' style='background:{color}'></div>"
                 f"<div class='lb'>{icon}&nbsp;&nbsp;{label}</div>"
                 f"<div class='sb' style='color:{color}'>{sub}</div></div>")
    for _, x, y, w, hh, title, sub, tag, color in page["panels"]:
        h.append(f"<div class='pn' style='left:{x}px;top:{y}px;width:{w}px;height:{hh}px'>"
                 f"<div class='dot' style='background:{color}'></div>"
                 f"<div class='t'>{title}</div><div class='s'>{sub}</div>"
                 f"<div class='tg'>{tag}</div><div class='ln'></div></div>")
    h.append("<div class='ft'>Nguồn: Vietnam Tourism Lakehouse · Medallion Bronze → Silver → Gold · Trino ODBC</div>")
    h.append("<div class='ft2'>Đồ án Data Engineering · 2026</div>")
    h.append("</body></html>")
    return "".join(h)


def cleanup_old_resources():
    if not os.path.exists(RES_DIR):
        return
    for fname in os.listdir(RES_DIR):
        if fname.endswith("_dark.png") or fname == "VietnamTourismDark.json":
            os.remove(os.path.join(RES_DIR, fname))


def render_backgrounds():
    os.makedirs(BG_SRC, exist_ok=True)
    os.makedirs(RES_DIR, exist_ok=True)
    cleanup_old_resources()
    names = {}
    for p in PAGES:
        html_path = os.path.join(BG_SRC, f"bg_{p['no']}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(bg_html(p))
        png_name = f"bg_page{p['no']}_light.png"
        png_path = os.path.join(RES_DIR, png_name)
        profile = tempfile.mkdtemp(prefix="edge_bg_")
        cmd = [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               f"--user-data-dir={profile}", "--force-device-scale-factor=2",
               "--window-size=1920,1080", "--default-background-color=00000000",
               f"--screenshot={png_path}", "file:///" + html_path.replace("\\", "/")]
        subprocess.run(cmd, check=True, timeout=120, capture_output=True)
        shutil.rmtree(profile, ignore_errors=True)
        if not os.path.exists(png_path):
            raise RuntimeError(f"Edge failed to render {png_path}")
        names[p["id"]] = png_name
        print(f"[bg] {png_name} ({os.path.getsize(png_path)//1024} KB)")
    return names

# ----------------------------------------------------------------------------
# 3. LIGHT EXECUTIVE THEME
# ----------------------------------------------------------------------------
THEME_NAME = "VietnamTourismLight.json"


def solid(c):
    return {"solid": {"color": c}}


def write_theme():
    theme = {
        "name": "Vietnam Tourism Light Executive",
        "dataColors": [TEAL, BLUE, CORAL, GOLD, INDIGO, "#0891B2", "#10B981", "#F59E0B", "#EF4444", SLATE_500],
        "foreground": SLATE_900,
        "foregroundNeutralSecondary": SLATE_600,
        "foregroundNeutralTertiary": SLATE_500,
        "background": "#FFFFFF",
        "backgroundLight": SLATE_50,
        "backgroundNeutral": SLATE_100,
        "tableAccent": TEAL,
        "good": TEAL,
        "neutral": GOLD,
        "bad": CORAL,
        "maximum": TEAL,
        "center": GOLD,
        "minimum": CORAL,
        "null": SLATE_500,
        "hyperlink": BLUE,
        "visitedHyperlink": INDIGO,
        "textClasses": {
            "callout": {"fontSize": 30, "fontFace": "Segoe UI Semibold", "color": SLATE_900},
            "title": {"fontSize": 13, "fontFace": "Segoe UI Semibold", "color": SLATE_900},
            "header": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": SLATE_900},
            "label": {"fontSize": 10, "fontFace": "Segoe UI", "color": SLATE_700},
        },
        "visualStyles": {
            "*": {"*": {
                "background": [{"show": False}],
                "border": [{"show": False}],
                "dropShadow": [{"show": False}],
                "title": [{"show": False}],
                "categoryAxis": [{"labelColor": solid(SLATE_700), "titleColor": solid(SLATE_600), "fontFamily": "Segoe UI"}],
                "valueAxis": [{"labelColor": solid(SLATE_600), "titleColor": solid(SLATE_600), "gridlineColor": solid(SLATE_200), "fontFamily": "Segoe UI"}],
                "legend": [{"labelColor": solid(SLATE_700), "fontFamily": "Segoe UI"}],
            }},
            "page": {"*": {
                "outspace": [{"color": solid(SLATE_100)}],
                "background": [{"color": solid(SLATE_100), "transparency": 0}],
            }},
            "tableEx": {"*": {
                "grid": [{"gridHorizontal": True, "gridHorizontalColor": solid(SLATE_200),
                          "gridVertical": False, "outlineColor": solid(SLATE_200), "rowPadding": 5}],
                "columnHeaders": [{"fontColor": solid(SLATE_900), "backColor": solid(SLATE_100),
                                   "fontFamily": "Segoe UI Semibold", "fontSize": 10}],
                "values": [{"fontColorPrimary": solid(SLATE_800), "backColorPrimary": solid("#FFFFFF"),
                            "fontColorSecondary": solid(SLATE_800), "backColorSecondary": solid(SLATE_50),
                            "fontFamily": "Segoe UI", "fontSize": 10}],
                "total": [{"fontColor": solid(SLATE_900), "backColor": solid(SLATE_100)}],
            }},
            "slicer": {"*": {
                "items": [{"fontColor": solid(SLATE_900), "background": solid("#FFFFFF"),
                           "fontFamily": "Segoe UI", "textSize": 10}],
                "header": [{"show": False}],
            }},
        },
    }
    os.makedirs(RES_DIR, exist_ok=True)
    with open(os.path.join(RES_DIR, THEME_NAME), "w", encoding="utf-8") as f:
        json.dump(theme, f, indent=2, ensure_ascii=False)
    base_theme_path = os.path.join(REPORT, "StaticResources", "SharedResources", "BaseThemes", "Fluent2-CY26SU10.json")
    if os.path.exists(base_theme_path):
        with open(base_theme_path, encoding="utf-8") as f:
            base_txt = f.read()
        updated_base = re.sub(r'"fontFace"\s*:\s*"DIN"', '"fontFace": "Segoe UI Semibold"', base_txt)
        if updated_base != base_txt:
            with open(base_theme_path, "w", encoding="utf-8", newline="") as f:
                f.write(updated_base)
    print("[theme] VietnamTourismLight.json written")

# ----------------------------------------------------------------------------
# 4. SEMANTIC MODEL (measures + format strings)
# ----------------------------------------------------------------------------
MEASURES = {
    OBT: [
        ("Total Places", "COUNTROWS('gold_obt_place_360_profile')", "#,0"),
        ("Total Google Reviews", "SUM('gold_obt_place_360_profile'[latest_google_review_count])", "#,0"),
        ("Total YouTube Views", "SUM('gold_obt_place_360_profile'[total_youtube_views])", "#,0"),
        ("Weighted Rating",
         "DIVIDE(SUMX('gold_obt_place_360_profile', 'gold_obt_place_360_profile'[latest_google_rating] * 'gold_obt_place_360_profile'[latest_google_review_count]), "
         "SUMX(FILTER('gold_obt_place_360_profile', NOT ISBLANK('gold_obt_place_360_profile'[latest_google_rating])), 'gold_obt_place_360_profile'[latest_google_review_count]))",
         "0.00"),
        ("Avg Rating", "AVERAGE('gold_obt_place_360_profile'[latest_google_rating])", "0.00"),
        ("Media Score", "LOG10(1 + SUM('gold_obt_place_360_profile'[total_youtube_views]))", "0.00"),
        ("Leading Hotspots",
         "COUNTROWS(FILTER('gold_obt_place_360_profile', NOT ISBLANK('gold_obt_place_360_profile'[latest_google_rating]) && 'gold_obt_place_360_profile'[latest_google_rating] >= 4.35 && 'gold_obt_place_360_profile'[total_youtube_views] >= 50000)) + 0",
         "#,0"),
        ("Hidden Gems",
         "COUNTROWS(FILTER('gold_obt_place_360_profile', NOT ISBLANK('gold_obt_place_360_profile'[latest_google_rating]) && 'gold_obt_place_360_profile'[latest_google_rating] >= 4.35 && 'gold_obt_place_360_profile'[total_youtube_views] < 50000)) + 0",
         "#,0"),
        ("Tourist Traps",
         "COUNTROWS(FILTER('gold_obt_place_360_profile', NOT ISBLANK('gold_obt_place_360_profile'[latest_google_rating]) && 'gold_obt_place_360_profile'[latest_google_rating] < 4.35 && 'gold_obt_place_360_profile'[total_youtube_views] >= 50000)) + 0",
         "#,0"),
    ],
    YT: [
        ("Video Count", "DISTINCTCOUNT('gold_fct_youtube_video_performance'[video_id])", "#,0"),
        ("Video Views", "SUM('gold_fct_youtube_video_performance'[latest_views])", "#,0"),
        ("Video Comments", "SUM('gold_fct_youtube_video_performance'[crawled_comment_count])", "#,0"),
        ("Channel Count", "DISTINCTCOUNT('gold_fct_youtube_video_performance'[channel_name])", "#,0"),
    ],
    MON: [
        ("New Reviews", "SUM('gold_fct_place_monthly_growth'[new_reviews_count])", "#,0"),
        ("Avg Monthly Rating", "AVERAGE('gold_fct_place_monthly_growth'[monthly_avg_review_rating])", "0.00"),
        ("New Videos", "SUM('gold_fct_place_monthly_growth'[new_videos_published_count])", "#,0"),
        ("Active Places", "DISTINCTCOUNT('gold_fct_place_monthly_growth'[place_id])", "#,0"),
        ("Positive Reviews", "SUM('gold_fct_place_monthly_growth'[positive_reviews_count])", "#,0"),
        ("Neutral Reviews", "SUM('gold_fct_place_monthly_growth'[neutral_reviews_count])", "#,0"),
        ("Negative Reviews", "SUM('gold_fct_place_monthly_growth'[negative_reviews_count])", "#,0"),
    ],
    CAT: [
        ("Category Rating", "AVERAGE('gold_fct_category_tourism_summary'[category_weighted_avg_rating])", "0.00"),
    ],
}

COLUMN_FORMATS = {
    OBT: {"total_youtube_views": "#,0", "latest_google_review_count": "#,0", "latest_google_rating": "0.00"},
    PROV: {"total_places_count": "#,0", "total_google_review_count": "#,0", "total_youtube_views": "#,0",
           "province_weighted_avg_rating": "0.00", "national_tourism_rank": "0"},
    YT: {"latest_views": "#,0", "crawled_comment_count": "#,0"},
    MON: {"activity_year": "0"},
}


def tmdl_quote(name):
    return f"'{name}'" if re.search(r"[^A-Za-z0-9_]", name) else name


def build_utf8_partition(table, nl):
    return (
        f"\tpartition {table} = m{nl}"
        f"\t\tmode: import{nl}"
        f"\t\tsource ={nl}"
        f"\t\t\t\tlet{nl}"
        f'\t\t\t\t    Source = Odbc.DataSource("dsn=Trino_Lakehouse", [HierarchicalNavigation=true]),{nl}'
        f'\t\t\t\t    iceberg_Database = Source{{[Name="iceberg",Kind="Database"]}}[Data],{nl}'
        f'\t\t\t\t    gold_Schema = iceberg_Database{{[Name="gold",Kind="Schema"]}}[Data],{nl}'
        f'\t\t\t\t    raw_Table = gold_Schema{{[Name="{table}",Kind="Table"]}}[Data],{nl}'
        f"\t\t\t\t    TextCols = Table.ColumnsOfType(raw_Table, {{type text, type nullable text}}),{nl}"
        f"\t\t\t\t    FixedUtf8 = Table.TransformColumns({nl}"
        f"\t\t\t\t        raw_Table,{nl}"
        f"\t\t\t\t        List.Transform({nl}"
        f"\t\t\t\t            TextCols,{nl}"
        f"\t\t\t\t            (c) => {{c, (v) => if v = null then null else let b = Text.ToBinary(v, 1252), u = try Text.FromBinary(b, TextEncoding.Utf8) otherwise v in if Text.Contains(u, Character.FromNumber(65533)) then v else u, type nullable text}}{nl}"
        f"\t\t\t\t        ){nl}"
        f"\t\t\t\t    ){nl}"
        f"\t\t\t\tin{nl}"
        f"\t\t\t\t    FixedUtf8{nl}"
    )


def update_model():
    for table in ALL_GOLD_TABLES:
        measures = MEASURES.get(table, [])
        path = os.path.join(MODEL, "definition", "tables", f"{table}.tmdl")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        nl = "\r\n" if "\r\n" in text else "\n"

        part_pat = re.compile(
            rf"\tpartition {re.escape(table)} = m\r?\n\t\tmode: import\r?\n\t\tsource =\r?\n(?:\t\t\t\t[^\r\n]*\r?\n)+",
            re.M,
        )
        if not part_pat.search(text):
            raise RuntimeError(f"Unexpected M partition block in {path}")
        text = part_pat.sub(lambda _: build_utf8_partition(table, nl), text, count=1)

        block = ""
        for name, expr, fmt in measures:
            if re.search(rf"^\tmeasure {re.escape(tmdl_quote(name))} =", text, re.M):
                continue
            block += (f"\tmeasure {tmdl_quote(name)} = {expr}{nl}"
                      f"\t\tformatString: {fmt}{nl}"
                      f"\t\tlineageTag: {uuid.uuid4()}{nl}{nl}")
        if block:
            m = re.search(r"^table [^\r\n]+\r?\n\tlineageTag: [^\r\n]+\r?\n\r?\n", text, re.M)
            if not m:
                raise RuntimeError(f"Unexpected TMDL header in {path}")
            text = text[:m.end()] + block + text[m.end():]
        for col_name, fmt in COLUMN_FORMATS.get(table, {}).items():
            pat = re.compile(rf"(\tcolumn {col_name}\r?\n\t\tdataType: \w+\r?\n)((?:\t\t[^\r\n]*\r?\n)*)")
            mm = pat.search(text)
            if mm and "formatString" not in mm.group(2):
                text = text[:mm.end(1)] + f"\t\tformatString: {fmt}{nl}" + text[mm.end(1):]
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"[model] {table}: UTF-8 M partition + measures/formats ensured")

# ----------------------------------------------------------------------------
# 5. VISUAL HELPERS (Light Executive Styles)
# ----------------------------------------------------------------------------
def L(v):
    return {"expr": {"Literal": {"Value": v}}}


def C(c):
    return {"solid": {"color": L(f"'{c}'")}}


def TRUE():
    return L("true")


def FALSE():
    return L("false")


def gid():
    return uuid.uuid4().hex[:20]


def col(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def meas(entity, prop):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def p_col(entity, prop, display=None, active=True):
    p = {"field": col(entity, prop), "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if active:
        p["active"] = True
    if display:
        p["displayName"] = display
    return p


def p_meas(entity, prop, display=None):
    p = {"field": meas(entity, prop), "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if display:
        p["displayName"] = display
    return p


def container_off():
    return {
        "background": [{"properties": {"show": FALSE()}}],
        "border": [{"properties": {"show": FALSE()}}],
        "dropShadow": [{"properties": {"show": FALSE()}}],
        "title": [{"properties": {"show": FALSE()}}],
    }


def visual(vtype, x, y, w, h, z, query_state=None, objects=None, sort=None):
    v = {"visualType": vtype}
    if query_state is not None:
        q = {"queryState": query_state}
        if sort:
            q["sortDefinition"] = {"sort": sort}
        v["query"] = q
    if objects:
        v["objects"] = objects
    v["visualContainerObjects"] = container_off()
    v["drillFilterOtherVisuals"] = True
    return {
        "$schema": VC_SCHEMA,
        "name": gid(),
        "position": {"x": float(x), "y": float(y), "z": int(z), "height": float(h),
                     "width": float(w), "tabOrder": int(z)},
        "visual": v,
    }


def inner(panel):
    _, x, y, w, h = panel[:5]
    return x + 16, y + 82, w - 32, h - 94


def axis_objects(cat_font="11D", show_value_axis=False, value_start=None, categorical=False):
    cat = {"labelColor": C(SLATE_700), "fontSize": L(cat_font), "showAxisTitle": FALSE()}
    if categorical:
        cat["axisType"] = L("'Categorical'")
    val = {"show": TRUE() if show_value_axis else FALSE(),
           "gridlineShow": TRUE() if show_value_axis else FALSE(),
           "gridlineColor": C(SLATE_200), "labelColor": C(SLATE_600), "showAxisTitle": FALSE()}
    if value_start is not None:
        val["start"] = L(f"{value_start}D")
    return {"categoryAxis": [{"properties": cat}], "valueAxis": [{"properties": val}]}


def labels(show=True, color=SLATE_900, size="10D"):
    return [{"properties": {"show": TRUE() if show else FALSE(), "color": C(color), "fontSize": L(size)}}]


def kpi_card(i, entity, measure, display, z):
    x = KPI_X[i] + 16
    return visual("card", x, KPI_Y + 36, KPI_W - 32, 62, z,
                  {"Values": {"projections": [p_meas(entity, measure, display)]}},
                  {"labels": [{"properties": {
                      "color": C(SLATE_900),
                      "fontSize": L("30D"),
                      "fontFamily": L("'Segoe UI Semibold'"),
                  }}],
                   "categoryLabels": [{"properties": {"show": FALSE()}}]})


def slicer(slot_x, entity, prop, display, z):
    return visual("slicer", slot_x + 8, 15 + 21, 294, 34, z,
                  {"Values": {"projections": [p_col(entity, prop, display)]}},
                  {"data": [{"properties": {"mode": L("'Dropdown'")}}],
                   "header": [{"properties": {"show": FALSE()}}],
                   "items": [{"properties": {
                       "fontColor": C(SLATE_900),
                       "background": C("#FFFFFF"),
                       "fontFamily": L("'Segoe UI'"),
                       "textSize": L("10D"),
                   }}]})


def bar(panel, cat_entity, cat_prop, cat_disp, m_entity, m_prop, m_disp, color, z,
        vtype="clusteredBarChart", value_start=None, cat_font="11D"):
    x, y, w, h = inner(panel)
    objs = {"dataPoint": [{"properties": {"fill": C(color)}}], "labels": labels(True, SLATE_900, "10D")}
    objs.update(axis_objects(cat_font=cat_font, value_start=value_start))
    return visual(vtype, x, y, w, h, z,
                  {"Category": {"projections": [p_col(cat_entity, cat_prop, cat_disp)]},
                   "Y": {"projections": [p_meas(m_entity, m_prop, m_disp)]}},
                  objs,
                  sort=[{"field": meas(m_entity, m_prop), "direction": "Descending"}])


def table(panel, entity, cols, sort_col, z):
    x, y, w, h = inner(panel)
    return visual("tableEx", x, y, w, h, z,
                  {"Values": {"projections": [p_col(entity, c, d, active=False) for c, d in cols]}},
                  {"columnHeaders": [{"properties": {
                      "fontColor": C(SLATE_900),
                      "backColor": C(SLATE_100),
                      "fontFamily": L("'Segoe UI Semibold'"),
                      "fontSize": L("10D"),
                  }}],
                   "values": [{"properties": {
                       "fontColorPrimary": C(SLATE_800),
                       "backColorPrimary": C("#FFFFFF"),
                       "fontColorSecondary": C(SLATE_800),
                       "backColorSecondary": C(SLATE_50),
                       "fontFamily": L("'Segoe UI'"),
                       "fontSize": L("10D"),
                   }}],
                   "grid": [{"properties": {"gridHorizontalColor": C(SLATE_200), "rowPadding": L("5D")}}]},
                  sort=[{"field": col(entity, sort_col), "direction": "Descending"}])


def series_colors(pairs):
    return [{"properties": {"fill": C(c)}, "selector": {"metadata": qref}} for qref, c in pairs]

# ----------------------------------------------------------------------------
# 6. PAGE BUILDERS
# ----------------------------------------------------------------------------
def common(page):
    vs = []
    for i, (_, label, _, _, ent, m) in enumerate(page["kpis"]):
        vs.append(kpi_card(i, ent, m, label.title(), 1000 + i * 100))
    for j, (sx, label, ent, prop) in enumerate(SLOTS):
        vs.append(slicer(sx, ent, prop, label.title(), 9000 + j * 100))
    return vs


def page1(p):
    A, B, Cc, D = p["panels"]
    vs = common(p)
    vs.append(bar(A, OBT, "province_name", "Tỉnh/Thành", OBT, "Total Places", "Số điểm du lịch", TEAL, 2000))
    x, y, w, h = inner(B)
    vs.append(visual("treemap", x, y, w, h, 2100,
                     {"Group": {"projections": [p_col(OBT, "primary_category_group", "Nhóm loại hình")]},
                      "Values": {"projections": [p_meas(OBT, "Total Places", "Số điểm du lịch")]}},
                     {"legend": [{"properties": {"show": FALSE()}}],
                      "labels": labels(True, "#FFFFFF", "11D"),
                      "categoryLabels": [{"properties": {"show": TRUE(), "color": C("#FFFFFF"), "fontSize": L("12D")}}]},
                     sort=[{"field": meas(OBT, "Total Places"), "direction": "Descending"}]))
    vs.append(table(Cc, PROV, [("province_name", "Tỉnh/Thành"), ("total_places_count", "Điểm du lịch"),
                               ("province_weighted_avg_rating", "Rating TB"),
                               ("total_google_review_count", "Đánh giá"), ("total_youtube_views", "Lượt xem"),
                               ("top_place_name_by_views", "Điểm đến đầu tàu")], "total_places_count", 2200))
    vs.append(bar(D, CAT, "name_vi", "Loại hình", CAT, "Category Rating", "Rating có trọng số", CORAL, 2300,
                  value_start=3, cat_font="10D"))
    return vs


def page2(p):
    A, B, Cc = p["panels"]
    vs = common(p)
    x, y, w, h = inner(A)
    vs.append(visual("scatterChart", x, y, w, h, 2000,
                     {"Category": {"projections": [p_col(OBT, "place_name", "Điểm đến")]},
                      "Series": {"projections": [p_col(OBT, "place_development_stage", "Giai đoạn")]},
                      "X": {"projections": [p_meas(OBT, "Media Score", "Chỉ số truyền thông (log10 lượt xem)")]},
                      "Y": {"projections": [p_meas(OBT, "Avg Rating", "Google rating")]},
                      "Size": {"projections": [p_meas(OBT, "Total Google Reviews", "Lượng đánh giá")]}},
                     {"legend": [{"properties": {"show": TRUE(), "position": L("'Top'"), "labelColor": C(SLATE_700),
                                                 "fontSize": L("10D")}}],
                      "categoryAxis": [{"properties": {"labelColor": C(SLATE_600), "showAxisTitle": TRUE(),
                                                       "titleColor": C(SLATE_700), "gridlineShow": TRUE(),
                                                       "gridlineColor": C(SLATE_200)}}],
                      "valueAxis": [{"properties": {"labelColor": C(SLATE_600), "showAxisTitle": TRUE(),
                                                    "titleColor": C(SLATE_700), "gridlineColor": C(SLATE_200),
                                                    "start": L("1D"), "end": L("5D")}}]}))
    x, y, w, h = inner(B)
    vs.append(visual("donutChart", x, y, w, h, 2100,
                     {"Category": {"projections": [p_col(OBT, "place_development_stage", "Giai đoạn")]},
                      "Y": {"projections": [p_meas(OBT, "Total Places", "Số điểm du lịch")]}},
                     {"legend": [{"properties": {"show": TRUE(), "position": L("'Right'"), "labelColor": C(SLATE_700),
                                                 "fontSize": L("10D")}}],
                      "labels": [{"properties": {"show": TRUE(), "color": C(SLATE_900), "fontSize": L("10D"),
                                                 "labelStyle": L("'Percent of total'")}}]}))
    vs.append(table(Cc, OBT, [("place_name", "Điểm đến"), ("province_name", "Tỉnh"),
                              ("latest_google_rating", "Rating"), ("total_youtube_views", "Lượt xem"),
                              ("place_development_stage", "Giai đoạn")], "total_youtube_views", 2200))
    return vs


def page3(p):
    A, B, Cc = p["panels"]
    vs = common(p)
    vs.append(bar(A, YT, "channel_name", "Kênh", YT, "Video Views", "Lượt xem", CORAL, 2000, cat_font="10D"))
    vs.append(table(B, YT, [("video_title", "Tiêu đề video"), ("channel_name", "Kênh"),
                            ("place_name", "Điểm đến"), ("latest_views", "Lượt xem"),
                            ("crawled_comment_count", "Bình luận")], "latest_views", 2100))
    x, y, w, h = inner(Cc)
    qv = f"{YT}.Video Count"
    vs.append(visual("lineChart", x, y, w, h, 2200,
                     {"Category": {"projections": [p_col(YT, "published_month", "Tháng xuất bản")]},
                      "Y": {"projections": [p_meas(YT, "Video Count", "Số video")]}},
                     dict(axis_objects(show_value_axis=True),
                          dataPoint=series_colors([(qv, BLUE)]),
                          lineStyles=[{"properties": {"strokeWidth": L("3D")}}])))
    return vs


def page4(p):
    A, B, Cc = p["panels"]
    vs = common(p)
    x, y, w, h = inner(A)
    q_rev, q_rat = f"{MON}.New Reviews", f"{MON}.Avg Monthly Rating"
    objs = axis_objects(show_value_axis=True, categorical=True)
    objs["valueAxis"][0]["properties"]["secShow"] = TRUE()
    objs["valueAxis"][0]["properties"]["secLabelColor"] = C(GOLD)
    objs.update({"legend": [{"properties": {"show": TRUE(), "position": L("'Top'"), "labelColor": C(SLATE_700)}}],
                 "dataPoint": series_colors([(q_rev, TEAL), (q_rat, GOLD)]),
                 "lineStyles": [{"properties": {"strokeWidth": L("3D")}}]})
    vs.append(visual("lineClusteredColumnComboChart", x, y, w, h, 2000,
                     {"Category": {"projections": [p_col(MON, "activity_year", "Năm")]},
                      "Y": {"projections": [p_meas(MON, "New Reviews", "Review mới")]},
                      "Y2": {"projections": [p_meas(MON, "Avg Monthly Rating", "Rating trung bình")]}},
                     objs))
    x, y, w, h = inner(B)
    qp, qn, qg = f"{MON}.Positive Reviews", f"{MON}.Neutral Reviews", f"{MON}.Negative Reviews"
    objs = axis_objects(show_value_axis=True, categorical=True, cat_font="10D")
    objs.update({"legend": [{"properties": {"show": TRUE(), "position": L("'Top'"), "labelColor": C(SLATE_700)}}],
                 "dataPoint": series_colors([(qp, TEAL), (qn, GOLD), (qg, CORAL)])})
    vs.append(visual("columnChart", x, y, w, h, 2100,
                     {"Category": {"projections": [p_col(MON, "activity_year", "Năm")]},
                      "Y": {"projections": [p_meas(MON, "Positive Reviews", "Tích cực"),
                                            p_meas(MON, "Neutral Reviews", "Trung lập"),
                                            p_meas(MON, "Negative Reviews", "Tiêu cực")]}},
                     objs))
    x, y, w, h = inner(Cc)
    q_v = f"{MON}.New Videos"
    objs = axis_objects(show_value_axis=True, categorical=True, cat_font="10D")
    objs.update({"dataPoint": series_colors([(q_v, CORAL)]),
                 "lineStyles": [{"properties": {"strokeWidth": L("3D")}}]})
    vs.append(visual("lineChart", x, y, w, h, 2200,
                     {"Category": {"projections": [p_col(MON, "activity_year", "Năm")]},
                      "Y": {"projections": [p_meas(MON, "New Videos", "Video mới")]}},
                     objs))
    return vs

# ----------------------------------------------------------------------------
# 7. WRITE REPORT
# ----------------------------------------------------------------------------
def write_page(page, bg_name, visuals):
    pdir = os.path.join(PAGES_DIR, page["id"])
    vdir = os.path.join(pdir, "visuals")
    if os.path.exists(vdir):
        shutil.rmtree(vdir)
    os.makedirs(vdir, exist_ok=True)
    page_def = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
        "name": page["id"],
        "displayName": page["name"],
        "displayOption": "FitToPage",
        "height": 1080,
        "width": 1920,
        "objects": {
            "background": [{"properties": {
                "image": {"image": {
                    "name": L(f"'{bg_name}'"),
                    "url": {"expr": {"ResourcePackageItem": {"PackageName": "RegisteredResources",
                                                             "PackageType": 1, "ItemName": bg_name}}},
                    "scaling": L("'Fit'"),
                }},
                "transparency": L("0D"),
            }}],
            "outspace": [{"properties": {"color": C(SLATE_100)}}],
        },
    }
    with open(os.path.join(pdir, "page.json"), "w", encoding="utf-8") as f:
        json.dump(page_def, f, indent=2, ensure_ascii=False)
    for v in visuals:
        d = os.path.join(vdir, v["name"])
        os.makedirs(d)
        with open(os.path.join(d, "visual.json"), "w", encoding="utf-8") as f:
            json.dump(v, f, indent=2, ensure_ascii=False)
    print(f"[page] {page['name']}: {len(visuals)} visuals")


def write_report_json(bg_names):
    path = os.path.join(REPORT, "definition", "report.json")
    with open(path, encoding="utf-8") as f:
        rep = json.load(f)
    base = rep["themeCollection"]["baseTheme"]
    rep["themeCollection"]["customTheme"] = {
        "name": THEME_NAME,
        "reportVersionAtImport": base.get("reportVersionAtImport"),
        "type": "RegisteredResources",
    }
    items = [{"name": THEME_NAME, "path": THEME_NAME, "type": "CustomTheme"}]
    items += [{"name": n, "path": n, "type": "Image"} for n in bg_names.values()]
    pkgs = [p for p in rep.get("resourcePackages", []) if p.get("name") != "RegisteredResources"]
    pkgs.append({"name": "RegisteredResources", "type": "RegisteredResources", "items": items})
    rep["resourcePackages"] = pkgs
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)

    with open(os.path.join(PAGES_DIR, "pages.json"), "w", encoding="utf-8") as f:
        json.dump({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
            "pageOrder": [p["id"] for p in PAGES],
            "activePageName": PAGES[0]["id"],
        }, f, indent=2, ensure_ascii=False)
    for d in os.listdir(PAGES_DIR):
        full = os.path.join(PAGES_DIR, d)
        if os.path.isdir(full) and d not in {p["id"] for p in PAGES}:
            shutil.rmtree(full)
    print("[report] report.json + pages.json updated")


def main():
    bg = render_backgrounds()
    write_theme()
    update_model()
    builders = [page1, page2, page3, page4]
    for page, build in zip(PAGES, builders):
        write_page(page, bg[page["id"]], build(page))
    write_report_json(bg)
    print("DONE")


if __name__ == "__main__":
    main()
