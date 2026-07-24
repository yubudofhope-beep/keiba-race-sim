# -*- coding: utf-8 -*-
"""
generate_race_sim_html.py
================================
predict_sisueos(_v3).py が出力する pred_YYYYMMDD.csv から、レースごとに
「レースシミュレーション」HTML（Plackett-Luce+Gumbelノイズで着順抽選、5着まで表示）
を自動生成する。course_geometry.json のコース固有ジオメトリ（直線長・回り・
高低差・新潟1000mの独立直線コースなど）を反映する。

使い方:
  python generate_race_sim_html.py --pred pred_20260719.csv --outdir race_sim_out
  python generate_race_sim_html.py --pred pred_20260719.csv --race-id 202602011201 --outdir race_sim_out

出力:
  race_sim_out/race_sim_<race_id>.html を1レース1ファイルで生成
  race_sim_out/index.html にその日の全レースへのリンク一覧を生成
"""
import argparse
import json
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
GEOM_PATH = HERE / "course_geometry.json"

# 枠番の色（JRA公認の帽色に準拠した簡易パレット）
FRAME_COLOR = {
    1: ("#ffffff", "#1a2e22"), 2: ("#1a1a1a", "#fff"), 3: ("#e2453f", "#fff"),
    4: ("#3b6ee0", "#fff"), 5: ("#f2b632", "#1a2e22"), 6: ("#2fa64d", "#fff"),
    7: ("#e368a8", "#fff"), 8: ("#f07f2e", "#fff"),
}

