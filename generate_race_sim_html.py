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
import sqlite3
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
GEOM_PATH = HERE / "course_geometry.json"

GA_SNIPPET = """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-3D31T25KK1"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-3D31T25KK1');
</script>
"""

# 枠番の色（JRA公認の帽色に準拠した簡易パレット）
FRAME_COLOR = {
    1: ("#ffffff", "#1a2e22"), 2: ("#1a1a1a", "#fff"), 3: ("#e2453f", "#fff"),
    4: ("#3b6ee0", "#fff"), 5: ("#f2b632", "#1a2e22"), 6: ("#2fa64d", "#fff"),
    7: ("#e368a8", "#fff"), 8: ("#f07f2e", "#fff"),
}

TEMPLATE = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
""" + GA_SNIPPET.replace("{", "{{").replace("}", "}}") + r"""<title>{race_title}｜レースシミュレーション</title>
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
    <a class="back" href="index.html?date={run_date}">← 一覧</a>
  </div>
  <div style="display:flex;gap:6px;margin-top:10px">
    <button id="btn2d" style="flex:1;height:28px;background:rgba(255,255,255,0.22);color:#fff;font-size:11px;border-radius:8px">2Dコース</button>
    <button id="btn3d" style="flex:1;height:28px;background:rgba(255,255,255,0.14);color:#fff;font-size:11px;border-radius:8px">3Dコース(β)</button>
  </div>
  <div id="viewSvg" style="position:relative;border-radius:12px;overflow:hidden;background:linear-gradient(180deg,#8fc98a,#6ba869);margin-top:8px">
    <div style="position:absolute;top:8px;right:8px;font-size:10px;z-index:2">
      <div class="badge"><span class="pill" style="background:#fff;color:#1a2e22">M</span>ペース想定</div>
      <div class="badge"><span class="pill" style="background:#5DCAA5;color:#04342C">良</span>馬場 良</div>
    </div>
    <svg id="track" viewBox="0 0 820 300" style="width:100%;display:block">
      <path id="trackOuter" fill="rgba(255,255,255,0.35)"/>
      <path id="trackInner" fill="#7fc27d"/>
      <line id="goalLine" stroke="#e2453f" stroke-width="4"/>
      <text id="goalTag" font-size="10" fill="#8a2620" font-weight="600"></text>
      <text id="progressLabel" x="410" y="150" text-anchor="middle" font-size="17" font-weight="500" fill="#1f3a26"></text>
      <g id="horses"></g>
    </svg>
    <div style="position:absolute;bottom:6px;left:0;right:0;text-align:center;font-size:10px;color:#1f3a26">{course_caption}</div>
  </div>
  <div id="viewThree" style="display:none;position:relative;border-radius:12px;overflow:hidden;background:linear-gradient(180deg,#233b28,#16241a);margin-top:8px">
    <canvas id="three3d" style="width:100%;height:300px;display:block"></canvas>
    <div style="position:absolute;top:8px;right:8px;background:rgba(233,240,228,0.88);border-radius:12px;padding:8px 14px;text-align:right;min-width:104px">
      <div><span id="dist3d" style="font-size:26px;font-weight:700;color:#1c2b34;line-height:1">--</span><span style="font-size:12px;color:#1c2b34">m</span></div>
      <div id="sect3d" style="display:inline-block;margin-top:4px;background:#3b7fe0;color:#fff;font-size:12px;font-weight:600;padding:2px 12px;border-radius:20px">発走前</div>
      <div id="grade3d" style="margin-top:4px;font-size:11px;font-weight:600;color:#2f6ea8">&nbsp;</div>
    </div>
    <div id="elev3d" style="position:absolute;top:8px;left:8px;background:rgba(233,240,228,0.88);color:#1c2b34;font-size:11px;font-weight:600;padding:4px 10px;border-radius:10px"></div>
    <div id="startOverlay3d" style="position:absolute;left:0;right:0;bottom:22px;text-align:center">
      <div style="display:inline-block;background:rgba(233,240,228,0.94);border-radius:14px;padding:10px 16px">
        <div style="font-size:11px;color:#1c2b34;margin-bottom:6px">ペース想定</div>
        <div id="paceBtns" style="display:flex;gap:6px;justify-content:center;margin-bottom:9px">
          <button class="paceBtn" data-p="S" style="width:44px;height:30px;font-size:13px;border-radius:8px;background:#fff;color:#1c2b34">S</button>
          <button class="paceBtn" data-p="M" style="width:44px;height:30px;font-size:13px;border-radius:8px;background:#3b7fe0;color:#fff">M</button>
          <button class="paceBtn" data-p="H" style="width:44px;height:30px;font-size:13px;border-radius:8px;background:#fff;color:#1c2b34">H</button>
        </div>
        <button id="startRaceBtn" style="width:150px;height:34px;font-size:13px;border-radius:9px;background:#1c2b34;color:#fff">▶ レース開始</button>
      </div>
    </div>
    <div style="position:absolute;bottom:6px;left:0;right:0;text-align:center;font-size:10px;color:rgba(255,255,255,0.6)">ドラッグで視点回転・ホイールでズーム／高低差はJRA公表値・起伏は誇張表示、勾配%は目安</div>
  </div>
  <div style="display:flex;gap:8px;margin:14px 0">
    <button id="playBtn">走行中...</button>
    <button class="spdBtn" id="spdBtn">速度 x2</button>
  </div>
  <div style="font-size:11px;color:rgba(255,255,255,0.55);text-align:center;margin-bottom:8px">※着順はwin_calib/top3_calib(較正済み予測確率)を反映したPlackett-Luce抽選（Gumbelノイズ）で試行ごとに決定</div>
  <div id="results"></div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
