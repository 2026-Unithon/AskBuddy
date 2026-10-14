"""Render the frozen synthetic diagnostic as self-contained HTML and a shareable PDF."""
import html
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'output/r-performance-20261006/run-02'
REPORT=json.loads((DATA/'results.json').read_text('utf-8'))
INPUTS=json.loads((DATA/'inputs.json').read_text('utf-8'))
OUT=ROOT/'output/pdf'
OUT.mkdir(parents=True,exist_ok=True)
LABELS={'ANSWER':'답변','CLARIFY':'재질문','ESCALATE':'점주 확인','REFUSE':'거절','SAFE_ROUTE':'안전 안내',None:'미실행'}
SCOPE='가상 매장 3개 RAW 카드 / 고정 후보 / 판단·렌더링 단계 / 실제 모델·검색 미측정'
EXPLAIN={
    'S07':'같은 HOT 조건을 한국어로 표현하면 현재 RAW 경로가 답변을 확정하지 못합니다.',
    'S08':'뜨거운 것을 HOT으로 연결하는 자연어 표현 해석이 이 경로에서는 지원되지 않습니다.',
    'S09':'라테/라떼 표기 차이로 대상을 확정하지 못하고 다시 선택하게 합니다.',
    'S10':'핫이라는 표현을 HOT과 동일하게 처리하지 못합니다.',
    'S11':'밀크/우유 동의어 표현을 이 경로에서 확정하지 못합니다.',
    'S13':'온도를 확인하면 답할 수 있는 질문이지만 재질문 대신 점주 확인으로 넘어갑니다.',
    'S14':'온도를 확인할 기회를 제공하지 않고 점주 확인으로 넘어갑니다.',
    'D01':'첫 턴에서 선택지를 제공하지 않아 예정된 HOT 선택 턴을 실행하지 못했습니다.',
    'D02':'첫 턴에서 선택지를 제공하지 않아 예정된 ICE 선택 턴을 실행하지 못했습니다.',
    'D03':'대상 선택은 처리했지만 RAW 카드에서 온도를 확인하는 다음 단계로 이어지지 못했습니다.',
    'D04':'이름을 생략한 후속 발화를 이전 답변 대상과 연결하지 못했습니다.',
    'D05':'이전 음료를 생략한 후속 질문에서 대상을 다시 선택하게 합니다.',
}


def expectation(turn):
    return LABELS[turn['expected_action']]+(' · '+turn['expected_text'] if turn.get('expected_text') else '')


def actual(turn):
    return LABELS[turn.get('actual_action')]


def build_html():
    cards=[]
    for row in REPORT['rows']:
        turns=[]
        for i,t in enumerate(row['turns'],1):
            response=t.get('output') or t.get('failure') or t.get('error','미실행')
            options=' / '.join(t.get('allowed_options',[]))
            turns.append(f'<div class="turn"><h4>{i}턴 · {html.escape(t["question"])}</h4>'
                f'<div class="compare"><div><small>기대 결과</small><p>{html.escape(expectation(t))}</p></div>'
                f'<div><small>실제 결과 · {actual(t)}</small><p>{html.escape(response)}</p>'
                +(f'<p class="muted">선택지: {html.escape(options)}</p>' if options else '')
                +f'<p class="muted">출처: {", ".join(c.get("source_id", "") or "" for c in t.get("citations",[])) or "없음"}</p></div></div></div>')
        cards.append(f'<article data-result="{"pass" if row["passed"] else "fail"}" data-group="{html.escape(row["group"])}">'
            f'<header><span class="tag {"pass" if row["passed"] else "fail"}">{"통과" if row["passed"] else "실패"}</span>'
            f'<b>{row["id"]} · {row["group"]}</b></header>'+''.join(turns)
            +(f'<p class="finding">{EXPLAIN[row["id"]]}</p>' if row['id'] in EXPLAIN else '')+'</article>')
    groups=''.join(f'<tr><td>{g["group"]}</td><td>{g["passed"]}/{g["total"]}</td>'
        f'<td><progress value="{g["passed"]}" max="{g["total"]}"></progress></td></tr>' for g in REPORT['groups'])
    options=''.join(f'<option>{g["group"]}</option>' for g in REPORT['groups'])
    document='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AskBuddy 답변 품질 1차 진단</title><style>