TEMPLATE = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>{race_title}｜レースシミュレーション</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body{{margin:0;background:#0f1a13;font-family:"Hiragino Sans","Yu Gothic",sans-serif;display:flex;justify-content:center;padding:24px 10px}}
  .card{{width:100%;max-width:520px;background:rgba(30,50,38,0.94);border-radius:16px;padding:20px;color:#fff}}
  .title{{font-size:19px;font-weight:500;margin-bottom:2px}}
  .sub{{font-size:12px;color:rgba(255,255,255,0.6);margin-bottom:12px}}
  .badge{{background:rgba(20,30,24,0.55);padding:3px 8px;border-radius:4px;margin-bottom:3px;font-size:10px}}
  .pill{{border-radius:2px;padding:0 4px;margin-right:4px;font-weight:500}}
  button{{border:none;border-radius:10px;font-weight:500}}
  #playBtn{{flex:1;height:46px;background:#e9e9e4;color:#1a2e22;font-size:15px}}
  .spdBtn{{width:96px;height:46px;background:rgba(255,255,255,0.14);color:#fff;font-size:15px}}
  .resrow{{display:flex;align-items:center;gap:10px;background:rgba(255,255,255,0.08);border-radius:10px;padding:9px 14px;margin-bottom:6px}}
  .num{{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:500}}
  a.back{{color:#5DCAA5;font-size:12px}}
</style></head>
<body><div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div><div class="title">{race_title}</div><div class="sub">{race_sub}</div></div>
    <a class="back" href="index.html">← 一覧</a>
  </div>
  <div style="position:relative;border-radius:12px;overflow:hidden;background:linear-gradient(180deg,#8fc98a,#6ba869);margin-top:10px">
    <div style="position:absolute;top:8px;right:8px;font-size:10px;z-index:2">
      <div class="badge"><span class="pill" style="background:#fff;color:#1a2e22">M</span>ペース想定</div>
      <div class="badge"><span class="pill" style="background:#5DCAA5;color:#04342C">良</span>馬場 良</div>
    </div>
    <svg id="track" viewBox="0 0 620 300" style="width:100%;display:block">
      <path id="trackOuter" fill="rgba(255,255,255,0.35)"/>
      <path id="trackInner" fill="#7fc27d"/>
      <line id="goalLine" stroke="#e2453f" stroke-width="4"/>
      <text id="goalTag" font-size="10" fill="#8a2620" font-weight="600"></text>
      <text id="progressLabel" x="290" y="150" text-anchor="middle" font-size="17" font-weight="500" fill="#1f3a26"></text>
      <g id="horses"></g>
    </svg>
    <div style="position:absolute;bottom:6px;left:0;right:0;text-align:center;font-size:10px;color:#1f3a26">{course_caption}</div>
  </div>
  <div style="display:flex;gap:8px;margin:14px 0">
    <button id="playBtn">走行中...</button>
    <button class="spdBtn" id="spdBtn">速度 x2</button>
  </div>
  <div style="font-size:11px;color:rgba(255,255,255,0.55);text-align:center;margin-bottom:8px">※着順はwin_calib/top3_calib(較正済み予測確率)を反映したPlackett-Luce抽選（Gumbelノイズ）で試行ごとに決定</div>
  <div id="results"></div>
</div>
<script>
var HORSES = {horses_json};
var GEOM = {geom_json};
(function(){{
  var horses = HORSES;
  var styleBase = {{"逃げ":0.97,"先行":0.80,"好位":0.60,"中団":0.38,"追込":0.15}};
  var styleKick  = {{"逃げ":-0.05,"先行":0.0,"好位":0.06,"中団":0.12,"追込":0.22}};
  var cx=310, cy=150;
  var straightHalf = GEOM.straightHalf, ry = GEOM.ry, thick = 28, rMid = ry+thick/2;
  var mirror = GEOM.turn === "右"; // 右回り=時計回り想定でX反転して描画
  function ovalPath(r){{
    var x1=cx-straightHalf,x2=cx+straightHalf;
    return "M "+x1+" "+(cy-r)+" L "+x2+" "+(cy-r)+" A "+r+" "+r+" 0 0 1 "+x2+" "+(cy+r)+
           " L "+x1+" "+(cy+r)+" A "+r+" "+r+" 0 0 1 "+x1+" "+(cy-r)+" Z";
  }}
  document.getElementById("trackOuter").setAttribute("d", ovalPath(ry+thick));
  document.getElementById("trackInner").setAttribute("d", ovalPath(ry));
  var centerPath = document.createElementNS("http://www.w3.org/2000/svg","path");
  centerPath.setAttribute("d", ovalPath(rMid));
  document.getElementById("horses").appendChild(centerPath);
  centerPath.style.display = "none";
  var len = centerPath.getTotalLength();
  var goalSideSign = mirror ? -1 : 1;
  var goalPt = {{x: cx - straightHalf*0.13*goalSideSign, y: cy + rMid}};
  var bestT=0,bestD=Infinity,samples=400;
  for (var i=0;i<=samples;i++){{
    var t=i/samples*len, p=centerPath.getPointAtLength(t);
    var d=(p.x-goalPt.x)*(p.x-goalPt.x)+(p.y-goalPt.y)*(p.y-goalPt.y);
    if (d<bestD){{bestD=d;bestT=t;}}
  }}
  var goalFrac = bestT/len;
  var goalPtActual = centerPath.getPointAtLength(bestT);
  var tang=centerPath.getPointAtLength(Math.min(len,bestT+1));
  var tangPrev=centerPath.getPointAtLength(Math.max(0,bestT-1));
  var dirx=tang.x-tangPrev.x, diry=tang.y-tangPrev.y, dl=Math.sqrt(dirx*dirx+diry*diry)||1;
  var nx=-diry/dl, ny=dirx/dl;
  document.getElementById("goalLine").setAttribute("x1", goalPtActual.x+nx*16);
  document.getElementById("goalLine").setAttribute("y1", goalPtActual.y+ny*16);
  document.getElementById("goalLine").setAttribute("x2", goalPtActual.x-nx*16);
  document.getElementById("goalLine").setAttribute("y2", goalPtActual.y-ny*16);
  var tag=document.getElementById("goalTag");
  tag.setAttribute("x", goalPtActual.x-14); tag.setAttribute("y", goalPtActual.y+ny*16+14);
  tag.textContent="ゴール";
  var scale = len / GEOM.realOneLap;
  var raceDistSvg = GEOM.distance * scale;
  // ★過去バグ: レース距離が1周(len)より長い場合(例:中京芝2000m対1周1705.9m)、
  //   従来はstartFracとgoalFracの差を"1周未満の弧(%1)"に丸めていたため、
  //   実際は1周以上グルっと回るはずの距離が4角付近の短い弧に圧縮されてしまっていた。
  //   周回数(lapsSpan)を%1で丸めず、実距離ぶんそのまま進める形に修正。
  var lapsSpan = raceDistSvg / len; // 1周に満たない場合もあれば複数周のこともある
  var startFrac = (((goalFrac * len - raceDistSvg) % len) + len) % len / len;
  var g=document.getElementById("horses");
  horses.forEach(function(h,i){{
    var el=document.createElementNS("http://www.w3.org/2000/svg","g");
    el.innerHTML='<circle r="9" fill="'+h.color+'" stroke="rgba(0,0,0,0.15)"></circle><text x="0" y="3.5" text-anchor="middle" font-size="9" font-weight="500" fill="'+h.text_color+'">'+h.num+'</text>';
    g.appendChild(el); h.el=el;
    h.strength = Math.log(Math.max(h.s,0.001)) - Math.log(Math.max(1-h.s,0.001));
  }});
  function drawTrialStrength(h){{ var noise=-Math.log(-Math.log(Math.random())); return h.strength+noise; }}
  var pace="M", paceShift={{S:-0.04,M:0,H:0.04}}, playing=false,t0=null,speedMult=1,raceDur=7000;
  function pathFrac(progress){{ return (startFrac + lapsSpan*progress) % 1; }}
  function place2(progress){{
    var stretch = progress>0.8 ? (progress-0.8)/0.2 : 0;
    var order=[];
    horses.forEach(function(h,i){{
      var bias=1+paceShift[pace];
      var styleOffset = styleBase[h.style] + styleKick[h.style]*Math.max(0,progress-0.55)/0.45;
      var w = Math.max(0,progress-0.3)/0.7;
      var combined = styleOffset*(1-w) + (h._trialNorm!==undefined?h._trialNorm:0.5)*w;
      var pr=Math.max(0,Math.min(1,progress*bias));
      var p=pathFrac(pr);
      var pt=centerPath.getPointAtLength(p*len);
      var pt2=centerPath.getPointAtLength(((p+0.003)%1)*len);
      var nx2=-(pt2.y-pt.y), ny2=(pt2.x-pt.x), nl=Math.sqrt(nx2*nx2+ny2*ny2)||1;
      var lead=combined*10;
      var lx=pt.x+dirx/dl*lead, ly=pt.y+diry/dl*lead;
      var spread = stretch>0 ? (i-3.5)*2.4 : (i-3.5)*1.1;
      h.el.setAttribute("transform","translate("+(lx+nx2/nl*spread)+","+(ly+ny2/nl*spread)+")");
      h._offset=combined; order.push(h);
    }});
    order.sort(function(a,b){{return b._offset-a._offset;}});
    var remain=Math.round((1-progress)*GEOM.distance/10)*10;
    document.getElementById("progressLabel").textContent = progress>0.99?"ゴール":(progress<0.15?"テン争い ":"道中 ")+"残り約"+Math.max(remain,0)+"m";
    return order;
  }}
  function rollTrial(){{
    var vals=horses.map(function(h){{return drawTrialStrength(h);}});
    var min=Math.min.apply(null,vals), max=Math.max.apply(null,vals);
    horses.forEach(function(h,i){{h._trialNorm=(vals[i]-min)/((max-min)||1);}});
  }}
  rollTrial(); place2(0);
  function frame(ts){{
    if(!playing) return; if(!t0) t0=ts;
    var progress=Math.min(1,((ts-t0)*speedMult)/raceDur);
    place2(progress);
    if(progress<1) requestAnimationFrame(frame); else finish();
  }}
  function finish(){{
    playing=false;
    var order=place2(1).slice(0,5);
    var medals=["1着","2着","3着","4着","5着"];
    document.getElementById("results").innerHTML = order.map(function(h,i){{
      return '<div class="resrow"><span style="color:#5DCAA5;font-weight:500;font-size:13px;width:32px">'+medals[i]+'</span>'+
        '<span class="num" style="background:'+h.color+';color:'+h.text_color+'">'+h.num+'</span>'+
        '<span style="font-size:13px;font-weight:500;flex:1">'+h.name+'</span>'+
        '<span style="font-size:11px;color:rgba(255,255,255,0.55)">'+(h.p_win!==undefined?('勝率'+(h.p_win*100).toFixed(0)+'%・'):'')+'複勝率'+(h.p_top3*100).toFixed(0)+'%</span></div>';
    }}).join("");
    document.getElementById("playBtn").textContent="▶ もう一回（別の試行）";
  }}
  document.getElementById("playBtn").addEventListener("click", function(){{
    document.getElementById("results").innerHTML=""; rollTrial();
    playing=true; t0=null; this.textContent="走行中...";
    requestAnimationFrame(frame);
  }});
  document.getElementById("spdBtn").addEventListener("click", function(){{
    speedMult = speedMult===1?2:1; this.textContent = speedMult===1?"速度 x2":"速度 x1";
  }});
  document.getElementById("playBtn").click();
}})();
</script>
</body></html>
"""

STYLES = ["逃げ", "先行", "好位", "中団", "追込"]


def load_geometry():
    return json.loads(GEOM_PATH.read_text(encoding="utf-8"))


def geom_for_race(geom_all, place, surface, distance):
    """course_geometry.jsonの値からSVG描画用パラメータに変換。値が欠けている場合は
    妥当なフォールバック値(全場平均的な数値)を使い、is_fallbackで明示する。"""
    g = geom_all.get(place, {})
    turn = g.get("turn", "右")
    is_turf = (surface == "芝")
    # 直線長: 必ず該当サーフェス(芝/ダート)の値を最優先する。
    # ★過去バグ: 汎用キー"home_stretch_m"を最優先にしていたため、新潟の芝外回り値(659m)を
    #   ダートレースにまで誤流用していた(ダートは実際約350mで別物)。サーフェス別キーを最優先に修正。
    if is_turf:
        keys = ("home_stretch_turf_m", "home_stretch_turf_outer_m", "home_stretch_turf_inner_m",
                "home_stretch_m")
    else:
        keys = ("home_stretch_dirt_m", "home_stretch_m")
    hs = None
    for key in keys:
        if g.get(key):
            hs = g[key]
            break
    if hs is None:
        hs = 300  # フォールバック(全場中央値程度)
    # 1周距離も同様にサーフェス別を優先(ダートレースに芝の1周距離を使わない)
    if is_turf:
        one_lap = (g.get("one_lap_turf_m") or g.get("one_lap_turf_outer_m") or
                   g.get("one_lap_turf_inner_m") or g.get("one_lap_dirt_m") or 1900)
    else:
        one_lap = (g.get("one_lap_dirt_m") or g.get("one_lap_turf_m") or
                   g.get("one_lap_turf_outer_m") or g.get("one_lap_turf_inner_m") or 1900)
    straight_half = min(225, max(90, hs * 0.55))  # SVG座標系(614幅)にスケール
    ry = max(38, 70 - straight_half * 0.05)
    is_straight_course = (place == "新潟" and surface == "芝" and int(distance) == 1000)
    return {
        "straightHalf": straight_half,
        "ry": ry,
        "realOneLap": one_lap,
        "distance": int(distance),
        "turn": turn,
        "is_straight_course": is_straight_course,
    }


def build_horses(race_df, public: bool):
    """public=True の場合、勝率(win_calib等)は一切horses配列に含めない。
    抽選駆動用のstrengthも複勝率(top3_calib)から作るので、公開HTMLのソースを
    見ても勝率の数値そのものが存在しない（難読化ではなく非搭載による対策）。
    public=False(自分用)は従来通りwin_calibを含めて厳密なPL抽選ができるようにする。"""
    race_df = race_df.copy()
    win_col = "win_calib" if "win_calib" in race_df.columns else (
        "score_win" if "score_win" in race_df.columns else "win_softmax")
    top3_col = "top3_calib" if "top3_calib" in race_df.columns else (
        "score_top3" if "score_top3" in race_df.columns else "top3_pl")
    total_win = race_df[win_col].sum() or 1.0
    total_top3 = race_df[top3_col].sum() or 1.0
    horses = []
    for i, (_, row) in enumerate(race_df.sort_values("horse_number").iterrows()):
        frame = int(row["frame_number"]) if "frame_number" in row and pd.notna(row["frame_number"]) else (
            (int(row["horse_number"]) - 1) % 8 + 1)
        color, text_color = FRAME_COLOR.get(frame, ("#888", "#fff"))
        p_top3 = float(row[top3_col]) if pd.notna(row[top3_col]) else 0.3
        h = {
            "num": int(row["horse_number"]),
            "name": str(row["horse_name"]),
            "color": color,
            "text_color": text_color,
            "style": STYLES[i % len(STYLES)],  # 実データに脚質列がないため見た目の味付け用に割当(結果には影響小)
            "p_top3": p_top3,
        }
        if public:
            # 公開版: 抽選の強さも複勝率ベースで代用。win_calibの数値は生成物に一切含めない。
            h["s"] = p_top3 / total_top3 if total_top3 else 0.05
        else:
            # 自分用: 本来のwin_calibで厳密にPL抽選
            h["s"] = float(row[win_col]) / total_win if total_win else 0.05
            h["p_win"] = float(row[win_col])  # 自分用のみ勝率も保持(参考表示・分析用)
        horses.append(h)
    return horses


def safe_filename(s):
    return re.sub(r"[^0-9A-Za-z_\-]", "_", str(s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True, help="predict_sisueosの出力CSV(pred_YYYYMMDD.csv)")
    ap.add_argument("--outdir", default="race_sim_out")
    ap.add_argument("--race-id", default=None, help="このrace_idのみ生成(省略時は全レース)")
    ap.add_argument("--public", action="store_true",
                    help="公開用モード。win_calib(勝率)を生成物に一切含めず、抽選もtop3_calib(複勝率)ベースで行う。"
                         "指定しない場合は自分用(勝率入り)として生成される。")
    args = ap.parse_args()

    df = pd.read_csv(args.pred, encoding="utf-8-sig")
    geom_all = load_geometry()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if args.race_id:
        df = df[df["race_id"].astype(str) == str(args.race_id)]

    index_rows = []
    for race_id, race_df in df.groupby("race_id"):
        row0 = race_df.iloc[0]
        place, distance, surface = row0["place"], row0["distance"], row0["surface"]
        race_name = row0.get("race_name", "")
        date = row0.get("date", "")
        geom = geom_for_race(geom_all, place, surface, distance)
        horses = build_horses(race_df, public=args.public)
        title = f"{place}{surface}{int(distance)}m {race_name}"
        sub = f"{date}｜{place}｜{surface}{int(distance)}m｜{geom['turn']}回り"
        if geom["is_straight_course"]:
            sub += "（※新潟1000m 直線専用コース。オーバル図とは別トラックのため簡易表示）"
        caption = f"{place} {surface}{int(distance)}m（{geom['turn']}回り）"
        html = TEMPLATE.format(
            race_title=title, race_sub=sub, course_caption=caption,
            horses_json=json.dumps(horses, ensure_ascii=False),
            geom_json=json.dumps(geom, ensure_ascii=False),
        )
        fname = f"race_sim_{safe_filename(race_id)}.html"
        (outdir / fname).write_text(html, encoding="utf-8")
        index_rows.append((race_id, place, surface, distance, race_name, fname))
        print(f"[OK] {race_id} {place} {race_name} -> {fname}")

    # 日付は基本1CSV=1日想定。複数日混在時は最大の日付をこの生成回のラベルにする。
    dates_seen = sorted({str(r) for r in df["date"].dropna().unique()}) if "date" in df.columns else []
    run_date = dates_seen[-1] if dates_seen else "unknown"

    build_day_and_archive(index_rows, outdir, run_date)
    print(f"[OK] {run_date}分のページ + アーカイブ一覧を生成（{len(index_rows)}レース）")


NAV_CSS = """
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body { margin:0; font-family:"Hiragino Sans","Yu Gothic",sans-serif; background:#0b1210; color:#fff;
         -webkit-font-smoothing:antialiased; }
  .nav { display:flex; align-items:center; justify-content:space-between; padding:14px 24px;
         background:rgba(15,26,19,0.9); backdrop-filter:blur(6px); border-bottom:1px solid rgba(255,255,255,0.08);
         position:sticky; top:0; z-index:10; }
  .nav .brand { font-size:18px; font-weight:700; letter-spacing:0.02em; }
  .nav .brand span { color:#5DCAA5; }
  .nav-right { display:flex; align-items:center; gap:16px; }
  .nav a.arclink { color:rgba(255,255,255,0.6); font-size:12px; text-decoration:none; }
  .nav a.arclink:hover { color:#5DCAA5; }
  .hero { padding:44px 24px 28px; background:radial-gradient(ellipse at top left,#16281f,#0b1210 70%); }
  .hero .eyebrow { display:inline-block; font-size:11px; font-weight:700; letter-spacing:0.08em;
                   color:#5DCAA5; background:rgba(93,202,165,0.12); border:1px solid rgba(93,202,165,0.3);
                   padding:3px 10px; border-radius:20px; margin-bottom:12px; }
  .hero h1 { margin:0 0 10px; font-size:28px; letter-spacing:0.01em; }
  .hero p { margin:0; color:rgba(255,255,255,0.65); font-size:14px; line-height:1.8; max-width:640px; }
  .about { padding:4px 24px 8px; }
  .about-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; max-width:820px; }
  .about-item { background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.07);
                border-radius:12px; padding:14px 16px; }
  .about-item .k { font-size:11px; color:rgba(255,255,255,0.45); margin-bottom:4px; }
  .about-item .v { font-size:14px; font-weight:600; color:#5DCAA5; }
  .content { padding:20px 24px 12px; }
  .venue-block { margin-top:28px; }
  .venue-title { font-size:16px; font-weight:700; color:#5DCAA5; margin-bottom:10px;
                 display:flex; align-items:center; gap:8px; padding-bottom:6px;
                 border-bottom:1px solid rgba(93,202,165,0.15); }
  .venue-count { font-size:11px; font-weight:400; color:rgba(255,255,255,0.45); }
  .card-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:10px; }
  .card { display:flex; gap:10px; align-items:center; background:rgba(255,255,255,0.05);
          border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:12px 14px;
          text-decoration:none; color:#fff; transition:all 0.15s; }
  .card:hover { background:rgba(93,202,165,0.12); border-color:rgba(93,202,165,0.4); transform:translateY(-1px); }
  .card-rno { font-size:13px; font-weight:700; color:#5DCAA5; width:34px; flex-shrink:0; }
  .card-name { font-size:13px; font-weight:500; }
  .card-meta { font-size:11px; color:rgba(255,255,255,0.5); margin-top:2px; }
  .datelink { display:block; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.08);
              border-radius:10px; padding:14px 16px; margin-bottom:10px; text-decoration:none; color:#fff;
              transition:all 0.15s; }
  .datelink:hover { background:rgba(93,202,165,0.12); border-color:rgba(93,202,165,0.4); transform:translateY(-1px); }
  footer.disclaimer { margin-top:32px; padding:22px 24px 28px; border-top:1px solid rgba(255,255,255,0.08);
                      color:rgba(255,255,255,0.45); font-size:11.5px; line-height:1.9; }
  footer.disclaimer strong { color:rgba(255,255,255,0.65); }
"""

DISCLAIMER_HTML = """
  <footer class="disclaimer">
    <strong>ご利用にあたって</strong><br>
    本サイトは機械学習モデルによる予想の参考情報を掲載しています。着順シミュレーションは予測モデルの複勝率をもとにした確率的な演出であり、実際のレース結果や的中を保証するものではありません。馬券の購入は必ずご自身の判断・責任で行ってください。20歳未満の方の馬券購入は法律で禁止されています。
  </footer>"""


def _format_date_label(d: str) -> str:
    try:
        y, m, dd = d.split("-")
        return f"{y}年{int(m)}月{int(dd)}日"
    except Exception:
        return d


def _day_content_html(index_rows, run_date, archive_link_html):
    by_place = {}
    for race_id, place, surface, distance, race_name, fname in index_rows:
        by_place.setdefault(place, []).append((race_id, surface, distance, race_name, fname))

    sections = []
    for place, races in by_place.items():
        cards = []
        for race_id, surface, distance, race_name, fname in races:
            rno = str(race_id)[-2:]
            cards.append(f"""
        <a class="card" href="{fname}">
          <div class="card-rno">{int(rno)}R</div>
          <div class="card-body">
            <div class="card-name">{race_name}</div>
            <div class="card-meta">{surface}{int(distance)}m</div>
          </div>
        </a>""")
        sections.append(f"""
      <div class="venue-block">
        <div class="venue-title">{place}<span class="venue-count">{len(races)}レース</span></div>
        <div class="card-grid">{''.join(cards)}</div>
      </div>""")

    n_venues = len(by_place)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>競馬AI レースシミュレーション（{_format_date_label(run_date)}）</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{NAV_CSS}</style></head>
<body>
  <div class="nav">
    <div class="brand">競馬AI<span>レースシム</span></div>
    <div class="nav-right">
      <a class="arclink" href="archive/index.html">過去の予想を見る</a>
      <span style="font-size:12px;color:rgba(255,255,255,0.5)">{len(index_rows)}レース掲載</span>
    </div>
  </div>
  <div class="hero">
    <span class="eyebrow">AI RACE SIMULATION</span>
    <h1>レースシミュレーション（{_format_date_label(run_date)}）</h1>
    <p>予測モデルが算出した複勝率をもとに、各馬の展開とゴールまでのシミュレーションを再現しています。実際の周回コース(直線距離・回り・高低差)をJRA全10場ぶん再現し、コースの特徴も反映しています。開催場ごとにレースを一覧表示しているので、気になるレースをタップして再生してみてください。{archive_link_html}</p>
  </div>
  <div class="about">
    <div class="about-grid">
      <div class="about-item"><div class="k">開催場数</div><div class="v">{n_venues}場</div></div>
      <div class="about-item"><div class="k">掲載レース数</div><div class="v">{len(index_rows)}レース</div></div>
      <div class="about-item"><div class="k">着順の決め方</div><div class="v">複勝率ベース抽選</div></div>
      <div class="about-item"><div class="k">対象</div><div class="v">中央競馬 全場</div></div>
    </div>
  </div>
  <div class="content">{''.join(sections)}</div>
  {DISCLAIMER_HTML}
</body></html>"""


def build_day_and_archive(index_rows, outdir, run_date):
    """当日分は docs/index.html（トップ）に反映しつつ、
    docs/archive/<date>.html にも同じ内容を保存して過去分を消さずに残す。
    docs/archive/index.html は archive/ 内の日付ファイルを走査して一覧化する。"""
    archive_dir = outdir / "archive"
    archive_dir.mkdir(exist_ok=True)

    day_html = _day_content_html(index_rows, run_date, "")
    (outdir / "index.html").write_text(day_html, encoding="utf-8")
    (archive_dir / f"{run_date}.html").write_text(
        _day_content_html(index_rows, run_date, "（このページはアーカイブです）"), encoding="utf-8"
    )

    # archive内の日付ファイルを走査してアーカイブ一覧を再構築（race_sim_*.htmlは対象外）
    date_files = sorted(
        (p.stem for p in archive_dir.glob("*.html") if p.stem != "index"),
        reverse=True,
    )
    links = "\n".join(
        f'<a class="datelink" href="{d}.html">{_format_date_label(d)}</a>' for d in date_files
    )
    archive_index = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>競馬AI レースシミュレーション（過去分アーカイブ）</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{NAV_CSS}</style></head>
<body>
  <div class="nav">
    <div class="brand">競馬AI<span>レースシム</span></div>
    <div class="nav-right"><a class="arclink" href="../index.html">最新に戻る</a></div>
  </div>
  <div class="hero">
    <span class="eyebrow">ARCHIVE</span>
    <h1>過去の予想アーカイブ</h1>
    <p>日付ごとのレースシミュレーション一覧です。見たい日付を選んでください（全{len(date_files)}日分）。</p>
  </div>
  <div class="content">{links}</div>
  {DISCLAIMER_HTML}
</body></html>"""
    (archive_dir / "index.html").write_text(archive_index, encoding="utf-8")


if __name__ == "__main__":
    main()