var HORSES = {horses_json};
var GEOM = {geom_json};
(function(){{
  var horses = HORSES;
  // ★脚質は h.pos(DBのrun_style_avg: 0=前で運ぶ / 1=後ろから)の連続値で扱う。
  //   以前は馬番順に逃げ→先行→…と機械的に割り当てた見た目だけの値だった。
  function baseOf(h){{ return 0.97 - 0.82*h.pos; }}   // 道中の前後位置
  function kickOf(h){{ return -0.05 + 0.27*h.pos; }}  // 終いの伸び(後ろの馬ほど末脚)
  // 道中の横位置(+1=最内ラチ沿い / -1=最外)。前で運ぶ馬はロスを避けて内、
  // 差し・追込は前が壁にならないよう外めを回る。
  function laneOf(h){{ return 0.78 - 1.20*h.pos; }}
  var cx=410, cy=150;   // viewBox 820x300 の中心
  // ★コース幅(thick)。馬マーカーの直径に対しコース幅が十分広くないと
  //   馬群が横に広がれず常に団子に見える。実写に近い比率(マーカー径 ≒ コース幅の1割)
  //   になるよう thick=110 / SCALE3D=0.06 / マーカー径0.7 で釣り合わせている。
  var straightHalf = GEOM.straightHalf, ry = GEOM.ry, thick = 110, rMid = ry+thick/2;
  var mirror = GEOM.turn === "右"; // 右回り=時計回り想定でX反転して描画
  // ★新潟芝1000mは日本唯一の直線専用コース。以前はフラグだけ持たせて
  //   注記を出すのみで、描画は他場と同じ楕円のままだった(コーナーが存在しないのに
  //   1〜2角/向正面が表示される)。直線コースは往復しない一本道として描く。
  var isStraight = !!GEOM.is_straight_course;
  function ovalPath(r){{
    var x1=cx-straightHalf,x2=cx+straightHalf;
    if (isStraight){{
      // 上下に細長い長方形(=直線コース)。往路のみで周回しない。
      return "M "+x1+" "+(cy-r)+" L "+x2+" "+(cy-r)+" L "+x2+" "+(cy+r)+
             " L "+x1+" "+(cy+r)+" Z";
    }}
    return "M "+x1+" "+(cy-r)+" L "+x2+" "+(cy-r)+" A "+r+" "+r+" 0 0 1 "+x2+" "+(cy+r)+
           " L "+x1+" "+(cy+r)+" A "+r+" "+r+" 0 0 1 "+x1+" "+(cy-r)+" Z";
  }}
  document.getElementById("trackOuter").setAttribute("d", ovalPath(ry+thick));
  document.getElementById("trackInner").setAttribute("d", ovalPath(ry));
  var centerPath = document.createElementNS("http://www.w3.org/2000/svg","path");
  // 直線コースは周回しない一本道。走行線も閉じた楕円ではなく左→右の直線にする。
  centerPath.setAttribute("d", isStraight
    ? ("M "+(cx-straightHalf)+" "+cy+" L "+(cx+straightHalf)+" "+cy)
    : ovalPath(rMid));
  document.getElementById("horses").appendChild(centerPath);
  centerPath.style.display = "none";
  var len = centerPath.getTotalLength();
  var goalSideSign = mirror ? -1 : 1;
  var goalPt = isStraight
    ? {{x: cx+straightHalf, y: cy}}
    : {{x: cx - straightHalf*0.13*goalSideSign, y: cy + rMid}};
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
  if (isStraight){{
    // 直線コースは一本道の端から端でちょうどレース距離。周回や巻き戻しはしない。
    lapsSpan = 1; startFrac = 0;
  }}
  var g=document.getElementById("horses");
  horses.forEach(function(h,i){{
    var el=document.createElementNS("http://www.w3.org/2000/svg","g");
    el.innerHTML='<circle r="9" fill="'+h.color+'" stroke="rgba(0,0,0,0.15)"></circle><text x="0" y="3.5" text-anchor="middle" font-size="9" font-weight="500" fill="'+h.text_color+'">'+h.num+'</text>';
    g.appendChild(el); h.el=el;
    h.strength = Math.log(Math.max(h.s,0.001)) - Math.log(Math.max(1-h.s,0.001));
  }});
  var mode = "2d", SCALE3D = 0.06;
  var scene3D, camera3D, renderer3D, gate3D;
  var gatePhase = false;
  var camYaw = 0, camPitchOff = 0, camDist = 9, camHeight = 4.2;
  var lastProgress = 0;
  // ---- 高低差(コースの起伏) ----
  // GEOM.elevM は course_geometry.json 由来の実測高低差(m)。
  // 位置ごとの詳細な標高プロファイルは公表値が無いため、JRA各場に共通する形
  //   「向正面〜3角付近が最高点 / ゴール手前に最低点があり最後は上り」
  // を基準にした近似モデルで補間する(=勾配%は目安値)。
  // 実寸だと最大でも3.5m程度で3Dではほぼ見えないため、表示上はELEV_EXAG倍に誇張する。
  var ELEV_EXAG = 12;
  var worldPerM = SCALE3D * (len / GEOM.realOneLap);
  var elevAmpWorld = (GEOM.elevM || 0) * worldPerM * ELEV_EXAG;
  // t = ゴールまでの残り(1周に対する割合)。JRA各場に共通する断面:
  //   ゴール前の短い区間に坂が集中 → 最低点 → 向正面〜3角が最高点 → 4角にかけて下る
  // ゴール前の坂を1周全体に均すと勾配が実測より大幅に小さくなるため、
  // 坂の区間長(ELEV_CLIMB_M)を区切って集中させている。
  var ELEV_CLIMB_M = 110;                       // ゴール前の坂の長さ(m)
  var ELEV_FIN_RATIO = 0.55;                    // 高低差のうちゴール前の坂が占める割合
  function elevNormAtFrac(pf){{
    // 直線コースは周回しないので、残り割合は素直に 1-pf(巻き戻しなし)
    var t = isStraight ? Math.max(0, Math.min(1, 1 - pf))
                       : (((goalFrac - pf) % 1) + 1) % 1;
    var tc = Math.min(0.3, ELEV_CLIMB_M / GEOM.realOneLap);
    var hFin = ELEV_FIN_RATIO;
    if (t <= tc){{
      // ゴール前の坂(ゴールに向かって上る)
      return hFin * (0.5 + 0.5*Math.cos(Math.PI * (t/tc)));
    }}
    if (t <= 0.55){{
      // 最低点 → 最高点(向正面〜3角)
      return 0.5 - 0.5*Math.cos(Math.PI * (t - tc) / (0.55 - tc));
    }}
    // 最高点 → 4角を下ってゴール前の坂の入口へ
    var w = (t - 0.55) / (1 - 0.55);
    return 1 - (1 - hFin) * (0.5 - 0.5*Math.cos(Math.PI * w));
  }}
  function elevAtFrac(pf){{ return elevNormAtFrac(pf) * elevAmpWorld; }}
  // 現在地の勾配(%)。実距離ベースなので誇張は外して計算する。
  function gradePctAtProgress(pr){{
    var pf = pathFrac(Math.max(0, Math.min(1, pr)));
    var dPf = 20 / GEOM.realOneLap;     // 20m先
    var e1 = elevNormAtFrac(pf) * (GEOM.elevM || 0);
    var e2 = elevNormAtFrac(pf + dPf) * (GEOM.elevM || 0);
    return (e2 - e1) / 20 * 100;
  }}
  function makeSurfaceTexture(base, variance, stripes){{
    var c=document.createElement("canvas"); c.width=128; c.height=128;
    var ctx=c.getContext("2d");
    var br=parseInt(base.slice(1,3),16), bg=parseInt(base.slice(3,5),16), bb=parseInt(base.slice(5,7),16);
    ctx.fillStyle=base; ctx.fillRect(0,0,128,128);
    for (var i=0;i<700;i++){{
      var x=Math.random()*128, y=Math.random()*128, v=(Math.random()-0.5)*variance;
      var r=Math.max(0,Math.min(255,br+v)), g=Math.max(0,Math.min(255,bg+v)), b=Math.max(0,Math.min(255,bb+v));
      ctx.fillStyle="rgba("+r+","+g+","+b+",0.55)";
      ctx.beginPath(); ctx.arc(x,y,Math.random()*2.2+0.4,0,Math.PI*2); ctx.fill();
    }}
    if (stripes){{
      for (var s=0;s<128;s+=16){{
        ctx.fillStyle = (s/16)%2===0 ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.05)";
        ctx.fillRect(0,s,128,8);
      }}
    }}
    var tex=new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    return tex;
  }}
  function makeHorseTexture(h){{
    var c=document.createElement("canvas"); c.width=64; c.height=64;
    var ctx=c.getContext("2d");
    ctx.beginPath(); ctx.arc(32,32,26,0,Math.PI*2);
    ctx.fillStyle=h.color; ctx.fill();
    ctx.lineWidth=5; ctx.strokeStyle="rgba(255,255,255,0.95)"; ctx.stroke();
    ctx.fillStyle=h.text_color; ctx.font="bold 28px sans-serif";
    ctx.textAlign="center"; ctx.textBaseline="middle";
    ctx.fillText(String(h.num),32,34);
    return new THREE.CanvasTexture(c);
  }}
  function buildTrackMesh3D(){{
    var outerEl=document.getElementById("trackOuter"), innerEl=document.getElementById("trackInner");
    var outerLen=outerEl.getTotalLength(), innerLen=innerEl.getTotalLength();
    var segs=110, positions=[], uvs=[], indices=[];
    for (var i=0;i<=segs;i++){{
      var f=i/segs;
      var po=outerEl.getPointAtLength(f*outerLen);
      var pi=innerEl.getPointAtLength(f*innerLen);
      var ey=elevAtFrac(f);
      positions.push((po.x-cx)*SCALE3D,ey,(po.y-cy)*SCALE3D);
      positions.push((pi.x-cx)*SCALE3D,ey,(pi.y-cy)*SCALE3D);
      uvs.push(f*14,1, f*14,0);
    }}
    for (var i=0;i<segs;i++){{
      var a=i*2,b=i*2+1,c=i*2+2,d=i*2+3;
      indices.push(a,b,c, b,d,c);
    }}
    var geo=new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(positions,3));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute(uvs,2));
    geo.setIndex(indices);
    geo.computeVertexNormals();
    var isTurf = GEOM.surface !== "ダート";
    var tex = isTurf ? makeSurfaceTexture("#5fa14f", 30, true) : makeSurfaceTexture("#8a5a3a", 26, false);
    tex.repeat.set(1,1);
    var mat=new THREE.MeshStandardMaterial({{map:tex, side:THREE.DoubleSide, roughness:0.95}});
    return new THREE.Mesh(geo, mat);
  }}
  function buildRail3D(pathEl, y){{
    var grp=new THREE.Group();
    var totalLen=pathEl.getTotalLength(), segs=150, pts=[];
    for (var i=0;i<=segs;i++){{
      var f=i/segs;
      var p=pathEl.getPointAtLength(f*totalLen);
      pts.push(new THREE.Vector3((p.x-cx)*SCALE3D, y+elevAtFrac(f), (p.y-cy)*SCALE3D));
    }}
    var railMat=new THREE.LineBasicMaterial({{color:0xf4f4ee}});
    [0, -0.16].forEach(function(dy){{
      var pts2=pts.map(function(v){{ return new THREE.Vector3(v.x, v.y+dy, v.z); }});
      grp.add(new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts2), railMat));
    }});
    var postGeo=new THREE.CylinderGeometry(0.035,0.035,y+0.1,5);
    var postMat=new THREE.MeshStandardMaterial({{color:0xe8e8e0, roughness:0.8}});
    for (var i=0;i<segs;i+=5){{
      var post=new THREE.Mesh(postGeo, postMat);
      post.position.set(pts[i].x, (y+0.1)/2, pts[i].z);
      post.castShadow=true;
      grp.add(post);
    }}
    return grp;
  }}
  // 走路上の点を等間隔にサンプルし、任意座標→最寄り地点の標高を引けるようにする
  var elevSamples = (function(){{
    var arr=[], N=240;
    for (var i=0;i<N;i++){{
      var f=i/N, p=centerPath.getPointAtLength(f*len);
      arr.push({{x:(p.x-cx)*SCALE3D, z:(p.y-cy)*SCALE3D, e:elevAtFrac(f)}});
    }}
    return arr;
  }})();
  function terrainElevAt(x, z){{
    var best=null, bestD=Infinity;
    for (var i=0;i<elevSamples.length;i++){{
      var s=elevSamples[i], dx=x-s.x, dz=z-s.z, d=dx*dx+dz*dz;
      if (d<bestD){{ bestD=d; best=s; }}
    }}
    // 走路から離れるほど起伏をなだらかに戻す
    var dist=Math.sqrt(bestD);
    var fall=Math.max(0, 1 - Math.max(0, dist-4)/26);
    return best.e * fall;
  }}
  function buildTree3D(x, z, tall){{
    var grp=new THREE.Group();
    var trunkMat=new THREE.MeshStandardMaterial({{color:0xa8794f, roughness:1}});
    var trunk=new THREE.Mesh(new THREE.CylinderGeometry(0.09,0.12,0.7,5), trunkMat);
    trunk.position.y=0.35; trunk.castShadow=true; grp.add(trunk);
    var leafCol = new THREE.Color().setHSL(0.27, 0.42, 0.42+Math.random()*0.16);
    var leafMat = new THREE.MeshStandardMaterial({{color:leafCol, roughness:1, flatShading:true}});
    var leaf;
    if (tall){{
      leaf=new THREE.Mesh(new THREE.SphereGeometry(0.42,7,7), leafMat);
      leaf.scale.set(0.62,1.9,0.62); leaf.position.y=1.45;
    }} else {{
      leaf=new THREE.Mesh(new THREE.DodecahedronGeometry(0.62,0), leafMat);
      leaf.position.y=1.15;
    }}
    leaf.castShadow=true; grp.add(leaf);
    grp.position.set(x, terrainElevAt(x,z), z);
    var s=0.8+Math.random()*0.7; grp.scale.set(s,s,s);
    return grp;
  }}
  // ★コース(トラック)はカプセル形状: 中心線分(±straightHalf, 0)からの距離が
  //   ry〜ry+thick の範囲が走路。以前は外周パスを60点サンプルして距離判定していたため
  //   サンプル間の隙間や内馬場に木が生えてしまっていた。数式で厳密に判定する。
  function distToSpine3D(x,z){{
    var shW = straightHalf*SCALE3D;
    var dx = Math.abs(x) - shW;
    if (dx < 0) dx = 0;                 // 直線部の真横なら垂直距離のみ
    return Math.sqrt(dx*dx + z*z);
  }}
  function scatterTrees3D(){{
    var grp=new THREE.Group();
    var outerR = (ry+thick)*SCALE3D;
    var minR = outerR + 1.6;            // 走路の外側にマージンを取る
    var maxR = outerR + 17;
    var placed=0, tries=0;
    while (placed<52 && tries<2500){{
      tries++;
      var x=(Math.random()-0.5)*2*(straightHalf*SCALE3D+maxR);
      var z=(Math.random()-0.5)*2*maxR;
      var d=distToSpine3D(x,z);
      if (d < minR || d > maxR) continue;   // 走路上・内馬場・遠すぎる場所には置かない
      grp.add(buildTree3D(x,z, Math.random()<0.35));
      placed++;
    }}
    return grp;
  }}
  function makeMeshPanelTexture(){{
    // 発走ゲートの網目(前扉)用テクスチャ。線以外は透過。
    var c=document.createElement("canvas"); c.width=64; c.height=64;
    var ctx=c.getContext("2d");
    ctx.clearRect(0,0,64,64);
    ctx.strokeStyle="rgba(225,225,215,0.95)"; ctx.lineWidth=3;
    for (var i=0;i<=64;i+=10){{
      ctx.beginPath(); ctx.moveTo(i,0); ctx.lineTo(i,64); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0,i); ctx.lineTo(64,i); ctx.stroke();
    }}
    var t=new THREE.CanvasTexture(c);
    t.wrapS=t.wrapT=THREE.RepeatWrapping;
    return t;
  }}
  function makeNumberPlateTexture(h){{
    // 各馬房の上に付く枠番号プレート
    var c=document.createElement("canvas"); c.width=64; c.height=64;
    var ctx=c.getContext("2d");
    ctx.fillStyle=h.color; ctx.fillRect(0,0,64,64);
    ctx.strokeStyle="rgba(0,0,0,0.25)"; ctx.lineWidth=3; ctx.strokeRect(1.5,1.5,61,61);
    ctx.fillStyle=h.text_color; ctx.font="bold 42px sans-serif";
    ctx.textAlign="center"; ctx.textBaseline="middle";
    ctx.fillText(String(h.num),32,35);
    return new THREE.CanvasTexture(c);
  }}
  function buildGoal3D(){{
    // ゴール線・ゴール板。3D側にゴールの目印が無かったため追加。
    var grp=new THREE.Group();
    var gx=(goalPtActual.x-cx)*SCALE3D, gz=(goalPtActual.y-cy)*SCALE3D;
    var tX=dirx/dl, tZ=diry/dl;                 // 進行方向(world)
    var wTrack=thick*SCALE3D;
    var inner=new THREE.Group();
    // 走路を横断する白いゴール線
    var line=new THREE.Mesh(
      new THREE.PlaneGeometry(wTrack, 0.28),
      new THREE.MeshBasicMaterial({{color:0xffffff, transparent:true, opacity:0.95}}));
    line.rotation.x=-Math.PI/2; line.position.y=0.03;
    inner.add(line);
    // 両端のゴール標(紅白ポール)
    [-wTrack/2, wTrack/2].forEach(function(px, idx){{
      var pole=new THREE.Mesh(
        new THREE.CylinderGeometry(0.07,0.07,2.0,6),
        new THREE.MeshStandardMaterial({{color:0xffffff, roughness:0.8}}));
      pole.position.set(px, 1.0, 0); pole.castShadow=true; inner.add(pole);
      var band=new THREE.Mesh(
        new THREE.CylinderGeometry(0.075,0.075,0.5,6),
        new THREE.MeshStandardMaterial({{color:0xe2453f, roughness:0.8}}));
      band.position.set(px, 1.45, 0); inner.add(band);
      // 内側の柱にゴール板を掲げる
      if (idx===0){{
        var c=document.createElement("canvas"); c.width=128; c.height=64;
        var ctx=c.getContext("2d");
        ctx.fillStyle="#1a1a1a"; ctx.fillRect(0,0,128,64);
        ctx.strokeStyle="#ffffff"; ctx.lineWidth=4; ctx.strokeRect(3,3,122,58);
        ctx.fillStyle="#ffffff"; ctx.font="bold 34px sans-serif";
        ctx.textAlign="center"; ctx.textBaseline="middle";
        ctx.fillText("ゴール",64,35);
        var sign=new THREE.Mesh(
          new THREE.PlaneGeometry(1.5,0.75),
          new THREE.MeshBasicMaterial({{map:new THREE.CanvasTexture(c), side:THREE.DoubleSide}}));
        sign.position.set(px-0.85, 1.75, 0);
        inner.add(sign);
      }}
    }});
    grp.add(inner);
    grp.position.set(gx, elevAtFrac(goalFrac), gz);
    grp.rotation.y = Math.atan2(tX, tZ);
    return grp;
  }}
  // 馬房幅(world)。★以前は下限0.5を設けていたため、15頭以上でゲート全幅が
  //   コース幅(thick*SCALE3D)を超え、外枠の馬が柵の外に立っていた。
  //   常にコース幅を頭数で割り、はみ出さないようにする。
  function gateCellW(){{
    return (thick*0.94*SCALE3D)/horses.length;
  }}
  function buildGate3D(){{
    // 発走ゲート。走行方向に対して横一列に馬房を並べ、各房に
    // 仕切り・黒い後扉・網目の前扉・上部の枠番号プレート・アンテナ支柱を組む。
    var grp=new THREE.Group();
    var sp=centerPath.getPointAtLength(startFrac*len);
    var sp2=centerPath.getPointAtLength(((startFrac*len)+3)%len);
    var tx=sp2.x-sp.x, ty=sp2.y-sp.y, tl=Math.sqrt(tx*tx+ty*ty)||1;
    tx/=tl; ty/=tl;
    var sx=(sp.x-cx)*SCALE3D, sz=(sp.y-cy)*SCALE3D;
    var yaw=Math.atan2(tx,ty);          // ローカル+Zが進行方向を向く回転
    var latX=ty, latZ=-tx;              // ローカル+Xに対応する横方向
    var n=horses.length;
    var cellW=gateCellW();
    var frameMat=new THREE.MeshStandardMaterial({{color:0xdcdcd2, roughness:0.7}});
    var backMat=new THREE.MeshStandardMaterial({{color:0x1e1e1e, roughness:0.9}});
    var meshTex=makeMeshPanelTexture();
    var H=cellW*2.4, D=cellW*1.9, pw=cellW*0.12;   // 馬房幅を基準に高さ/奥行きを決める
    for (var i=0;i<n;i++){{
      var off=(i-(n-1)/2)*cellW;
      var cell=new THREE.Group();
      // 左右の仕切り柱
      [-cellW/2, cellW/2].forEach(function(px){{
        var post=new THREE.Mesh(new THREE.BoxGeometry(pw, H, pw*1.2), frameMat);
        post.position.set(px, H/2, 0); post.castShadow=true; cell.add(post);
        // 支柱上のアンテナ
        var ant=new THREE.Mesh(new THREE.CylinderGeometry(pw*0.15,pw*0.15,H*0.42,4), frameMat);
        ant.position.set(px, H+H*0.21, 0); cell.add(ant);
        // 接地部の足
        var foot=new THREE.Mesh(new THREE.BoxGeometry(pw*1.6,H*0.06,D), frameMat);
        foot.position.set(px, H*0.03, 0); foot.castShadow=true; cell.add(foot);
      }});
      // 側面の仕切り板(腰から下)
      [-cellW/2, cellW/2].forEach(function(px){{
        var side=new THREE.Mesh(new THREE.BoxGeometry(pw*0.5, H*0.48, D*0.9), frameMat);
        side.position.set(px, H*0.31, 0); side.castShadow=true; cell.add(side);
      }});
      // 後扉(黒板)
      var back=new THREE.Mesh(new THREE.BoxGeometry(cellW*0.94, H*0.66, pw*0.6), backMat);
      back.position.set(0, H*0.34, -D/2); back.castShadow=true; cell.add(back);
      // 前扉(網目)
      var mtex=meshTex.clone(); mtex.needsUpdate=true; mtex.repeat.set(2,2);
      var meshMat=new THREE.MeshBasicMaterial({{map:mtex, transparent:true, side:THREE.DoubleSide}});
      var door=new THREE.Mesh(new THREE.PlaneGeometry(cellW*0.94, H*0.72), meshMat);
      door.position.set(0, H*0.43, D/2); cell.add(door);
      // 上部の横枠
      var topBar=new THREE.Mesh(new THREE.BoxGeometry(cellW, pw, pw), frameMat);
      topBar.position.set(0, H, 0); topBar.castShadow=true; cell.add(topBar);
      var topBar2=new THREE.Mesh(new THREE.BoxGeometry(cellW, pw*0.8, pw*0.8), frameMat);
      topBar2.position.set(0, H, D/2); cell.add(topBar2);
      // 枠番号プレート
      var plate=new THREE.Mesh(
        new THREE.PlaneGeometry(cellW*0.62,cellW*0.62),
        new THREE.MeshBasicMaterial({{map:makeNumberPlateTexture(horses[i]), side:THREE.DoubleSide}}));
      plate.position.set(0, H+cellW*0.4, D/2+0.02);
      cell.add(plate);
      cell.position.set(sx+latX*off, elevAtFrac(startFrac), sz+latZ*off);
      cell.rotation.y = yaw;
      grp.add(cell);
    }}
    grp.visible = false;
    return grp;
  }}
  function init3D(){{
    if (typeof THREE === "undefined") return;
    var canvasEl = document.getElementById("three3d");
    scene3D = new THREE.Scene();
    scene3D.fog = new THREE.Fog(0x16241a, 26, 85);
    var w = canvasEl.clientWidth || 520;
    camera3D = new THREE.PerspectiveCamera(50, w/300, 0.1, 300);
    renderer3D = new THREE.WebGLRenderer({{canvas:canvasEl, antialias:true, alpha:true}});
    renderer3D.setSize(w, 300, false);
    renderer3D.setPixelRatio(Math.min(window.devicePixelRatio||1, 2));
    renderer3D.shadowMap.enabled = true;
    renderer3D.shadowMap.type = THREE.PCFSoftShadowMap;
    scene3D.add(new THREE.AmbientLight(0xffffff, 0.62));
    var sun = new THREE.DirectionalLight(0xfff4e0, 0.85);
    sun.position.set(-16, 22, 10);
    sun.castShadow = true;
    sun.shadow.mapSize.width = 1024; sun.shadow.mapSize.height = 1024;
    sun.shadow.camera.left=-34; sun.shadow.camera.right=34;
    sun.shadow.camera.top=34; sun.shadow.camera.bottom=-34;
    sun.shadow.camera.near=1; sun.shadow.camera.far=70;
    scene3D.add(sun);
    var groundGeo = new THREE.PlaneGeometry(110, 110, 72, 72);
    // 地面も走路の起伏に合わせて変形させる(走路だけ浮いて見えないように)
    var gpos = groundGeo.attributes.position;
    for (var vi=0; vi<gpos.count; vi++){{
      var gx=gpos.getX(vi), gy=gpos.getY(vi);
      gpos.setZ(vi, terrainElevAt(gx, -gy));   // 後で x軸-90度回転するのでyとzが入れ替わる
    }}
    gpos.needsUpdate = true;
    groundGeo.computeVertexNormals();
    var grassTex = makeSurfaceTexture("#2f6b32", 22, false);
    grassTex.repeat.set(20,20);
    var ground = new THREE.Mesh(groundGeo, new THREE.MeshStandardMaterial({{map:grassTex, roughness:1}}));
    ground.rotation.x = -Math.PI/2; ground.position.y = -0.05;
    ground.receiveShadow = true;
    scene3D.add(ground);
    var trackMesh = buildTrackMesh3D();
    trackMesh.receiveShadow = true;
    scene3D.add(trackMesh);
    scene3D.add(buildRail3D(document.getElementById("trackOuter"), 0.34));
    scene3D.add(buildRail3D(document.getElementById("trackInner"), 0.34));
    scene3D.add(scatterTrees3D());
    scene3D.add(buildGoal3D());
    gate3D = buildGate3D();
    scene3D.add(gate3D);
    horses.forEach(function(h){{
      var tex = makeHorseTexture(h);
      var mat = new THREE.SpriteMaterial({{map:tex, transparent:true}});
      var spr = new THREE.Sprite(mat);
      spr.scale.set(0.7, 0.7, 1);   // コース幅6.6に対し約1割(動画と同等の比率)
      spr.position.y = 0.34;
      scene3D.add(spr);
      h.mesh3D = spr;
      var shadow = new THREE.Mesh(
        new THREE.CircleGeometry(0.24, 12),
        new THREE.MeshBasicMaterial({{color:0x000000, transparent:true, opacity:0.24}}));
      shadow.rotation.x = -Math.PI/2;
      shadow.position.y = 0.03;
      scene3D.add(shadow);
      h.shadow3D = shadow;
    }});
    var dragging=false, lastX=0, lastY=0;
    canvasEl.addEventListener("mousedown", function(e){{ dragging=true; lastX=e.clientX; lastY=e.clientY; }});
    window.addEventListener("mouseup", function(){{ dragging=false; }});
    window.addEventListener("mousemove", function(e){{
      if (!dragging) return;
      camYaw -= (e.clientX-lastX)*0.008;
      camPitchOff = Math.max(-2.5, Math.min(6, camPitchOff - (e.clientY-lastY)*0.03));
      lastX=e.clientX; lastY=e.clientY;
    }});
    canvasEl.addEventListener("wheel", function(e){{
      e.preventDefault();
      camDist = Math.max(4, Math.min(40, camDist + e.deltaY*0.02));
    }}, {{passive:false}});
    canvasEl.addEventListener("touchstart", function(e){{
      if (e.touches.length===1){{ dragging=true; lastX=e.touches[0].clientX; lastY=e.touches[0].clientY; }}
    }}, {{passive:true}});
    window.addEventListener("touchend", function(){{ dragging=false; }});
    window.addEventListener("touchmove", function(e){{
      if (!dragging || e.touches.length!==1) return;
      camYaw -= (e.touches[0].clientX-lastX)*0.008;
      camPitchOff = Math.max(-2.5, Math.min(6, camPitchOff - (e.touches[0].clientY-lastY)*0.03));
      lastX=e.touches[0].clientX; lastY=e.touches[0].clientY;
    }}, {{passive:true}});
    function updateCamera3D(){{
      var p = pathFrac(lastProgress) * len;
      var pt = centerPath.getPointAtLength(p);
      var pt2 = centerPath.getPointAtLength((p+2)%len);
      var tx=pt2.x-pt.x, ty=pt2.y-pt.y, tl=Math.sqrt(tx*tx+ty*ty)||1;
      tx/=tl; ty/=tl;
      var cxp=(pt.x-cx)*SCALE3D, czp=(pt.y-cy)*SCALE3D;
      var cyp=elevAtFrac(pathFrac(lastProgress));
      if (gatePhase){{
        // 枠入り中はゲート全体を斜め前から見せる
        var gyaw = Math.atan2(tx,ty) + camYaw + 0.85;
        var gd = 7.5;
        camera3D.position.set(
          cxp - Math.sin(gyaw)*gd + tx*2.2,
          cyp + 3.2 + camPitchOff,
          czp - Math.cos(gyaw)*gd + ty*2.2);
        camera3D.lookAt(cxp, cyp+0.9, czp);
        return;
      }}
      var yaw = Math.atan2(tx,ty) + camYaw;
      var bx = -Math.sin(yaw)*camDist, bz=-Math.cos(yaw)*camDist;
      camera3D.position.set(cxp+bx, cyp+camHeight+camPitchOff, czp+bz);
      camera3D.lookAt(cxp, cyp+0.6, czp);
    }}
    function idleRender3D(){{
      if (renderer3D) {{
        updateCamera3D();
        renderer3D.render(scene3D, camera3D);
      }}
      requestAnimationFrame(idleRender3D);
    }}
    idleRender3D();
  }}
  function setMode(m){{
    mode = m;
    document.getElementById("viewSvg").style.display = (m==="2d") ? "block" : "none";
    document.getElementById("viewThree").style.display = (m==="3d") ? "block" : "none";
    document.getElementById("btn2d").style.background = (m==="2d") ? "rgba(255,255,255,0.22)" : "rgba(255,255,255,0.14)";
    document.getElementById("btn3d").style.background = (m==="3d") ? "rgba(255,255,255,0.22)" : "rgba(255,255,255,0.14)";
    if (m==="3d" && renderer3D){{
      var w = document.getElementById("viewThree").clientWidth || 520;
      renderer3D.setSize(w, 300, false);
      camera3D.aspect = w/300; camera3D.updateProjectionMatrix();
      // 走行中でなければペース選択画面を出す
      var ov=document.getElementById("startOverlay3d");
      if (ov) ov.style.display = (playing||gatePhase) ? "none" : "block";
    }}
  }}
  (function(){{
    var eb=document.getElementById("elev3d");
    if (eb) eb.innerHTML = GEOM.elevM
      ? 'コース最高地点 <span style="color:#c0392b">▲'+GEOM.elevM+'m</span>'
      : 'ほぼ平坦なコース';
  }})();
  document.getElementById("btn2d").addEventListener("click", function(){{ setMode("2d"); }});
  document.getElementById("btn3d").addEventListener("click", function(){{ setMode("3d"); }});
  init3D();
  function drawTrialStrength(h){{ var noise=-Math.log(-Math.log(Math.random())); return h.strength+noise; }}
  var pace="M", paceShift={{S:-0.04,M:0,H:0.04}}, playing=false,t0=null,speedMult=1,raceDur=7000;
  function pathFrac(progress){{
    // 直線コースは周回しないので %1 で先頭に巻き戻さない
    if (isStraight) return Math.max(0, Math.min(1, startFrac + lapsSpan*progress));
    return (startFrac + lapsSpan*progress) % 1;
  }}
  function place2(progress){{
    lastProgress = progress;
    var stretch = progress>0.8 ? (progress-0.8)/0.2 : 0;
    var order=[];
    horses.forEach(function(h,i){{
      var bias=1+paceShift[pace];
      var styleOffset = baseOf(h) + kickOf(h)*Math.max(0,progress-0.55)/0.45;
      var w = Math.max(0,progress-0.3)/0.7;
      var combined = styleOffset*(1-w) + (h._trialNorm!==undefined?h._trialNorm:0.5)*w;
      var pr=Math.max(0,Math.min(1,progress*bias));
      var p=pathFrac(pr);
      var pt=centerPath.getPointAtLength(p*len);
      var pt2=centerPath.getPointAtLength(((p+0.003)%1)*len);
      var nx2=-(pt2.y-pt.y), ny2=(pt2.x-pt.x), nl=Math.sqrt(nx2*nx2+ny2*ny2)||1;
      // ★前後の開き。以前は combined*10 固定で、コース全長に対し1%程度しか差がつかず
      //   最初から最後まで団子のままだった。スタート直後は密集、進むほど隊列が縦に伸び、
      //   直線でさらに広がるように progress 依存でレンジを広げる。
      var leadRange = 14 + 95*progress + 70*stretch;
      var lead=(combined-0.5)*leadRange;
      var lx=pt.x+dirx/dl*lead, ly=pt.y+diry/dl*lead;
      // ---- 横位置(進路取り) ----
      // ★以前は枠順どおりの横位置にレース中ずっと固定されていて、逃げ・先行馬が
      //   内に潜り込む動きが無かった。実際のレースに合わせて
      //   「スタートは枠順 → 道中は脚質に応じて内/外へ動く → 直線で進路を選んで散る」
      //   という3段階で横位置を作る。この垂直方向は正が内ラチ側。
      var mid=(horses.length-1)/2;
      var laneHome = (mid-i)/Math.max(1,mid);              // +1=最内枠, -1=最外枠
      var tgt = laneOf(h) + (h._laneJit||0);
      var w1 = Math.max(0, Math.min(1, (progress-0.08)/0.27));  // 枠順→脚質の位置取りへ
      var lane = laneHome*(1-w1) + tgt*w1;
      lane += (h._laneOut||0)*stretch;                     // 直線で外に持ち出す馬
      lane = Math.max(-1, Math.min(1, lane));
      var spread = lane * (thick*0.40);
      var fx = lx+nx2/nl*spread, fy = ly+ny2/nl*spread;
      h.el.setAttribute("transform","translate("+fx+","+fy+")");
      if (h.mesh3D){{
        var mx=(fx-cx)*SCALE3D, mz=(fy-cy)*SCALE3D, my=elevAtFrac(p);
        h.mesh3D.position.set(mx, my+0.34, mz);
        if (h.shadow3D) h.shadow3D.position.set(mx, my+0.03, mz);
      }}
      h._offset=combined; order.push(h);
    }});
    order.sort(function(a,b){{return b._offset-a._offset;}});
    var remain=Math.round((1-progress)*GEOM.distance/10)*10;
    document.getElementById("progressLabel").textContent = progress>0.99?"ゴール":(progress<0.15?"テン争い ":"道中 ")+"残り約"+Math.max(remain,0)+"m";
    var d3=document.getElementById("dist3d");
    if (d3) d3.textContent = progress>0.99 ? "0" : String(Math.max(remain,0));
    var s3=document.getElementById("sect3d");
    if (s3){{
      var seg=sectionLabel(progress, remain);
      s3.textContent=seg[0]; s3.style.background=seg[1];
    }}
    var gr=document.getElementById("grade3d");
    if (gr){{
      if (!GEOM.elevM){{ gr.textContent="平坦"; gr.style.color="#5a6b73"; }}
      else {{
        var gp=gradePctAtProgress(progress);
        if (Math.abs(gp)<0.05){{ gr.textContent="平坦"; gr.style.color="#5a6b73"; }}
        else if (gp>0){{ gr.textContent="登り ↗ 勾配"+gp.toFixed(1)+"%"; gr.style.color="#c0392b"; }}
        else {{ gr.textContent="下り ↘ 勾配"+Math.abs(gp).toFixed(1)+"%"; gr.style.color="#2f6ea8"; }}
      }}
    }}
    return order;
  }}
  // ---- 区間ラベル判定 ----
  // ★競馬のコーナー番号は「ゴール前の最終直線の直前のコーナーが必ず4角」。
  //   3角→4角→最終直線 の順で、レース中に最初に迎えるコーナーであっても
  //   最終直線の直前ならそれは4角。以前は楕円の左右どちらの弧かで機械的に
  //   決めていたため、この規則を満たしていなかった。
  //   ここでは「その弧を進んだ先が最終直線かどうか」で3〜4角/1〜2角を判定する。
  var goalIsLower = goalPtActual.y > cy;
  function inStraightAt(pf){{
    var p=centerPath.getPointAtLength(((pf%1)+1)%1*len);
    return {{straight: Math.abs(p.x-cx) <= straightHalf, lower: p.y > cy}};
  }}
  function arcLeadsToHomeStraight(pf){{
    // 現在の弧を進行方向に辿り、最初に到達する直線が最終直線(=ゴールのある側)か
    for (var k=1;k<=180;k++){{
      var s=inStraightAt(pf + k*0.0035);
      if (s.straight) return s.lower === goalIsLower;
    }}
    return false;
  }}
  function sectionLabel(progress, remain){{
    if (progress>0.995) return ["ゴール","#e2453f"];
    if (progress<0.12)  return ["テン争い","#3b7fe0"];
    if (remain<=100)    return ["ゴール前","#e2453f"];
    if (remain<=300)    return ["ラスト300m","#e2453f"];
    var pf=pathFrac(Math.max(0,Math.min(1,progress)));
    var here=inStraightAt(pf);
    if (here.straight) {{
      return here.lower === goalIsLower ? ["直線","#3b7fe0"] : ["向正面","#5a8f3c"];
    }}
    return arcLeadsToHomeStraight(pf) ? ["3〜4角","#3b7fe0"] : ["1〜2角","#3b7fe0"];
  }}
  function rollTrial(){{
    var vals=horses.map(function(h){{return drawTrialStrength(h);}});
    var min=Math.min.apply(null,vals), max=Math.max.apply(null,vals);
    horses.forEach(function(h,i){{
      h._trialNorm=(vals[i]-min)/((max-min)||1);
      // 進路取りの揺らぎ。同じ脚質の馬が完全に重ならないよう馬ごとにばらけさせ、
      // 試行のたびに引き直すので毎回違う位置取りになる。
      h._laneJit = (Math.random()-0.5)*0.42;
      h._laneOut = (Math.random()-0.5)*0.55;
    }});
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
        '<span style="font-size:13px;font-weight:500;flex:1">'+h.name+
          '<span style="font-size:10px;color:rgba(255,255,255,0.45);margin-left:6px">'+
          (h.styleKnown?h.style:'脚質不明')+'</span></span>'+
        '<span style="font-size:11px;color:rgba(255,255,255,0.55)">'+(h.p_win!==undefined?('勝率'+(h.p_win*100).toFixed(0)+'%・'):'')+'複勝率'+(h.p_top3*100).toFixed(0)+'%</span></div>';
    }}).join("");
    document.getElementById("playBtn").textContent="▶ もう一回（別の試行）";
    var ov=document.getElementById("startOverlay3d");
    if (ov && mode==="3d") ov.style.display="block";
  }}
  function placeInGate(){{
    // 枠入り時は各馬をゲート内の自分の馬房に整列させる(前後差は付けない)
    var sp=centerPath.getPointAtLength(startFrac*len);
    var sp2=centerPath.getPointAtLength(((startFrac*len)+3)%len);
    var tx=sp2.x-sp.x, ty=sp2.y-sp.y, tl=Math.sqrt(tx*tx+ty*ty)||1;
    tx/=tl; ty/=tl;
    var nxp=-ty, nyp=tx;
    var n=horses.length;
    var cellSvg=gateCellW()/SCALE3D;  // buildGate3D の馬房幅と一致させる
    horses.forEach(function(h,i){{
      // ★この法線(nxp,nyp)は正が内ラチ側。(i-mid)のままだと1番が外に立ち、
      //   ゲート枠(1番=最内)と馬の位置が左右逆にズレていた。
      var off=((n-1)/2-i)*cellSvg;
      var fx=sp.x+nxp*off, fy=sp.y+nyp*off;
      h.el.setAttribute("transform","translate("+fx+","+fy+")");
      if (h.mesh3D){{
        var mx=(fx-cx)*SCALE3D, mz=(fy-cy)*SCALE3D, my=elevAtFrac(startFrac);
        h.mesh3D.position.set(mx, my+0.34, mz);
        if (h.shadow3D) h.shadow3D.position.set(mx, my+0.03, mz);
      }}
    }});
  }}
  function setSect(label, col){{
    var s3=document.getElementById("sect3d");
    if (s3){{ s3.textContent=label; s3.style.background=col; }}
  }}
  function startSequence(btn){{
    // ★ゲートイン演出: いきなり走り出すと各馬の位置取りが分からないため、
    //   枠入り(ゲート表示・静止) → 発走(ゲート消滅) の2段階を挟む。
    document.getElementById("results").innerHTML="";
    rollTrial();
    playing=false; t0=null;
    lastProgress=0;
    gatePhase=true;
    placeInGate();
    if (gate3D) gate3D.visible = true;
    btn.textContent="枠入り...";
    setSect("枠入り", "#3b7fe0");
    var d3=document.getElementById("dist3d");
    if (d3) d3.textContent=String(GEOM.distance);
    document.getElementById("progressLabel").textContent="枠入り";
    setTimeout(function(){{
      btn.textContent="スタート！";
      setSect("発走", "#e2453f");
      setTimeout(function(){{
        if (gate3D) gate3D.visible = false;
        gatePhase=false;
        playing=true; t0=null;
        btn.textContent="走行中...";
        requestAnimationFrame(frame);
      }}, 600);
    }}, 1800);
  }}
  document.getElementById("playBtn").addEventListener("click", function(){{
    var ov=document.getElementById("startOverlay3d");
    if (ov) ov.style.display="none";
    startSequence(this);
  }});
  // ペース選択(S/M/H)。paceShiftで道中の進み方に反映される。
  Array.prototype.forEach.call(document.querySelectorAll(".paceBtn"), function(b){{
    b.addEventListener("click", function(){{
      pace=this.getAttribute("data-p");
      Array.prototype.forEach.call(document.querySelectorAll(".paceBtn"), function(x){{
        var on = x.getAttribute("data-p")===pace;
        x.style.background = on ? "#3b7fe0" : "#fff";
        x.style.color = on ? "#fff" : "#1c2b34";
      }});
    }});
  }});
  document.getElementById("startRaceBtn").addEventListener("click", function(){{
    document.getElementById("startOverlay3d").style.display="none";
    startSequence(document.getElementById("playBtn"));
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

DB_PATH = Path(__file__).with_name("keibaAI_merged_final.db")


def style_label(pos):
    """run_style_avg(0=前, 1=後ろ)を脚質ラベルに変換。
    閾値は se_pace_v3.run_style_cat の区分(0:〜0.15 / 1:〜0.40 / 2:〜0.70 / 3:それ以上)に合わせてある。
    この区分は実際の4角通過順(平均 3.25 / 4.59 / 6.75 / 9.07番手)と整合することを確認済み。"""
    if pos is None:
        return "中団"
    if pos < 0.15:
        return "逃げ"
    if pos < 0.40:
        return "先行"
    if pos < 0.70:
        return "中団"
    return "追込"


def load_run_styles(horse_names, run_date):
    """出走馬の脚質を se_pace_v3 から取得する。
    ★従来は脚質を馬番順に「逃げ→先行→好位→中団→追込」と機械的に割り当てた見た目用の値で、
      実際の走り方とは無関係だった。ここでDBの実データ(run_style_avg)に置き換える。
    当日のレースはまだ走っていないためレースIDでは引けない。馬名で過去走を辿り、
    開催日より前の最新の値を採用する(未来のデータは使わない)。
    戻り値: {horse_name: run_style_avg}  取得できない馬(新馬など)は含まない。"""
    if not DB_PATH.exists():
        return {}
    cutoff = str(run_date).replace("-", "")[:8]
    try:
        conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?immutable=1", uri=True)
    except sqlite3.Error:
        return {}
    try:
        df = pd.read_sql(
            "SELECT horse_name, race_id, run_style_avg FROM se_pace_v3 "
            "WHERE run_style_avg IS NOT NULL", conn)
    except Exception:
        return {}
    finally:
        conn.close()
    df = df[df["horse_name"].isin(set(horse_names))].copy()
    if df.empty:
        return {}
    df["race_id"] = df["race_id"].astype(str)
    df = df[df["race_id"] < cutoff]
    if df.empty:
        return {}
    latest = df.sort_values("race_id").groupby("horse_name").tail(1)
    return dict(zip(latest["horse_name"], latest["run_style_avg"].astype(float)))


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
    # ★芝の内回り/外回り判定。中山・阪神・京都は同じ場でも内外でコース長も直線長も
    #   まったく別物なので、JRA公式の距離割当表をもとにレース距離からどちらかを決める。
    #   (以前は内外を区別せず片方の値で一律に描画していた)
    lane = None
    if is_turf:
        d_int = int(distance)
        if d_int in (g.get("turf_inner_distances") or []):
            lane = "inner"
        elif d_int in (g.get("turf_outer_distances") or []):
            lane = "outer"
    if is_turf:
        if lane == "inner":
            keys = ("home_stretch_turf_inner_m", "home_stretch_turf_m", "home_stretch_m")
        elif lane == "outer":
            keys = ("home_stretch_turf_outer_m", "home_stretch_turf_m", "home_stretch_m")
        else:
            keys = ("home_stretch_turf_m", "home_stretch_turf_outer_m",
                    "home_stretch_turf_inner_m", "home_stretch_m")
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
        if lane == "inner":
            one_lap = (g.get("one_lap_turf_inner_m") or g.get("one_lap_turf_m") or
                       g.get("one_lap_turf_outer_m") or g.get("one_lap_dirt_m") or 1900)
        elif lane == "outer":
            one_lap = (g.get("one_lap_turf_outer_m") or g.get("one_lap_turf_m") or
                       g.get("one_lap_turf_inner_m") or g.get("one_lap_dirt_m") or 1900)
        else:
            one_lap = (g.get("one_lap_turf_m") or g.get("one_lap_turf_outer_m") or
                       g.get("one_lap_turf_inner_m") or g.get("one_lap_dirt_m") or 1900)
    else:
        one_lap = (g.get("one_lap_dirt_m") or g.get("one_lap_turf_m") or
                   g.get("one_lap_turf_outer_m") or g.get("one_lap_turf_inner_m") or 1900)
    # ★直線長の描画上限が160だったため、阪神の内回り(356.5m)と外回り(473.6m)が
    #   どちらも上限に張り付いて画面上で同じ長さに見えていた。viewBoxを620→820に広げ、
    #   上限を272まで緩めて内外・各場の直線長の差が見た目に出るようにした。
    # 制約: straight_half + ry + 110 <= 410(=cx) かつ ry + 110 <= 150
    straight_half = min(272, max(80, hs * 0.42))  # SVG座標系(820幅)にスケール
    ry = max(24, min(40, 300 - straight_half))
    is_straight_course = (place == "新潟" and surface == "芝" and int(distance) == 1000)
    if is_straight_course:
        # 直線専用コースは「1周」の概念が無く、コース全長=レース距離として扱う
        one_lap = int(distance)
    # 高低差(m)。JRA公式で裏取り済みの course_geometry.json の値をサーフェス別に採用する。
    # 例: 中京ダート=3.4m (netkeiba 3Dシミュレーターの「コース最高地点 ▲3.4m」と一致)
    # ★福島は slope_max_m にしか値が無く、当初のキー一覧から漏れて平坦扱いになっていた
    if is_turf and lane == "inner":
        elev = (g.get("slope_inner_m") or g.get("slope_turf_m") or g.get("slope_m") or
                g.get("slope_max_m"))
    elif is_turf and lane == "outer":
        elev = (g.get("slope_outer_m") or g.get("slope_turf_m") or g.get("slope_m") or
                g.get("slope_max_m"))
    elif is_turf:
        elev = (g.get("slope_turf_m") or g.get("slope_m") or
                g.get("slope_outer_m") or g.get("slope_inner_m") or g.get("slope_max_m"))
    else:
        elev = (g.get("slope_dirt_m") or g.get("slope_m") or
                g.get("slope_turf_m") or g.get("slope_inner_m") or g.get("slope_max_m"))
    try:
        elev = float(elev) if elev is not None else 0.0
    except (TypeError, ValueError):
        elev = 0.0
    return {
        "straightHalf": straight_half,
        "ry": ry,
        "realOneLap": one_lap,
        "distance": int(distance),
        "turn": turn,
        "is_straight_course": is_straight_course,
        "surface": surface,
        "elevM": elev,
        "lane": lane,   # "inner"/"outer"/None(内外の区別が無いコース)
    }


def build_horses(race_df, public: bool, run_styles=None):
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
        # 脚質: DB(se_pace_v3)の実データを使う。取得できない馬(新馬など)は中団相当で扱う。
        pos = (run_styles or {}).get(str(row["horse_name"]))
        known = pos is not None
        if not known:
            pos = 0.5
        pos = max(0.0, min(1.0, float(pos)))
        h = {
            "num": int(row["horse_number"]),
            "name": str(row["horse_name"]),
            "color": color,
            "text_color": text_color,
            "style": style_label(pos) if known else "中団",
            "pos": round(pos, 4),      # 0=前で運ぶ / 1=後ろから
            "styleKnown": bool(known),
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

    # 出走馬の脚質をDBから一括取得(1回のクエリで済ませる)
    _rd = str(df.iloc[0].get("date", "")) if len(df) else ""
    run_styles = load_run_styles(set(df["horse_name"].astype(str)), _rd)
    if run_styles:
        print(f"[脚質] se_pace_v3から{len(run_styles)}頭ぶん取得"
              f"（該当なしの馬は中団扱い）")
    else:
        print("[脚質] DBから取得できず。全馬を中団扱いで描画します")

    index_rows = []
    for race_id, race_df in df.groupby("race_id"):
        row0 = race_df.iloc[0]
        place, distance, surface = row0["place"], row0["distance"], row0["surface"]
        race_name = row0.get("race_name", "")
        date = row0.get("date", "")
        geom = geom_for_race(geom_all, place, surface, distance)
        horses = build_horses(race_df, public=args.public, run_styles=run_styles)
        lane_label = {"inner": "内回り", "outer": "外回り"}.get(geom.get("lane"), "")
        title = f"{place}{surface}{int(distance)}m {race_name}"
        sub = f"{date}｜{place}｜{surface}{int(distance)}m{('・'+lane_label) if lane_label else ''}｜{geom['turn']}回り"
        if geom["is_straight_course"]:
            sub += "（※新潟1000m 直線専用コース。オーバル図とは別トラックのため簡易表示）"
        caption = f"{place} {surface}{int(distance)}m{('・'+lane_label) if lane_label else ''}（{geom['turn']}回り）"
        html = TEMPLATE.format(
            race_title=title, race_sub=sub, course_caption=caption,
            horses_json=json.dumps(horses, ensure_ascii=False),
            geom_json=json.dumps(geom, ensure_ascii=False),
            run_date=date,
        )
        fname = f"race_sim_{safe_filename(race_id)}.html"
        (outdir / fname).write_text(html, encoding="utf-8")
        index_rows.append((race_id, place, surface, distance, race_name, fname))
        print(f"[OK] {race_id} {place} {race_name} -> {fname}")

    # 日付は基本1CSV=1日想定。複数日混在時は最大の日付をこの生成回のラベルにする。
    dates_seen = sorted({str(r) for r in df["date"].dropna().unique()}) if "date" in df.columns else []
    run_date = dates_seen[-1] if dates_seen else "unknown"

    write_home_and_archive(index_rows, outdir, run_date)
    print(f"[OK] {run_date}分のデータ登録 + トップ/アーカイブ シェルを更新（{len(index_rows)}レース）")


NAV_CSS = """
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body { margin:0; font-family:"Hiragino Sans","Yu Gothic",sans-serif; background:#0b1210; color:#fff;
         -webkit-font-smoothing:antialiased; overflow-x:hidden; }
  .nav { display:flex; align-items:center; justify-content:space-between; padding:14px 24px;
         background:rgba(15,26,19,0.9); backdrop-filter:blur(6px); border-bottom:1px solid rgba(255,255,255,0.08);
         position:sticky; top:0; z-index:10; }
  .nav .brand { font-size:18px; font-weight:700; letter-spacing:0.02em; }
  .nav .brand span { color:#5DCAA5; }
  .nav-right { display:flex; align-items:center; gap:16px; }
  .nav a.arclink { color:rgba(255,255,255,0.6); font-size:12px; text-decoration:none; transition:color 0.15s; }
  .nav a.arclink:hover { color:#5DCAA5; }

  /* ---- hero ---- */
  .hero { position:relative; padding:48px 24px 30px; overflow:hidden;
          background:radial-gradient(ellipse at top left,#17301f,#0b1210 68%); }
  .hero::before { content:""; position:absolute; inset:0; z-index:0; pointer-events:none; opacity:0.35;
          background-image:repeating-linear-gradient(115deg, rgba(93,202,165,0.10) 0px, rgba(93,202,165,0.10) 2px,
          transparent 2px, transparent 46px);
          animation: trackmove 14s linear infinite; }
  @keyframes trackmove { 0%{ background-position:0 0; } 100%{ background-position:400px 0; } }
  .hero > * { position:relative; z-index:1; }
  .hero .eyebrow { display:inline-block; font-size:11px; font-weight:700; letter-spacing:0.08em;
                   color:#5DCAA5; background:rgba(93,202,165,0.12); border:1px solid rgba(93,202,165,0.3);
                   padding:3px 10px; border-radius:20px; margin-bottom:14px; }
  .hero h1 { margin:0 0 14px; font-size:29px; letter-spacing:0.01em; font-weight:800; min-height:1.3em; }
  .grad-text { background:linear-gradient(90deg,#5DCAA5,#8fe9c8,#5DCAA5,#4fb0e0);
               background-size:300% 100%; -webkit-background-clip:text; background-clip:text;
               color:transparent; animation:gradshift 6s ease-in-out infinite; }
  @keyframes gradshift { 0%{background-position:0% 50%;} 50%{background-position:100% 50%;} 100%{background-position:0% 50%;} }
  .hero p { margin:14px 0 0; color:rgba(255,255,255,0.65); font-size:14px; line-height:1.8; max-width:640px; }

  /* ---- date switcher ---- */
  .datebar { display:flex; align-items:center; gap:10px; margin-top:2px; }
  .dbtn { width:34px; height:34px; border-radius:50%; border:1px solid rgba(93,202,165,0.35);
          background:rgba(93,202,165,0.08); color:#5DCAA5; font-size:14px; cursor:pointer; transition:all 0.15s; }
  .dbtn:hover:not(:disabled) { background:rgba(93,202,165,0.25); transform:scale(1.08); }
  .dbtn:disabled { opacity:0.25; cursor:default; }
  .dbtn:focus { outline:none; }
  #dateLabel { font-size:13px; font-weight:600; color:rgba(255,255,255,0.85); min-width:150px; }

  /* ---- stats ---- */
  .about { padding:4px 24px 8px; }
  .about-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; max-width:820px; }
  .about-item { background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.07);
                border-radius:12px; padding:14px 16px; transition:border-color 0.2s; }
  .about-item:hover { border-color:rgba(93,202,165,0.35); }
  .about-item .k { font-size:11px; color:rgba(255,255,255,0.45); margin-bottom:4px; }
  .about-item .v { font-size:15px; font-weight:700; color:#5DCAA5; }

  /* ---- skeleton loading ---- */
  .skel { background:linear-gradient(90deg, rgba(255,255,255,0.05) 25%, rgba(255,255,255,0.11) 37%,
          rgba(255,255,255,0.05) 63%); background-size:400% 100%; animation:shimmer 1.4s ease infinite;
          border-radius:8px; }
  @keyframes shimmer { 0%{background-position:100% 0;} 100%{background-position:-100% 0;} }

  .content { padding:20px 24px 12px; }
  .venue-block { margin-top:28px; opacity:0; animation:fadeup 0.5s ease forwards; }
  @keyframes fadeup { from{opacity:0; transform:translateY(10px);} to{opacity:1; transform:translateY(0);} }
  .venue-title { font-size:16px; font-weight:700; color:#5DCAA5; margin-bottom:10px;
                 display:flex; align-items:center; gap:8px; padding-bottom:6px;
                 border-bottom:1px solid rgba(93,202,165,0.15); }
  .venue-count { font-size:11px; font-weight:400; color:rgba(255,255,255,0.45); }
  .card-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:10px; }
  .card { display:flex; gap:10px; align-items:center; background:rgba(255,255,255,0.05);
          border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:12px 14px;
          text-decoration:none; color:#fff; transition:all 0.18s; opacity:0; animation:fadeup 0.45s ease forwards; }
  .card:hover { background:rgba(93,202,165,0.14); border-color:rgba(93,202,165,0.5); transform:translateY(-2px);
                box-shadow:0 6px 18px rgba(93,202,165,0.15); }
  .card-rno { font-size:13px; font-weight:700; color:#5DCAA5; width:34px; flex-shrink:0; }
  .card-name { font-size:13px; font-weight:500; }
  .card-meta { font-size:11px; color:rgba(255,255,255,0.5); margin-top:2px; }
  .datelink { display:flex; align-items:center; justify-content:space-between; background:rgba(255,255,255,0.05);
              border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:14px 16px; margin-bottom:10px;
              text-decoration:none; color:#fff; transition:all 0.18s; opacity:0; animation:fadeup 0.45s ease forwards; }
  .datelink:hover { background:rgba(93,202,165,0.14); border-color:rgba(93,202,165,0.5); transform:translateY(-2px);
                    box-shadow:0 6px 18px rgba(93,202,165,0.15); }
  .datelink .arrow { color:#5DCAA5; font-size:13px; }
  .errbox { padding:40px 24px; text-align:center; color:rgba(255,255,255,0.55); font-size:14px; }
  .errbox a { color:#5DCAA5; }

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


# ============================================================================
# ★2026-07-26設計変更: 「静的シェル + JSONデータ」方式に刷新。
# 理由: 以前はdocs/index.htmlの中身(日付・レース一覧)を毎日まるごと書き換えていたため、
#   Google Sites側の埋め込み(URL埋め込み)がページの見た目を古いままキャッシュしてしまう
#   不具合が繰り返し発生していた(参考: BoatAI姉妹サイトは同じ埋め込み方式でも一度もこの
#   問題が起きていない → 調査の結果、BoatAI側はトップページのHTML自体は不変で、日付ごとの
#   データを小さいJSON経由でJSが取得・描画する構造だった)。
#   同じ構造にすることで、docs/index.html / docs/archive/index.html は生成のたびに
#   "同一内容"になり(=Googleのスナップショットが古くても実害が出ない)、実際に変化するのは
#   docs/data/*.json だけになる。
# ============================================================================

INDEX_SHELL = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
""" + GA_SNIPPET + """<title>競馬AI レースシミュレーション</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>""" + NAV_CSS + """</style></head>
<body>
  <div class="nav">
    <div class="brand">競馬AI<span>レースシム</span></div>
    <div class="nav-right">
      <a class="arclink" href="archive/index.html">過去の予想を見る</a>
      <span id="navCount" style="font-size:12px;color:rgba(255,255,255,0.5)"></span>
    </div>
  </div>
  <div class="hero">
    <span class="eyebrow">AI RACE SIMULATION</span>
    <h1 id="heroTitle" class="grad-text">読み込み中…</h1>
    <div class="datebar">
      <button class="dbtn" id="prevBtn" disabled>&#9664;</button>
      <span id="dateLabel">--</span>
      <button class="dbtn" id="nextBtn" disabled>&#9654;</button>
    </div>
    <p>予測モデルが算出した複勝率をもとに、各馬の展開とゴールまでのシミュレーションを再現しています。実際の周回コース(直線距離・回り・高低差)をJRA全10場ぶん再現し、コースの特徴も反映しています。開催場ごとにレースを一覧表示しているので、気になるレースをタップして再生してみてください。</p>
  </div>
  <div class="about">
    <div class="about-grid" id="statsGrid">
      <div class="about-item"><div class="k">開催場数</div><div class="v skel">&nbsp;</div></div>
      <div class="about-item"><div class="k">掲載レース数</div><div class="v skel">&nbsp;</div></div>
      <div class="about-item"><div class="k">着順の決め方</div><div class="v">複勝率ベース抽選</div></div>
      <div class="about-item"><div class="k">対象</div><div class="v">中央競馬 全場</div></div>
    </div>
  </div>
  <div class="content" id="raceContent">
    <div class="venue-block" style="animation-delay:0s">
      <div class="skel" style="height:20px;width:120px;margin-bottom:12px"></div>
      <div class="card-grid">
        <div class="skel" style="height:56px"></div><div class="skel" style="height:56px"></div>
        <div class="skel" style="height:56px"></div><div class="skel" style="height:56px"></div>
      </div>
    </div>
  </div>
  """ + DISCLAIMER_HTML + """
<script>
(function(){
  var params = new URLSearchParams(location.search);
  var reqDate = params.get('date');

  function showError(msg){
    document.getElementById('raceContent').innerHTML =
      '<div class="errbox">'+msg+'<br><br><a href="index.html">最新のシミュレーションに戻る</a></div>';
    document.getElementById('heroTitle').textContent = '競馬AI レースシミュレーション';
  }

  function animateCount(el, target){
    var start = 0, dur = 700, t0 = null;
    function step(ts){
      if(!t0) t0 = ts;
      var p = Math.min(1, (ts - t0) / dur);
      el.textContent = Math.round(start + (target - start) * p) + (el.dataset.suffix||'');
      if(p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function render(data, dates){
    document.getElementById('heroTitle').innerHTML =
      'レースシミュレーション（<span class="grad-text">' + data.date_label + '</span>）';
    document.getElementById('dateLabel').textContent = data.date_label;
    document.getElementById('navCount').textContent = data.venues.reduce(function(a,v){return a+v.races.length;},0) + 'レース掲載';

    var statsGrid = document.getElementById('statsGrid');
    var totalRaces = data.venues.reduce(function(a,v){return a+v.races.length;},0);
    var vEl = statsGrid.children[0].querySelector('.v');
    var rEl = statsGrid.children[1].querySelector('.v');
    vEl.classList.remove('skel'); rEl.classList.remove('skel');
    vEl.dataset.suffix = '場'; rEl.dataset.suffix = 'レース';
    animateCount(vEl, data.venues.length);
    animateCount(rEl, totalRaces);

    var html = '';
    data.venues.forEach(function(v, vi){
      html += '<div class="venue-block" style="animation-delay:'+(vi*0.06)+'s">' +
        '<div class="venue-title">' + v.place + '<span class="venue-count">' + v.races.length + 'レース</span></div>' +
        '<div class="card-grid">';
      v.races.forEach(function(r, ri){
        html += '<a class="card" href="' + r.file + '" style="animation-delay:' + ((vi*0.06)+(ri*0.03)) + 's">' +
          '<div class="card-rno">' + r.rno + 'R</div>' +
          '<div class="card-body"><div class="card-name">' + r.name + '</div>' +
          '<div class="card-meta">' + r.surface + r.distance + 'm</div></div></a>';
      });
      html += '</div></div>';
    });
    document.getElementById('raceContent').innerHTML = html;

    var idx = dates.indexOf(data.date);
    var prevBtn = document.getElementById('prevBtn'), nextBtn = document.getElementById('nextBtn');
    // dates は新しい日付が先頭(降順)。「次」=より新しい日付、「前」=より古い日付。
    if (idx >= 0 && idx < dates.length - 1) {
      prevBtn.disabled = false;
      prevBtn.onclick = function(){ location.search = '?date=' + dates[idx+1]; };
    }
    if (idx > 0) {
      nextBtn.disabled = false;
      nextBtn.onclick = function(){ location.search = '?date=' + dates[idx-1]; };
    }
  }

  fetch('data/manifest.json').then(function(r){ return r.json(); }).then(function(manifest){
    var dates = manifest.dates || [];
    if (!dates.length) { showError('データがまだありません。'); return; }
    var date = (reqDate && dates.indexOf(reqDate) >= 0) ? reqDate : dates[0];
    return fetch('data/day_' + date + '.json').then(function(r){
      if (!r.ok) throw new Error('not found');
      return r.json();
    }).then(function(data){ render(data, dates); });
  }).catch(function(){
    showError('データの読み込みに失敗しました。時間をおいて再度お試しください。');
  });
})();
</script>
</body></html>"""

ARCHIVE_SHELL = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
""" + GA_SNIPPET + """<title>競馬AI レースシミュレーション（過去分アーカイブ）</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>""" + NAV_CSS + """</style></head>
<body>
  <div class="nav">
    <div class="brand">競馬AI<span>レースシム</span></div>
    <div class="nav-right"><a class="arclink" href="../index.html">最新に戻る</a></div>
  </div>
  <div class="hero">
    <span class="eyebrow">ARCHIVE</span>
    <h1 class="grad-text">過去の予想アーカイブ</h1>
    <p id="archiveSub">読み込み中…</p>
  </div>
  <div class="content" id="archiveList">
    <div class="skel" style="height:52px;margin-bottom:10px"></div>
    <div class="skel" style="height:52px;margin-bottom:10px"></div>
    <div class="skel" style="height:52px;margin-bottom:10px"></div>
  </div>
  """ + DISCLAIMER_HTML + """
<script>
(function(){
  function fmt(d){
    var m = d.match(/^(\\d{4})-(\\d{2})-(\\d{2})$/);
    return m ? (m[1]+'年'+parseInt(m[2],10)+'月'+parseInt(m[3],10)+'日') : d;
  }
  fetch('../data/manifest.json').then(function(r){ return r.json(); }).then(function(manifest){
    var dates = manifest.dates || [];
    document.getElementById('archiveSub').textContent =
      '日付ごとのレースシミュレーション一覧です。見たい日付を選んでください（全' + dates.length + '日分）。';
    var html = dates.map(function(d, i){
      return '<a class="datelink" href="../index.html?date=' + d + '" style="animation-delay:' + (i*0.03) + 's">' +
        '<span>' + fmt(d) + '</span><span class="arrow">見る →</span></a>';
    }).join('');
    document.getElementById('archiveList').innerHTML = html || '<div class="errbox">まだデータがありません。</div>';
  }).catch(function(){
    document.getElementById('archiveSub').textContent = '読み込みに失敗しました。';
    document.getElementById('archiveList').innerHTML = '';
  });
})();
</script>
</body></html>"""


def write_home_and_archive(index_rows, outdir, run_date):
    """docs/index.html と docs/archive/index.html は"不変の静的シェル"として1回書けば
    以後内容が変わらない(常に同一バイト列)。実際に変化するのは docs/data/*.json のみ。
    これにより、Googleサイト埋め込みが古いHTMLスナップショットをキャッシュしても、
    そのスナップショット自身のJSが実行時にJSONを取りに行くため最新表示になる
    (BoatAI姉妹サイトと同じ構造)。"""
    data_dir = outdir / "data"
    data_dir.mkdir(exist_ok=True)
    (outdir / "archive").mkdir(exist_ok=True)

    # 1. 当日分データJSON
    by_place = {}
    for race_id, place, surface, distance, race_name, fname in index_rows:
        by_place.setdefault(place, []).append(
            {"race_id": str(race_id), "rno": int(str(race_id)[-2:]),
             "name": race_name, "surface": surface, "distance": int(distance), "file": fname}
        )
    day_data = {
        "date": run_date,
        "date_label": _format_date_label(run_date),
        "venues": [{"place": place, "races": races} for place, races in by_place.items()],
    }
    (data_dir / f"day_{run_date}.json").write_text(
        json.dumps(day_data, ensure_ascii=False, indent=1), encoding="utf-8")

    # 2. manifest.json (既存日付一覧 + 今回分。降順ソート)
    manifest_path = data_dir / "manifest.json"
    dates = []
    if manifest_path.exists():
        try:
            dates = json.loads(manifest_path.read_text(encoding="utf-8")).get("dates", [])
        except Exception:
            dates = []
    if run_date not in dates:
        dates.append(run_date)
    dates = sorted(set(dates), reverse=True)
    manifest_path.write_text(json.dumps({"dates": dates}, ensure_ascii=False, indent=1), encoding="utf-8")

    # 3. シェル本体(index.html / archive/index.html)は常に同一内容で上書き
    (outdir / "index.html").write_text(INDEX_SHELL, encoding="utf-8")
    (outdir / "archive" / "index.html").write_text(ARCHIVE_SHELL, encoding="utf-8")


if __name__ == "__main__":
    main()