:root{color-scheme:light;font-family:Malgun Gothic,Arial,sans-serif;color:#192b40;background:#f4f6fa}*{box-sizing:border-box}body{margin:0}main{max-width:1040px;margin:auto;padding:44px 24px}h1{font-size:34px;letter-spacing:-1px}h2{font-size:23px;margin-top:34px}p{line-height:1.7;white-space:pre-line}small,.muted{color:#617085;font-size:13px}.hero{background:#142941;color:white;padding:30px;border-radius:20px}.hero p{color:#d3deec}.badge{font-size:12px;color:#afcff7;letter-spacing:2px}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:22px 0}.stat{padding:22px;background:white;border-radius:14px;border:1px solid #dde4ed}.stat b{font-size:32px;display:block;margin:8px 0}.notice{background:#fff3d8;padding:18px 22px;border-radius:12px;color:#634c23}table{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden}td,th{text-align:left;padding:12px 18px;border-bottom:1px solid #edf0f5}progress{width:100%;accent-color:#2d6cce}.controls{display:flex;gap:12px;margin:20px 0;position:sticky;top:0;background:#f4f6fa;padding:12px 0;z-index:1}select{font:inherit;padding:10px;border:1px solid #cad3df;border-radius:8px}article{background:white;border:1px solid #dfe5ed;border-radius:14px;padding:22px;margin-bottom:16px}header{display:flex;gap:12px;align-items:center}.tag{font-size:12px;padding:5px 10px;border-radius:20px}.pass{background:#e2f4ed;color:#176a47}.fail{background:#ffebe6;color:#a13d2e}.compare{display:grid;grid-template-columns:1fr 1fr;gap:16px}.compare>div{background:#f5f7fa;padding:15px;border-radius:9px}.compare p{margin:7px 0}.turn{margin-top:18px}.finding{border-left:3px solid #d68d46;padding-left:12px;font-size:14px}.method{padding:22px;background:#e9eef6;border-radius:12px}footer{font-size:12px;color:#647285;padding-top:25px;line-height:1.8}button{border:0;background:#2d6cce;color:white;padding:11px 18px;border-radius:8px;cursor:pointer}article[hidden]{display:none}@media(max-width:640px){.stats,.compare{grid-template-columns:1fr}main{padding:20px 14px}h1{font-size:27px}.controls{flex-wrap:wrap}}@media print{.controls,button{display:none}article{break-inside:avoid}.hero{background:#eee;color:#142941}.hero p{color:#142941}main{max-width:none;padding:0}}
</style><main><section class="hero"><div class="badge">ASKBUDDY / ENGINE DIAGNOSTIC / 2026.10.06</div>
<h1>명시적인 질문은 통과,<br>표현 변화와 후속 맥락은 보완 필요</h1><p>현재 R 코드에 공개 가능한 합성 질문을 입력한 1차 진단입니다.<br>실사용 채팅 정확도를 주장하는 자료가 아닙니다.</p></section>
<div class="stats"><div class="stat"><small>고정 시나리오 통과</small><b>16 / 28</b><small>57.1% · 이 합성 표본에만 해당</small></div><div class="stat"><small>실패 사례</small><b>12개</b><small>실패와 미실행 후속 턴 모두 보존</small></div><div class="stat"><small>종합 채팅 정확도</small><b>미측정</b><small>실제 검색·모델·HTTP 평가 필요</small></div></div>
<div class="notice"><b>수치의 범위</b><br>SEARCH_SCOPE. 실제 자료·고객 대화는 사용하지 않았습니다. 아래 점수를 전체 서비스 성능이나 일반 사용자 정확도로 인용하면 안 됩니다.</div>
<h2>유형별 결과</h2><table><thead><tr><th>유형</th><th>통과 / 전체</th><th>표본 내 통과 비율</th></tr></thead><tbody>GROUP_ROWS</tbody></table>
<p class="muted">단일 질문 22개 + 2턴 시나리오 6개. 대화는 모든 예정 턴이 통과해야 시나리오 통과입니다. 선택형 맥락 3건 중 2건은 첫 턴 실패로 두 번째 턴 미실행입니다.</p>
<h2>평가에 사용한 지식</h2><p>가상 카드 1: HOT 라테 우유 225ml 넣는다.<br>가상 카드 2: ICE 아메리카노 물 150ml 넣는다.<br>가상 카드 3: 질문: 마감 준비는 어떻게 해? / 답변: 장비를 세척한다.</p>
<h2>전체 사례 · 기대 결과와 실제 응답</h2><div class="controls"><select id="result"><option value="all">전체 28개</option><option value="fail">실패 12개</option><option value="pass">통과 16개</option></select><select id="group"><option value="all">모든 유형</option>GROUP_OPTIONS</select><button onclick="window.print()">인쇄 / PDF 저장</button></div>CASE_CARDS
<h2>방법과 해석</h2><div class="method"><p>① 결과를 보기 전에 질문·기대 행동·정답 문구·출처를 고정했습니다. 기대 기준은 이번 작업에서 작성한 합성 기준이며 독립 사람 채점을 거치지 않았습니다.<br>② 모든 카드 블록을 후보로 주고 실제 decide/render 함수를 실행했습니다. 선택형 후속 턴은 실제 accept_selection 함수를 사용했습니다.<br>③ 대화는 라우터의 입력 조합을 메모리에서 재현했습니다. HTTP·DB 세션·직원 알림을 실행한 종단 대화 시험은 아닙니다.<br>④ 기대 행동, 필수 문구, 출처 ID를 대조했습니다. 자유로운 답변 전체의 의미를 자동 판정한 것은 아닙니다.<br>⑤ 실패·미실행을 분모에서 제외하지 않았습니다. 28개는 편의 표본이며 모집단 정확도나 통계적 신뢰구간을 제시하지 않습니다.</p></div>
<h2>확인된 개선 방향</h2><p>1. RAW 답변에서도 HOT/따뜻한, 라테/라떼 같은 표현을 검증된 범위에서 연결하기<br>2. 온도 정보가 빠지면 점주 전달보다 먼저 재질문할 수 있도록 연결하기<br>3. 응답 이후 지시어·생략 표현이 이전 대상과 조건을 이어받도록 검증하기</p>
<p>이번 실행의 실패는 주로 답할 수 있는 질문을 보류하거나 불필요하게 재질문한 경우였습니다. 제한된 표본에서 잘못된 사실 답변이 관측되지 않았다고 해서 일반적인 환각률이 0이라는 의미는 아닙니다.</p>
<footer>기준 코드: COMMIT · 유료 호출: 0회 · 실제 응답시간/원가: 미측정<br>추적 자료: run-02/inputs.json, run-02/results.json · 재현: api/scripts/measure_r_share_probe.py<br>초기 수집기 실행은 contract_version 누락으로 중단되었으며, 수집기만 보완한 뒤 동일 입력으로 실행했습니다. 제품 코드는 수정하지 않았습니다.<br>이 문서는 로컬 파일입니다. 파일 자체를 전달하면 네트워크 없이 열 수 있으며 외부 서비스에 게시하지 않았습니다.</footer>
</main><script>function filter(){let r=document.querySelector('#result').value,g=document.querySelector('#group').value;document.querySelectorAll('article').forEach(a=>a.hidden=!( (r==='all'||a.dataset.result===r)&&(g==='all'||a.dataset.group===g)));}document.querySelectorAll('select').forEach(s=>s.addEventListener('change',filter));</script></html>'''
    document=document.replace('SEARCH_SCOPE',SCOPE).replace('GROUP_ROWS',groups).replace('GROUP_OPTIONS',options).replace('CASE_CARDS',''.join(cards)).replace('COMMIT',REPORT['git_commit'][:12])
    (DATA.parent/'AskBuddy-performance.html').write_text(document,encoding='utf-8')


def build_pdf():
    pdfmetrics.registerFont(TTFont('Korean','C:/Windows/Fonts/malgun.ttf'))
    pdfmetrics.registerFont(TTFont('KoreanBold','C:/Windows/Fonts/malgunbd.ttf'))
    pdfmetrics.registerFontFamily('Korean',normal='Korean',bold='KoreanBold')
    navy=colors.HexColor('#182d47'); muted=colors.HexColor('#596d85')
    style=ParagraphStyle('body',fontName='Korean',fontSize=9.5,leading=15,wordWrap='CJK',textColor=navy,spaceAfter=8)
    title=ParagraphStyle('title',parent=style,fontName='KoreanBold',fontSize=24,leading=34,spaceAfter=16)
    h2=ParagraphStyle('h2',parent=style,fontName='KoreanBold',fontSize=14,leading=22,spaceBefore=10,spaceAfter=10)
    small=ParagraphStyle('small',parent=style,fontSize=8,leading=12,textColor=muted)
    def p(text,s=style):return Paragraph(escape(text).replace('\n','<br/>'),s)
    def table(rows,widths,smalltext=False):
        data=[[p(str(cell),small if smalltext else style) for cell in row] for row in rows]
        t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e6edf6')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),5),
            ('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#dce4ee'))]))
        return t
    story=[p('ASKBUDDY / 2026.10.06 / 합성 진단',small),p('답변 품질 1차 진단\n성공과 실패를 함께 공개합니다',title),
        p('현재 코드의 답변 판단·출처 렌더링을 점검했습니다. 실제 검색·모델을 포함한 서비스 전체 정확도는 아직 측정하지 않았습니다.'),
        table([['고정 시나리오 통과','실패 사례','실사용 정확도'],['16 / 28 (57.1%)','12개 보존','미측정']],[170,160,175]),
        p('유형별 결과',h2),table([['유형','통과 / 전체','해석']]+[
            [g['group'],f"{g['passed']} / {g['total']}",('전부 통과' if g['passed']==g['total'] else '보완 필요')]
            for g in REPORT['groups']],[240,95,170]),
        Spacer(1,10),p('이 수치의 범위',h2),p(SCOPE),
        p('단일 질문 22개와 2턴 대화 6개를 결과 확인 전에 고정했습니다. 모든 지식 카드를 후보로 제공했으므로 검색 성공률은 측정하지 않았습니다. 선택형 맥락 3개 중 2개는 첫 턴 실패로 후속 턴을 실행하지 못했으며 실패에 포함했습니다.',small),
        p('57.1%를 AskBuddy 전체 정확도라고 소개하면 안 됩니다. 이 합성 표본에 대한 통과율입니다. 모델·검색·DB·HTTP·독립 사람 채점은 포함되지 않았습니다.',small),PageBreak(),
        p('어떤 질문에서 실패했나',title),p('같은 지식이 있어도 질문 표현과 맥락에 따라 응답이 달라졌습니다. 아래는 이번 실행에서 실제로 관측한 사례입니다.')]
    for ident in ['S07','S09','S13','D04']:
        row=next(r for r in REPORT['rows'] if r['id']==ident)
        t=row['turns'][-1]
        seq=' → '.join(ti['question'] for ti in row['turns'])
        story.append(KeepTogether([p(f'{ident} · {row["group"]}',h2),p('질문: '+seq),
            p('기대: '+expectation(t)),p('실제: '+(t.get('output') or '미실행')),
            p(EXPLAIN[ident],small)]))
    story.extend([Spacer(1,10),p('성공 대조',h2),p('“HOT 라테 우유 얼마나?”에는 “HOT 라테 우유 225ml 넣는다.”와 출처 1을 반환했습니다. 이 경로에서는 명시적 HOT 표현은 통과하고 “따뜻한” 표현은 점주 확인으로 넘어갔습니다.'),PageBreak(),
        p('단일 질문 22개 전체 결과',title),p('채점: 기대 행동 + 답변 사례의 필수 문구 + 지정 출처. 문장 전체의 독립적 의미 채점은 아닙니다.',small)])
    singles=[r for r in REPORT['rows'] if r['id'].startswith('S')]
    story.append(table([['ID / 질문','기대','실제','판정']]+[[r['id']+'  '+r['turns'][0]['question'],LABELS[r['turns'][0]['expected_action']],actual(r['turns'][0]),'통과' if r['passed'] else '실패'] for r in singles],[285,75,75,70],True))
    story.extend([Spacer(1,12),p('가상 매장 지식',h2),p('1. HOT 라테 우유 225ml 넣는다.\n2. ICE 아메리카노 물 150ml 넣는다.\n3. 질문: 마감 준비는 어떻게 해? / 답변: 장비를 세척한다.',small),PageBreak(),p('맥락 진단과 재현 범위',title)])
    dialogue=[r for r in REPORT['rows'] if r['id'].startswith('D')]
    story.append(table([['ID / 2턴 시나리오','실제 행동 순서','판정']]+[[r['id']+'  '+' → '.join(t['question'] for t in r['turns']),' → '.join(actual(t) for t in r['turns']),'통과' if r['passed'] else '실패'] for r in dialogue],[300,140,65],True))
    story.extend([p('실행 방법',h2),p('실제 decide/render 함수를 사용했습니다. 선택형 문맥은 accept_selection을 호출하고, 라우터의 질문·확정 조건 조합을 메모리에서 재현했습니다. 영속 세션·HTTP·DB까지 실행한 종단 대화 평가는 아닙니다.'),
        p('판정 기준과 한계',h2),p('기대 기준은 이번 작업에서 작성한 고정 합성 기준입니다. 독립 평가자의 검토를 거치지 않았고, 28개는 실제 직원 질문 분포를 대표하지 않습니다. 선택적 의미 adapter와 실제 검색·모델은 호출하지 않았습니다. 실사용 지연과 원가는 미측정이며 유료 호출은 0회입니다.'),
        p('개선 우선순위',h2),p('1. RAW 카드의 자연어 표현·동의어 처리\n2. RAW 카드에서 부족한 조건을 재질문으로 확인하는 연결\n3. 답변 이후 지시어·생략 발화의 대상과 조건 유지'),
        p('재현 자료',h2),p('기준 커밋: '+REPORT['git_commit']+'\n입력/출력: output/r-performance-20261006/run-02/inputs.json 및 results.json\n실행기: api/scripts/measure_r_share_probe.py\n초기 실행은 수집기의 contract_version 누락으로 중단되었습니다. 수집기만 보완하고 동일 입력으로 실행했습니다. 제품 코드는 변경하지 않았습니다.',small),
        p('공유할 때 사용할 설명',h2),p('“현재 R 엔진의 합성 진단 28개 중 16개가 기대 결과와 일치했습니다. 명시적인 질문은 통과했고, 자연어 표현 변화와 후속 맥락에서 보완점을 발견했습니다. 종합 채팅 정확도는 별도 실사용 평가가 필요합니다.”')])
    def page(canvas,doc):
        canvas.setStrokeColor(colors.HexColor('#dce4ee'));canvas.line(45,39,550,39)
        canvas.setFont('Korean',7);canvas.setFillColor(muted)
        canvas.drawString(45,26,'AskBuddy | 합성 진단 · 전체 서비스 정확도 아님 | 2026.10.06')
        canvas.drawRightString(550,26,str(doc.page))
    doc=SimpleDocTemplate(str(OUT/'AskBuddy-performance-20261006.pdf'),pagesize=(595.28,841.89),
        rightMargin=45,leftMargin=45,topMargin=39,bottomMargin=51,title='AskBuddy 답변 품질 1차 합성 진단',author='AskBuddy')
    doc.build(story,onFirstPage=page,onLaterPages=page)


if __name__=='__main__':
    build_html()
    build_pdf()
    print('Created HTML and PDF report')
