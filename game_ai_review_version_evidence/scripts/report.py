#!/usr/bin/env python3
"""Validate structural provenance and render an offline review. No external dependencies."""
import argparse
import collections
import html
import json
import re
from pathlib import Path

STATUSES = {'confirmed':'断言已证','conditional':'条件待证','requirement_unverified':'需求有效性待核','inactive_config':'配置未启用','refuted':'已反证','unresolved':'待确认'}
ORIGINS = {'new_implementation':'新增实现','new_requirement':'新需求','migration_gap':'迁移适配','historical':'历史行为','unknown':'归因待核'}
SEVERITIES = {'P0':'紧急','P1':'高','P2':'中','P3':'低','P4':'轻微'}
CLAIM_SCOPES = {'local_contract':'局部合同断言','user_flow':'用户流程断言'}
FLOW_STATES = {'reachable':'已证流程可达','blocked_by_confirmed_issue':'被已确认问题阻断','unproved':'流程可达性未证','inactive_config':'本版配置未启用'}
PRESENTATION_VERSION = 'delivery-entry-v4.1'
PENDING_STATUSES = {'conditional', 'requirement_unverified', 'unresolved'}
NEW_ORIGINS = {'new_implementation', 'new_requirement', 'migration_gap'}

def display_bucket(finding):
    if finding.get('finding_kind') == 'improvement':
        return 'archive'
    if finding['status'] == 'confirmed':
        return finding['severity']
    if finding['status'] in PENDING_STATUSES:
        return 'pending'
    return 'archive'

def origin_group(finding):
    if display_bucket(finding) not in SEVERITIES:
        return ''
    if finding['origin'] == 'migration_gap' and finding.get('origin_subtype') == 'legacy_code_new_config':
        return 'legacy_code_new_config'
    if finding['origin'] in NEW_ORIGINS:
        return 'new_or_omission'
    return 'historical' if finding['origin'] == 'historical' else 'unknown'

def origin_counts(doc):
    counts = collections.Counter(origin_group(f) for f in doc['findings'])
    return {key: counts[key] for key in ('new_or_omission', 'historical', 'legacy_code_new_config', 'unknown')}

def origin_summary_labels(doc):
    def label(role, fallback):
        for key in (role + '_label', role + '_ref'):
            value = doc.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        refs = sorted({s['requested_ref'].strip() for s in doc.get('sources', [])
                       if s.get('kind') == 'git' and s.get('version') == doc.get(role)
                       and isinstance(s.get('requested_ref'), str) and s['requested_ref'].strip()})
        return ' / '.join(refs) if refs else fallback
    return {'new_or_omission': label('target', '本次') + '新增 / 遗漏',
            'historical': label('baseline', '基线') + '历史问题',
            'legacy_code_new_config': '旧代码 × 新配置', 'unknown': '归因未知'}

def presentation_counts(doc):
    buckets = collections.Counter(display_bucket(f) for f in doc['findings'])
    severity = {p: buckets[p] for p in SEVERITIES}
    return {'version': PRESENTATION_VERSION, 'confirmed_total': sum(severity.values()),
            'pending_total': buckets['pending'], 'severity_confirmed': severity,
            'main_total': sum(severity.values()) + buckets['pending'],
            'archive_total': buckets['archive'],
            'origin_confirmed': origin_counts(doc),
            'origin_labels': origin_summary_labels(doc),
            'pending_statuses': sorted(PENDING_STATUSES),
            'policy': 'P0～P4仅统计确定问题；待确认单列；已反证、配置未启用及改进建议不计入问题总数。'}

def severity_rows():
    source = Path(__file__).resolve().parent.parent / 'references' / 'severity.md'
    rows = [tuple(c.strip() for c in line.strip().strip('|').split('|'))
            for line in source.read_text().splitlines() if line.startswith('| P')]
    if len(rows) != 5 or any(len(row) != 3 for row in rows):
        raise ValueError('severity.md must define exactly five P0～P4 rows')
    return rows

def presentation_markdown(doc):
    n = presentation_counts(doc)
    return ['## 问题统计', '', f"确定问题 **{n['confirmed_total']}**；待确认 **{n['pending_total']}**。",
            '', '| 确定问题归因 | 数量 |', '|---|---:|'] + [
            f"| {n['origin_labels'][key]} | {number} |" for key, number in n['origin_confirmed'].items()] + [
            '', '前三项互斥，与归因未知合计等于确定问题总数。旧代码 × 新配置按已核证并标记的子类统计；其它迁移计入新增 / 遗漏。本次新增Bug总数仍包含旧代码 × 新配置。',
            '', '| 等级 | 确定问题数 |', '|---|---:|'] + [
            f"| {p} {label} | {n['severity_confirmed'][p]} |" for p, label in SEVERITIES.items()] + [
            '', n['policy'], '', f"主问题记录 {n['main_total']} 项；另有审计记录 {n['archive_total']} 项。待确认等级仅为暂定，不计入上表。",
            '', '## 严重程度分类标准', '', '| 等级 | 判定规则 | 边界 |', '|---|---|---|'] + [
            '| ' + ' | '.join(row) + ' |' for row in severity_rows()] + [
            '', '严重度、确定性与归因分别判断；按已证最窄影响分级。流程被其他问题阻断或尚未证实时，保留局部断言与流程状态，不继承阻断者等级。', '']

def validate(doc):
    errors=[]
    for key in ('title','mode','target','baseline','scope','limitations','sources','coverage','findings','skill_version','timings','high_severity_review','review_state','handoffs','classification_schema'):
        if key not in doc: errors.append('missing '+key)
    if errors: return errors
    if doc['mode'] != 'independent': errors.append('mode must be independent; only independent discovery is supported')
    if doc['classification_schema'] != 'local-flow-v1': errors.append('classification_schema must be local-flow-v1; use the frozen renderer for earlier schemas')
    if not isinstance(doc['findings'],list) or not isinstance(doc['sources'],list): return ['sources/findings must be arrays']
    if doc['review_state'] not in ('completed', 'incomplete'):
        errors.append('review_state must be completed/incomplete')
    handoffs=doc['handoffs']
    if not isinstance(handoffs,list):
        errors.append('handoffs must be an array')
        handoffs=[]
    handoff_ids=set()
    for h in handoffs:
        if not isinstance(h,dict):
            errors.append('handoff must be an object');continue
        label=str(h.get('id','?'))
        for key in ('id','from','to','question','disposition'):
            if not isinstance(h.get(key),str) or not h[key].strip():
                errors.append('handoff '+label+' empty '+key)
        if label in handoff_ids:errors.append('duplicate handoff '+label)
        handoff_ids.add(label)
        state=h.get('status')
        if state not in ('open','closed','blocked','out_of_scope'):
            errors.append('handoff '+label+' invalid status')
        if state=='open' and doc['review_state']=='completed':
            errors.append('completed review contains open handoff '+label)
        if not isinstance(h.get('evidence_refs'),list):
            errors.append('handoff '+label+' evidence_refs must be an array')
        else:
            if any(not isinstance(ref,str) or not ref.strip() for ref in h['evidence_refs']):
                errors.append('handoff '+label+' evidence_refs needs non-empty strings')
            if state in ('closed','out_of_scope') and not h['evidence_refs']:
                errors.append('handoff '+label+' needs closure evidence')
        if state=='blocked':
            for key in ('missing_source','why_existing_sources_insufficient'):
                if not isinstance(h.get(key),str) or not h[key].strip():
                    errors.append('blocked handoff '+label+' empty '+key)
    source_ids=[s.get('id') for s in doc['sources']]
    if len(source_ids)!=len(set(source_ids)): errors.append('duplicate source ids')
    sources={s.get('id'):s for s in doc['sources']}
    for s in doc['sources']:
        for k in ('id','kind','location','version','allowed','limitations','content_hash','captured_at','allowed_uses'):
            if k not in s: errors.append('source '+str(s.get('id'))+' missing '+k)
        if type(s.get('allowed')) is not bool: errors.append('source allowed must be boolean')
    for c in doc['coverage']:
        if not isinstance(c,dict): errors.append('coverage entries must be objects');continue
        if not isinstance(c.get('module'),str): errors.append('coverage module must be a string')
        for k in ('files','paths_checked','gaps'):
            if not isinstance(c.get(k),list): errors.append('coverage '+k+' must be an array')
        for k in ('module','files','paths_checked','gaps'):
            if k not in c: errors.append('coverage missing '+k)
    ids=set()
    required=('id','title','status','origin','severity','severity_basis','trigger','actual','expected','impact','reachability','counterevidence','evidence_level','scope','limitations','evidence','claim_scope','local_input_basis','flow_reachability')
    for f in doc['findings']:
        label=str(f.get('id','?'))
        for k in required:
            if k not in f: errors.append(label+' missing '+k)
        if label in ids: errors.append('duplicate finding '+label)
        ids.add(label)
        if f.get('status') not in STATUSES: errors.append(label+' invalid status')
        if f.get('origin') not in ORIGINS: errors.append(label+' invalid origin')
        if 'origin_subtype' in f:
            if f['origin_subtype'] != 'legacy_code_new_config' or f.get('origin') != 'migration_gap':
                errors.append(label+' origin_subtype must be legacy_code_new_config with migration_gap origin')
        if f.get('severity') not in SEVERITIES: errors.append(label+' severity must be P0/P1/P2/P3/P4')
        if f.get('claim_scope') not in CLAIM_SCOPES: errors.append(label+' invalid claim_scope')
        local=f.get('local_input_basis')
        if not isinstance(local,dict): errors.append(label+' local_input_basis must be an object')
        else:
            if not isinstance(local.get('description'),str) or not local['description'].strip(): errors.append(label+' local_input_basis needs description')
            refs=local.get('evidence_refs')
            if not isinstance(refs,list) or any(not isinstance(ref,str) or not ref.strip() for ref in refs): errors.append(label+' local_input_basis evidence_refs must be strings')
            if f.get('status')=='confirmed' and f.get('claim_scope')=='local_contract' and not refs: errors.append(label+' confirmed local claim needs legal-input evidence')
        flow=f.get('flow_reachability')
        if not isinstance(flow,dict): errors.append(label+' flow_reachability must be an object')
        else:
            state=flow.get('state')
            if state not in FLOW_STATES: errors.append(label+' invalid flow_reachability state')
            if not isinstance(flow.get('basis'),str) or not flow['basis'].strip(): errors.append(label+' flow_reachability needs basis')
            for key in ('blocked_by','evidence_refs'):
                refs=flow.get(key)
                if not isinstance(refs,list) or any(not isinstance(ref,str) or not ref.strip() for ref in refs): errors.append(label+' flow_reachability '+key+' must be strings')
            if state=='blocked_by_confirmed_issue' and not flow.get('blocked_by'): errors.append(label+' blocked flow needs another confirmed issue')
            if state!='blocked_by_confirmed_issue' and flow.get('blocked_by'): errors.append(label+' only blocked flow may name blocked_by findings')
            if state in ('reachable','blocked_by_confirmed_issue','inactive_config') and not flow.get('evidence_refs'): errors.append(label+' known flow state needs evidence')
            if f.get('status')=='confirmed' and f.get('claim_scope')=='user_flow' and state!='reachable': errors.append(label+' confirmed user_flow needs proved reachability')
            if f.get('status')=='confirmed' and state=='inactive_config': errors.append(label+' inactive configuration cannot count as a confirmed current Bug')
            if f.get('status')=='inactive_config' and state!='inactive_config': errors.append(label+' inactive_config status needs matching flow state')
        basis=f.get('severity_basis')
        if not isinstance(basis,dict): errors.append(label+' severity_basis must be an object')
        else:
            for key in ('consequence','affected_scope','trigger_basis','recovery','rationale'):
                if not isinstance(basis.get(key),str) or not basis[key].strip(): errors.append(label+' empty severity_basis '+key)
            if not isinstance(basis.get('evidence_refs'),list) or not basis['evidence_refs']: errors.append(label+' severity_basis needs evidence_refs')
        if not f.get('evidence'): errors.append(label+' no evidence')
        for e in f.get('evidence',[]):
            for k in ('source_id','location','locator','quote','supports','role'):
                if not e.get(k): errors.append(label+' empty evidence '+k)
            s=sources.get(e.get('source_id'))
            if not s: errors.append(label+' unknown source '+str(e.get('source_id')))
            elif not s.get('allowed'): errors.append(label+' relies on excluded source')
        if f.get('status')=='confirmed':
            roles={e.get('role') for e in f.get('evidence',[])}
            if 'implementation' not in roles or not roles.intersection({'norm','invariant'}): errors.append(label+' confirmed without implementation and norm/invariant roles')
            for k in ('trigger','reachability','counterevidence','expected','actual'):
                if not f.get(k): errors.append(label+' confirmed without '+k)
            if len(f.get('evidence',[]))<2: errors.append(label+' confirmed needs implementation and norm/invariant evidence')
    by_id={f.get('id'):f for f in doc['findings']}
    for f in doc['findings']:
        flow=f.get('flow_reachability',{})
        if isinstance(flow,dict) and flow.get('state')=='blocked_by_confirmed_issue' and isinstance(flow.get('blocked_by'),list):
            for blocker in flow['blocked_by']:
                if not isinstance(blocker,str) or blocker==f.get('id') or by_id.get(blocker,{}).get('status')!='confirmed': errors.append(str(f.get('id'))+' blocker must name another confirmed finding')
    return errors

FIXED_FIELDS={'id','title','status','origin','severity','trigger','actual','expected','impact','reachability','counterevidence','evidence_level','scope','limitations','evidence'}

def safe_url(url):
    return isinstance(url,str) and bool(url) and not url.startswith('//') and (':' not in url or url.startswith(('https://','http://')))

def escaped(x):
    if isinstance(x,(dict,list)): x=json.dumps(x,ensure_ascii=False,indent=2)
    return html.escape(str(x))

def lines(x):
    if isinstance(x,list): return '\n'.join('- '+str(v) for v in x)
    return str(x)

def field_html(value):
    if isinstance(value, list):
        return '<ul class="field-list">' + ''.join('<li>' + field_html(item) + '</li>' for item in value) + '</ul>'
    text = json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, dict) else str(value)
    paragraphs = [part for part in text.splitlines() if part.strip()]
    if len(text) > 80:
        paragraphs = [clause for part in paragraphs for clause in re.split(r'(?<=[。；])', part) if clause.strip()]
    return ''.join('<p class="field-paragraph">' + escaped(part) + '</p>' for part in paragraphs)

def classification_counts(doc):
    confirmed=[f for f in doc['findings'] if display_bucket(f) in SEVERITIES]
    scopes=collections.Counter(f['claim_scope'] for f in confirmed)
    flows=collections.Counter(f['flow_reachability']['state'] for f in confirmed)
    return {'confirmed_total':len(confirmed),'new_bug_total':sum(f['origin'] in ('new_implementation','new_requirement','migration_gap') for f in confirmed),'historical':sum(f['origin']=='historical' for f in confirmed),'origin_unknown':sum(f['origin']=='unknown' for f in confirmed),'local_contract':scopes['local_contract'],'user_flow':scopes['user_flow'],'blocked_by_confirmed_issue':flows['blocked_by_confirmed_issue'],'unproved':flows['unproved'],'reachable':flows['reachable']}

def classification_summary(doc):
    n=classification_counts(doc)
    return f"确定断言合计 {n['confirmed_total']} = 局部合同 {n['local_contract']} + 用户流程 {n['user_flow']}；本次新增Bug {n['new_bug_total']}，历史 {n['historical']}，归因未知 {n['origin_unknown']}；其中被已确认问题阻断 {n['blocked_by_confirmed_issue']}，流程可达性未证 {n['unproved']}。后两项是子计数。"

def ordered_findings(doc):
    order = {p: i for i, p in enumerate(SEVERITIES)}
    order.update(pending=5, archive=6)
    return sorted(doc['findings'], key=lambda f: order[display_bucket(f)])

DEFAULT_DISCLAIMER = {
    'summary': '本报告基于列明的固定版本与允许输入，供开发排查和风险评估参考，不构成无缺陷或上线安全保证。',
    'details': [
        '适用边界：结论仅适用于报告列明的基线、目标提交及已冻结的允许来源；不自动适用于其他版本、配置或运行环境。',
        '验证边界：审查方法与已完成验证以报告记录为准；未明确记录完成的运行复现、真实服务集成及完整验收，不视为已完成。静态推导不等同于线上已发生。',
        '判定口径：确定问题仅表示所列断言范围内证据闭合，局部确定性与完整流程可达性分别标注；待确认项不计入确定问题数量。P0～P4反映已证后果与影响边界，不代表实际发生频率。',
        '覆盖边界：未发现问题不代表不存在问题。未核证条件、覆盖缺口与输入限制以各项证据和覆盖记录为准；免责声明不替代逐项举证或归因核证。',
        '使用建议：修复优先级和发布决定应结合实际复现、回归测试、集成验证与业务验收综合判断。'
    ]
}

def disclaimer_html(doc):
    value = doc.get('disclaimer', DEFAULT_DISCLAIMER)
    return '<aside class="disclaimer" id="disclaimer" aria-label="免责声明"><strong>免责声明</strong><div class="disclaimer-summary">' + field_html(value['summary']) + '</div><details><summary>展开适用边界与使用说明</summary>' + field_html(value['details']) + '</details></aside>'

def disclaimer_markdown(doc):
    value = doc.get('disclaimer', DEFAULT_DISCLAIMER)
    return ['## 免责声明', '', value['summary'], '', lines(value['details']), '']

def markdown(doc):
    out=['# '+doc['title'],'',f"目标：`{doc['target']}`；基线：`{doc['baseline']}`。",'',str(doc['scope']),''] + disclaimer_markdown(doc) + presentation_markdown(doc) + [classification_summary(doc),'','## 限制','',lines(doc['limitations']),'','## 发现','']
    group = None
    for f in ordered_findings(doc):
        bucket = display_bucket(f)
        current = '待确认' if bucket == 'pending' else '审计记录（不计入问题总数）' if bucket == 'archive' else '确定问题'
        if current != group:
            out += ['## ' + current, '']
            group = current
        out += ['### '+f['id']+' '+f['title'],'',f"判定：{STATUSES[f['status']]}；归因：{ORIGINS[f['origin']]}；等级：{'暂定 ' if bucket == 'pending' else '记录等级（不计入统计） ' if bucket == 'archive' else ''}{f['severity']}。",'']
        out += [f"断言范围：{CLAIM_SCOPES[f['claim_scope']]}；流程：{FLOW_STATES[f['flow_reachability']['state']]}。",'', '**局部输入依据**：'+f['local_input_basis']['description'],'','**流程依据**：'+f['flow_reachability']['basis'],'']
        for k,label in [('trigger','触发'),('actual','实际行为'),('expected','预期与规则'),('impact','已证影响与限制'),('reachability','可达性'),('counterevidence','反证检查'),('evidence_level','证明方式'),('scope','来源边界'),('limitations','限制')]:
            out += [f'**{label}**：{lines(f[k])}','']
        extras={k:v for k,v in f.items() if k not in FIXED_FIELDS}
        if extras: out += ['**附加判定信息**','',json.dumps(extras,ensure_ascii=False,indent=2),'']
        for e in f['evidence']:
            if safe_url(e.get('local_copy')):out += ['[查看固定版本完整文件]('+e['local_copy']+')','']
            out += [f"- [{e['source_id']}] {e['location']} · {e['locator']}：{e['supports']}",'','```text',str(e['quote']),'```','']
    out += ['## 来源','',json.dumps(doc['sources'],ensure_ascii=False,indent=2),'','## 覆盖与缺口','',json.dumps(doc['coverage'],ensure_ascii=False,indent=2)]
    if doc.get('comparison'):out += ['','## 对比说明','',json.dumps(doc['comparison'],ensure_ascii=False,indent=2)]
    for key in ('excluded_contacts','probes','review_history','attachments'):
        if doc.get(key): out += ['', '## '+key, '', json.dumps(doc[key],ensure_ascii=False,indent=2)]
    top_known={'disclaimer','title','mode','target','baseline','scope','limitations','sources','coverage','findings','comparison','excluded_contacts','probes','review_history','attachments'}
    other={k:v for k,v in doc.items() if k not in top_known}
    if other: out += ['', '## 完整补充账本与元数据', '', json.dumps(other,ensure_ascii=False,indent=2)]
    return '\n'.join(out)+'\n'

CSS='''*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:100px}body{margin:0;background:#f5f7fa;color:#1f2937;font:16px/1.75 system-ui,-apple-system,"PingFang SC",sans-serif}main{max-width:1280px;margin:auto;padding:30px 28px 64px}h1{font-size:28px;line-height:1.35;letter-spacing:-.4px;margin:8px 0 10px}h2{font-size:20px;margin:26px 0 12px}h3{font-size:17px;line-height:1.5;margin:0;font-weight:650}.eyebrow{font-size:14px;letter-spacing:2px;color:#475569}.muted{color:#475569}.report-links{font-size:14px;margin:0 0 22px}.report-links a{text-decoration:none}.panel,article{background:#fff;border:1px solid #e0e6ee;border-radius:12px;padding:18px 22px;margin:12px 0;box-shadow:0 2px 6px #24364c03}a{color:#2563a0;text-underline-offset:3px}details{margin:10px 0}summary{cursor:pointer;overflow-wrap:anywhere;color:#345777;font-size:14px;font-weight:600}summary::marker{color:#8b9db3}summary span{float:right;font-size:14px;font-weight:400;color:#475569}details[open]>summary{margin-bottom:16px}.scope-panel,.standards-panel{padding:12px 18px}.scope-panel p,.classification-note p{max-width:100ch}.scope-panel .break{font:14px/1.8 ui-monospace,monospace;margin-top:14px}.classification-note{margin:12px 2px 20px}.classification-note summary{font-weight:400;font-size:14px}.overview{display:grid;grid-template-columns:1fr 2.4fr;gap:14px;margin:18px 0 12px}.metrics{display:grid;gap:10px}.totals{grid-template-columns:repeat(2,minmax(0,1fr))}.severity-metrics{grid-template-columns:repeat(5,minmax(0,1fr))}button.metric{font:inherit;text-align:left;min-height:92px;padding:12px 16px;background:#fff;border:1px solid #dce5f0;border-radius:10px;cursor:pointer;color:#42536a;transition:border-color .15s,box-shadow .15s}button.metric b{display:block;font-variant-numeric:tabular-nums;font-size:28px;line-height:1.2;margin-bottom:6px;font-weight:650;color:#294a70}button.metric.confirmed{background:#e9f1fb;border-color:#d9e6f5;color:#315b8c}button.metric.pending{background:#fff5e4;border-color:#f0e3cc;color:#8b6b30}button.metric.pending b{color:#8a6221}button.metric.P0 b{color:#b13643}button.metric.P1 b{color:#b75b28}button.metric.P2 b{color:#997326}button.metric.P3 b{color:#3168a0}button.metric.P4 b{color:#6c7b8f}button.metric:hover,button.metric[aria-pressed=true]{border-color:#497eb3;box-shadow:0 0 0 2px #497eb314}button.metric:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid #497eb3;outline-offset:4px}.toolbar{position:sticky;top:0;z-index:2;background:#f5f7faf2;backdrop-filter:blur(10px);padding:12px 0;display:flex;gap:10px;border-bottom:1px solid #e0e6ee}input,select{font:inherit;padding:9px 12px;border:1px solid #d2dce8;border-radius:8px;background:white;min-width:0;max-width:100%}input{flex:1}select{max-width:250px}.toolbar+p{font-size:14px;margin:8px 0}.count{font-size:14px;color:#475569;margin:8px 0 14px}.finding-card{padding:18px 22px;border-left:3px solid #91a7bf;margin:0 0 14px}.finding-card[data-bucket=P2]{border-left-color:#c39b47}.finding-card[data-bucket=P3]{border-left-color:#6993bc}.finding-card[data-bucket=pending]{border-left-color:#d3ae68}.finding-heading{display:flex;gap:12px;align-items:baseline}.finding-id{color:#475569;font:14px/1.5 ui-monospace,monospace;white-space:nowrap;min-width:62px}.finding-badges{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 12px}.badge{display:inline-block;padding:2px 7px;border-radius:5px;background:#f0f3f7;color:#42536a;font-size:14px;line-height:1.7}.badge.grade{font-weight:650;color:#345a85;background:#eaf0f8}.badge.confirmed{background:#eaf6ee;color:#36734f}.badge.conditional,.badge.requirement_unverified,.badge.unresolved{background:#fff2dc;color:#8b6b30}.badge.refuted{background:#f0ecf9;color:#75608f}.row{display:grid;grid-template-columns:92px minmax(0,1fr);gap:14px;margin:10px 0}.row strong{font-size:14px;font-weight:500;color:#475569}.row>div{overflow-wrap:anywhere;max-width:108ch}.finding-preview .row{margin:7px 0}.finding-preview .row:first-child{color:#536479}.finding-details{border-top:1px solid #edf0f4;margin:14px 0 0;padding-top:10px}.finding-details>summary{font-size:14px;font-weight:500}.finding-details[open]{padding-top:12px}.finding-details .row{margin:14px 0}.meta-panel>summary{font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;border:1px solid #e8edf3;padding:14px;border-radius:7px;font:14px/1.7 ui-monospace,monospace;max-height:420px;overflow:auto}code,.break{overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #e6ebf1;overflow-wrap:anywhere}th{font-weight:600;color:#52657e;background:#f7f9fb}.tablewrap{overflow:auto;margin-top:12px}.standards-panel td:first-child{white-space:nowrap}.standards-panel th:nth-child(2){width:55%}#sources table{min-width:780px}#audit-records>.finding-card{box-shadow:none;margin-top:16px}[hidden]{display:none!important}@media(max-width:1000px){.overview{grid-template-columns:1fr}.metric{min-height:78px!important}.totals button.metric b{display:inline-block;margin:0 12px 0 0;vertical-align:middle}}@media(max-width:600px){main{padding:22px 14px 44px}h1{font-size:23px}h3{font-size:16px}.panel,.finding-card{padding:14px 16px}.overview{gap:10px;margin-top:14px}.metrics{gap:7px}.severity-metrics{grid-template-columns:repeat(3,minmax(0,1fr))}button.metric{padding:10px 12px}button.metric b{font-size:24px}.toolbar{flex-wrap:wrap}.toolbar input{flex-basis:100%}.toolbar select{flex:1;max-width:none}.finding-heading{display:block}.finding-id{display:block;margin-bottom:5px}.row{grid-template-columns:1fr;gap:2px}.finding-preview .row{margin:10px 0}.finding-badges{gap:5px}.finding-details>summary span{float:none;margin-left:8px}.report-links{line-height:2}.scope-panel>summary span{display:none}}@media print{body{background:#fff}main{max-width:none;padding:0}.toolbar,.report-links{display:none}.panel,article{box-shadow:none;break-inside:avoid}.overview{grid-template-columns:1fr 2.4fr}.metrics{break-inside:avoid}}'''
CSS += '''button.metric.zero b{color:#596b80}.field-list{margin:0;padding-left:18px}.field-list li+li{margin-top:6px}'''
CSS += '''.input-panel>summary{font-size:14px}.input-panel h3{font-size:14px;margin:22px 0 8px}.input-panel .input-repo{display:grid;grid-template-columns:80px minmax(0,1fr);gap:12px;padding:10px 0;border-bottom:1px solid #edf0f4}.input-repo strong{font-size:14px;color:#475569}.input-repo code{font-size:14px;overflow-wrap:anywhere}.input-table{min-width:740px}.input-table th:first-child{width:25%}.input-table .input-path{font-size:14px;color:#475569;min-width:260px}.input-table td:nth-child(3){min-width:160px}.input-table td:nth-child(4){white-space:nowrap}@media(max-width:800px){.input-panel>summary span{float:none;display:block;margin:5px 0 0 16px}.input-panel .input-repo{grid-template-columns:1fr;gap:3px}}'''
CSS += '''body{overflow-wrap:anywhere}main,.panel,.finding-card,.row,.row>div,.finding-heading h3,.input-repo>div{min-width:0;max-width:100%}.finding-heading h3{overflow-wrap:anywhere;word-break:break-word}.row>div{max-width:76ch;white-space:normal;word-break:break-word;line-height:1.85}.field-paragraph{margin:0}.field-paragraph+.field-paragraph{margin-top:8px}.field-list li .field-paragraph+.field-paragraph{margin-top:5px}.input-panel>summary span{float:none;display:block;margin:5px 0 0 16px}.scope-panel .break,.input-repo code,code{white-space:normal;overflow-wrap:anywhere;word-break:break-word}pre{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;min-width:0;max-width:100%;width:100%}table{table-layout:fixed}th,td{min-width:0;max-width:100%;white-space:normal;overflow-wrap:anywhere;word-break:break-word}.input-table,#sources table{min-width:0;width:100%}.input-table .input-path,.input-table td:nth-child(3){min-width:0}.input-table td:nth-child(4),.standards-panel td:first-child{white-space:normal}.input-table th:first-child{width:23%}.input-table th:nth-child(2){width:43%}.input-table th:nth-child(3){width:22%}.input-table th:nth-child(4){width:12%}.tablewrap{max-width:100%;overflow-x:auto}@media(max-width:760px){.input-table,.input-table tbody,.input-table tr,.input-table td,#sources table,#sources tbody,#sources tr,#sources td{display:block;width:100%;min-width:0}.input-table thead,#sources thead{display:none}.input-table tr,#sources tr{padding:10px 0;border-bottom:1px solid #dce5ef}.input-table td,#sources td{border:0;padding:5px 0;white-space:normal}.input-table td::before,#sources td::before{display:block;font-size:14px;font-weight:600;color:#475569;margin-bottom:2px}.input-table td:nth-child(1)::before{content:"文件"}.input-table td:nth-child(2)::before{content:"原始路径"}.input-table td:nth-child(3)::before{content:"版本 / 修订"}.input-table td:nth-child(4)::before{content:"登记状态"}#sources td:nth-child(1)::before{content:"来源 ID"}#sources td:nth-child(2)::before{content:"类别"}#sources td:nth-child(3)::before{content:"位置"}#sources td:nth-child(4)::before{content:"版本"}#sources td:nth-child(5)::before{content:"允许使用"}#sources td:nth-child(6)::before{content:"限制"}.row>div{max-width:100%}}'''
CSS += '''.disclaimer{margin:16px 0;padding:14px 18px;border:1px solid #dce5ef;border-left:3px solid #829bb7;border-radius:9px;background:#eef3f8;color:#52657b;font-size:14px;line-height:1.85}.disclaimer>strong{display:block;color:#345777;font-size:14px;margin-bottom:5px}.disclaimer-summary{max-width:86ch}.disclaimer details{margin:8px 0 0}.disclaimer summary{font-size:14px;font-weight:400}.disclaimer .field-list{max-width:100ch;margin-top:10px}.disclaimer li+li{margin-top:10px}@media print{.disclaimer{break-inside:avoid}}'''
DELIVERY_CSS=""".version-summary{display:grid;gap:10px;margin:14px 0}.version-item{display:grid;grid-template-columns:90px minmax(160px,220px) minmax(0,1fr);gap:10px;align-items:start;padding:12px 14px;background:#eaf0f7;border:1px solid #d4deea;border-radius:7px;font-size:15px}.version-item strong{color:#475569}.version-item code{font-size:14px}.top-disclaimer{margin:8px 0 16px;padding:10px 14px;border-left:3px solid #829bb7;background:#eef3f8;color:#52657b;border-radius:6px;font-size:14px}.delivery{display:block;margin:18px 0}.delivery h2{margin:3px 0}.delivery-notice{grid-column:1/-1;padding:11px 14px;background:#fff4dd;border:1px solid #efd9a8;border-left:4px solid #c79631;border-radius:7px;color:#674d1d;font-weight:600}.delivery-ready{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:0;color:#5d6f84}.download-button{display:inline-block;padding:9px 15px;border-radius:7px;background:#315f91;color:white;text-decoration:none;font-weight:600}.download-button:hover{background:#244c77}.delivery code{font-size:14px;overflow-wrap:anywhere}#finding-overview{margin-bottom:14px}#finding-overview a{text-decoration:none}#finding-overview th:nth-child(1){width:7%}#finding-overview th:nth-child(2){width:10%}#finding-overview th:nth-child(3){width:35%}#finding-overview th:nth-child(4){width:14%}#finding-overview th:nth-child(5){width:16%}#finding-overview th:nth-child(6){width:18%}@media(max-width:760px){.delivery{grid-template-columns:1fr}.delivery-notice{grid-column:1}.delivery-ready{align-items:flex-start;flex-direction:column;gap:8px}#finding-overview,#finding-overview tbody,#finding-overview tr,#finding-overview td{display:block;width:100%;min-width:0}#finding-overview thead{display:none}#finding-overview tr{padding:10px 0;border-bottom:1px solid #dce5ef}#finding-overview td{border:0;padding:4px 0;white-space:normal}#finding-overview td::before{display:block;margin-bottom:2px;font-size:14px;font-weight:600;color:#475569}#finding-overview td:nth-child(1)::before{content:"ID"}#finding-overview td:nth-child(2)::before{content:"等级"}#finding-overview td:nth-child(3)::before{content:"标题"}#finding-overview td:nth-child(4)::before{content:"模块"}#finding-overview td:nth-child(5)::before{content:"归因"}#finding-overview td:nth-child(6)::before{content:"证明方式"}#finding-overview td:first-child{white-space:normal}}"""


READABILITY_CSS=""".delivery h2{margin:4px 0 12px}.delivery-notice{margin:10px 0 16px}.delivery-ready{display:flex;align-items:flex-start;gap:22px;flex-wrap:wrap}.delivery-meta{flex:1 1 520px;min-width:0;margin:0}.delivery-meta>div{display:grid;grid-template-columns:90px minmax(0,1fr);gap:12px;margin:0 0 8px}.delivery-meta dt{font-weight:600;color:#334155}.delivery-meta dd{margin:0;min-width:0;color:#1e293b;overflow-wrap:anywhere}.delivery-meta code{font-size:14px;color:#1e293b;line-height:1.8;word-break:break-all}.download-button{flex:none;font-size:16px}.version-branch{font-weight:600;color:#1e293b}.version-sha{font-size:14px!important;color:#1e293b}.finding-badges .badge{font-size:14px}.delivery-usage{font-size:14px!important;color:#475569!important;margin-top:14px!important}.count{color:#475569}.page-nav a{font-size:14px!important}.eyebrow{color:#475569}@media(max-width:760px){.version-item{grid-template-columns:90px minmax(0,1fr)}.version-sha{grid-column:1/-1}.delivery-meta{flex-basis:100%;width:100%}.delivery-meta>div{grid-template-columns:1fr;gap:2px}.delivery-ready{gap:14px}.delivery-meta code{word-break:break-all}}"""

JS='''const cards=[...document.querySelectorAll('#main-findings > article')];
const rows=[...document.querySelectorAll('#finding-overview tbody tr')];
function filter(){
 const q=document.querySelector('#q').value.toLowerCase(),v=document.querySelector('#severity').value;
 const o=document.querySelector('#origin').value,m=document.querySelector('#module').value;
 let n=0;
 cards.forEach(c=>{
  const match=(v==='all'||(v==='confirmed'?c.dataset.bucket!=='pending':v==='pending'?c.dataset.bucket==='pending':c.dataset.bucket===v))
   &&(!o||(o.startsWith('group:')?c.dataset.originGroup===o.slice(6):c.dataset.origin===o))&&(!m||c.dataset.module===m)&&c.textContent.toLowerCase().includes(q);
  c.hidden=!match;if(match)n++;
  const row=rows.find(r=>r.dataset.findingId===c.id);if(row)row.hidden=!match;
 });
 document.querySelector('#count').textContent=`显示 ${n} / ${cards.length} 项主问题记录`;
 document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===v)));
 document.querySelectorAll('button[data-origin-filter]').forEach(b=>b.setAttribute('aria-pressed',String(v==='confirmed'&&b.dataset.originFilter===o)));
}
['q','severity','origin','module'].forEach(id=>document.getElementById(id).addEventListener(id==='q'?'input':'change',filter));
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{document.getElementById('severity').value=b.dataset.view;filter();}));
document.querySelectorAll('button[data-origin-filter]').forEach(b=>b.addEventListener('click',()=>{document.getElementById('severity').value='confirmed';document.getElementById('origin').value=b.dataset.originFilter;filter();}));
filter();'''


def extra_html(title, value):
    if isinstance(value,dict):
        parts=[]
        for k,v in value.items():
            if isinstance(v,(dict,list)):parts.append('<details><summary>'+escaped(k)+'</summary><pre>'+escaped(v)+'</pre></details>')
            else:parts.append('<div class="row"><strong>'+escaped(k)+'</strong><div>'+field_html(v)+'</div></div>')
        body=''.join(parts)
    else:body='<pre>'+escaped(value)+'</pre>'
    return '<details class="panel meta-panel"><summary>'+escaped(title)+'</summary>'+body+'</details>'

def input_html(doc):
    sources=doc['sources']
    git=[s for s in sources if s['kind']=='git']
    files=[s for s in sources if s['kind']!='git']
    repos=len({s['location'] for s in git})
    labels={'requirement':'需求文档','configuration':'配表','client_design':'客户端设计','server_design':'服务端设计','resource':'资源'}
    groups={}
    for source in files:
        groups.setdefault(source['kind'],[]).append(source)
    counts=' · '.join([f'{repos} 个仓库 / {len(git)} 个固定快照'] + [f'{labels.get(k,k)} {len(v)} 份' for k,v in groups.items()])
    body='<p class="muted">列出原独立审查的完整登记输入。文件已提供并冻结不等于每个字段均已核证，实际覆盖见覆盖账本。</p>'
    if git:
        body+='<h3>客户端仓库与版本</h3>'
        for source in sorted(git,key=lambda s: {'BASELINE':0,'BASE':0,'TARGET':1}.get(s['id'],2)):
            label={'BASELINE':'基线提交','BASE':'基线提交','TARGET':'目标提交'}.get(source['id'],source['id'])
            ref='<code>'+escaped(source['requested_ref'])+'</code><br>' if source.get('requested_ref') else ''
            body+='<div class="input-repo" data-source-id="'+escaped(source['id'])+'"><strong>'+escaped(label)+'</strong><div><code>'+escaped(source['location'])+'</code><br>'+ref+'<code>'+escaped(source['version'])+'</code></div></div>'
    for kind,items in groups.items():
        body+='<h3>'+escaped(labels.get(kind,kind))+'（'+str(len(items))+' 份）</h3><div class="tablewrap"><table class="input-table"><thead><tr><th>文件</th><th>原始路径</th><th>版本 / 修订</th><th>登记状态</th></tr></thead><tbody>'
        for source in items:
            name=Path(source['location']).name
            copy=source.get('local_copy')
            title='<a href="'+escaped(copy)+'">'+escaped(name)+'</a>' if safe_url(copy) else escaped(name)
            version=('工作副本 r'+str(source['svn_revision'])+'；最后修改 r'+str(source.get('svn_last_changed','unknown'))) if source.get('svn_revision') else source['version']
            state='已提供 / 已冻结' if source['allowed'] else '接触后排除 / 不作依据'
            body+='<tr data-source-id="'+escaped(source['id'])+'"><td>'+title+'</td><td class="input-path">'+escaped(source['location'])+'</td><td>'+escaped(version)+'</td><td>'+state+'</td></tr>'
        body+='</tbody></table></div>'
    availability=doc.get('input_availability',[])
    if availability:
        body+='<details><summary>资料可用性、未提供及禁止使用项</summary><p class="muted">以下状态描述原独立发现阶段；后续文档自审和展示更新单独留档。</p><div class="tablewrap"><table><thead><tr><th>来源类别</th><th>本轮状态</th><th>用途与限制</th></tr></thead><tbody>'
        for item in availability:
            body+='<tr><td>'+escaped(item.get('kind','未分类'))+'</td><td>'+escaped(item.get('state','未登记'))+'</td><td>'+escaped(item.get('required','未登记'))+'</td></tr>'
        body+='</tbody></table></div></details>'
    return '<details class="panel input-panel" id="complete-inputs"><summary>完整输入列表<span>'+escaped(counts)+'</span></summary>'+body+'<p class="muted">文件哈希、用途限制、采集时间及完整元数据见下方“完整来源登记”；配表与目标发布的映射限制仍保留。</p></details>'

def version_summary(doc):
    def one(role, label):
        commit = str(doc[role])
        explicit = doc.get(role + '_ref')
        refs = [explicit] if isinstance(explicit, str) and explicit.strip() else sorted({
            s['requested_ref'] for s in doc.get('sources', [])
            if s.get('kind') == 'git' and s.get('version') == commit
            and isinstance(s.get('requested_ref'), str) and s['requested_ref'].strip()})
        branch = ' / '.join(refs) if refs else '分支未登记'
        return '<div class="version-item"><strong>' + escaped(label) + '</strong><span class="version-branch">' + escaped(branch) + '</span><code class="version-sha">' + escaped(commit) + '</code></div>'
    return '<div class="version-summary">' + one('target', '目标分支') + one('baseline', '基线分支') + '</div>'

def delivery_html(delivery):
    delivery = delivery if isinstance(delivery, dict) else {}
    notice = delivery.get('notice')
    notice_html = '<div class="delivery-notice">' + escaped(notice) + '</div>' if notice else ''
    profile = delivery.get('profile')
    if profile == 'package':
        body = '<p class="delivery-ready">证据已包含在随包目录，无需另行下载。</p>'
        usage = '<p class="delivery-usage">包含报告、原始输入与核证资料；解压后打开 <code>index.html</code> 阅读。</p>'
    elif profile == 'local':
        url, sha, size, checksum_url = (delivery.get('url'), delivery.get('sha256'),
                                        delivery.get('bytes'), delivery.get('checksum_url'))
        if (safe_url(url) and safe_url(checksum_url) and isinstance(sha, str)
                and re.fullmatch(r'[0-9a-fA-F]{64}', sha)
                and isinstance(size, int) and not isinstance(size, bool) and size >= 0):
            checksum = '<div><dt>校验文件</dt><dd data-delivery-field="checksum"><a href="' + escaped(checksum_url) + '">SHA-256 校验文件</a></dd></div>'
            body = '<div class="delivery-ready"><a class="download-button" href="' + escaped(url) + '" download>下载完整证据包</a><dl class="delivery-meta"><div><dt>文件大小</dt><dd data-delivery-field="size">' + format(size / 1024 ** 2, '.2f') + ' MiB · ' + format(size, ',') + ' bytes</dd></div><div><dt>SHA-256</dt><dd data-delivery-field="sha256"><code>' + escaped(sha) + '</code></dd></div>' + checksum + '</dl></div>'
            usage = '<p class="delivery-usage">包含报告、原始输入与核证资料；解压后打开 <code>index.html</code> 阅读。</p>'
        else:
            body = '<p class="muted">证据包尚未生成或下载校验信息不完整。</p>'
            usage = ''
    else:
        body = '<p class="muted">证据包尚未生成。</p>'
        usage = ''
    return '<section class="delivery panel" id="delivery"><div><span class="eyebrow">EVIDENCE DELIVERY</span><h2>证据包</h2></div>' + notice_html + body + usage + '</section>'

def origin_summary_html(doc):
    counts, labels = origin_counts(doc), origin_summary_labels(doc)
    cards = ''.join('<button type="button" class="origin-metric ' + key +
                    '" data-origin-filter="' + ('historical' if key == 'historical' else 'group:' + key) +
                    '" aria-pressed="false"><b>' + str(counts[key]) + '</b><span>' + escaped(labels[key]) + '</span></button>'
                    for key in ('new_or_omission', 'historical', 'legacy_code_new_config'))
    return '<section id="origin-summary" aria-label="确定问题归因统计"><div class="origin-metrics">' + cards + '</div><p class="muted origin-note">三项互斥；归因未知：' + str(counts['unknown']) + '。四者合计等于确定问题总数，待确认与审计记录不计入。旧代码 × 新配置按已核证标记统计，其它迁移归入新增 / 遗漏；本次新增Bug总数包含旧代码 × 新配置。</p></section>'

CSS += '''.origin-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin:18px 0 8px}.origin-metric{font:inherit;text-align:left;background:#fff;border:1px solid #d6e1e8;border-radius:14px;padding:24px 28px;min-width:0;cursor:pointer;color:#1c303d}.origin-metric b{display:block;font-size:44px;line-height:1.15;margin-bottom:16px}.origin-metric span{font-size:20px;color:#5a6d7b;overflow-wrap:anywhere}.origin-metric.historical b{color:#285a80}.origin-metric.legacy_code_new_config b{color:#91560a}.origin-metric:hover,.origin-metric[aria-pressed=true]{border-color:#497eb3;box-shadow:0 0 0 2px #497eb314}.origin-metric:focus-visible{outline:2px solid #497eb3;outline-offset:4px}.origin-note{font-size:14px;line-height:1.8}@media(max-width:600px){.origin-metrics{grid-template-columns:1fr;gap:10px}.origin-metric{padding:18px 22px}.origin-metric b{font-size:36px;margin-bottom:8px}.origin-metric span{font-size:18px}}'''

def render(doc,basename,delivery=None):
    n = presentation_counts(doc)
    delivery = delivery if isinstance(delivery, dict) else {}
    if not delivery.get('notice'):
        revision = doc.get('presentation_revision', {})
        if isinstance(revision, dict) and revision.get('notice'):
            delivery = dict(delivery, notice=revision['notice'])
    def metric_button(view, number, label):
        zero=' zero' if number == 0 else ''
        return f'<button type="button" class="metric {view}{zero}" data-view="{view}" aria-pressed="false"><b>{number}</b>{escaped(label)}</button>'
    metric = '<div class="metrics totals">' + metric_button('confirmed', n['confirmed_total'], '确定问题') + metric_button('pending', n['pending_total'], '待确认') + '</div>'
    metric += '<div class="metrics severity-metrics">' + ''.join(metric_button(p, n['severity_confirmed'][p], p + ' ' + label) for p, label in SEVERITIES.items()) + '</div>'
    standard = '<details class="panel standards-panel" id="severity-guide"><summary>严重程度分类标准（P0～P4）与统计口径</summary><p>' + escaped(n['policy']) + '</p><p>待确认包括条件待证、需求有效性待核和未决候选。待确认项的等级仅为暂定；已反证、未启用配置及改进建议保留在审计记录中。</p><div class="tablewrap"><table><thead><tr><th>等级</th><th>判定规则</th><th>边界</th></tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + escaped(c) + '</td>' for c in row) + '</tr>' for row in severity_rows()) + '</tbody></table></div><p>严重度、确定性、归因分别判断；按已证最窄影响分级。局部确定性和完整流程可达性仍单列；高等级须闭合严重后果、合法触发、影响范围与恢复限制。</p></details>'
    cards=[]
    audit_cards=[]
    table_rows=[]
    for f in ordered_findings(doc):
        bucket=display_bucket(f)
        grade=('暂定 ' if bucket=='pending' else '记录等级（不计统计） ' if bucket=='archive' else '')+f['severity']
        module = f.get('module') if isinstance(f.get('module'), str) and f.get('module').strip() else '未分类'
        preview=''.join(f'<div class="row"><strong>{label}</strong><div>{field_html(f[k])}</div></div>' for k,label in [('trigger','触发条件'),('impact','影响')])
        rows='<div class="row"><strong>局部输入依据</strong><div>'+field_html(f['local_input_basis']['description'])+'</div></div><div class="row"><strong>流程依据</strong><div>'+field_html(f['flow_reachability']['basis'])+'</div></div>'
        rows+=''.join(f'<div class="row"><strong>{label}</strong><div>{field_html(f[k])}</div></div>' for k,label in [('actual','实际行为'),('expected','预期依据'),('counterevidence','反证检查'),('evidence_level','证明方式'),('scope','来源边界'),('limitations','限制')])
        rows+='<div class="row"><strong>所属模块</strong><div>'+escaped(module)+'</div></div>'
        rows+='<div class="row"><strong>归因</strong><div>'+escaped(ORIGINS[f['origin']])+'</div></div>'
        if f['reachability'] != f['flow_reachability']['basis']:
            rows += '<div class="row"><strong>可达性补充</strong><div>' + field_html(f['reachability']) + '</div></div>'
        extra={k:v for k,v in f.items() if k not in FIXED_FIELDS}
        rows += '<details><summary>附加判定信息</summary><pre>'+escaped(extra)+'</pre></details>' if extra else ''
        evidence=''.join('<details><summary>'+escaped(e['source_id']+' · '+e['location']+' · '+str(e['locator']))+'</summary><p>'+escaped(e['supports'])+'</p>'+ ('<p><a href="'+escaped(e['local_copy'])+'">查看固定版本完整文件</a></p>' if safe_url(e.get('local_copy')) else '') +'<pre>'+escaped(e['quote'])+'</pre></details>' for e in f['evidence'])
        card = f'<article class="finding-card" data-bucket="{bucket}" id="{escaped(f["id"])}" data-finding-id="{escaped(f["id"])}" data-status="{f["status"]}" data-origin="{escaped(f["origin"])}" data-origin-group="{origin_group(f)}" data-severity="{escaped(f["severity"])}" data-module="{escaped(module)}"><div class="finding-heading"><span class="finding-id">{escaped(f["id"])}</span><h3>{escaped(f["title"])}</h3></div><div class="finding-badges"><span class="badge grade">{escaped(grade)}</span><span class="badge {f["status"]}">{STATUSES[f["status"]]}</span><span class="badge">{CLAIM_SCOPES[f["claim_scope"]]}</span><span class="badge">{FLOW_STATES[f["flow_reachability"]["state"]]}</span></div><div class="finding-preview">{preview}</div><details class="finding-details"><summary>展开详细分析、来源与证据 <span>{len(f["evidence"])} 条证据</span></summary>{rows}<details><summary>证据引用（{len(f["evidence"])}）</summary>{evidence}</details></details></article>'
        if bucket == 'archive':
            audit_cards.append(card)
        else:
            cards.append(card)
            proof = f.get('evidence_level', '未记录')
            if isinstance(proof, (dict, list)):
                proof = json.dumps(proof, ensure_ascii=False)
            table_rows.append('<tr data-finding-id="' + escaped(f['id']) + '" data-bucket="' + escaped(bucket) + '" data-status="' + escaped(f['status']) + '" data-origin="' + escaped(f['origin']) + '" data-origin-group="' + origin_group(f) + '" data-severity="' + escaped(f['severity']) + '" data-module="' + escaped(module) + '"><td><a href="#' + escaped(f['id']) + '">' + escaped(f['id']) + '</a></td><td><span class="badge grade">' + escaped(grade) + '</span></td><td><a href="#' + escaped(f['id']) + '">' + escaped(f['title']) + '</a></td><td>' + escaped(module) + '</td><td>' + escaped(ORIGINS[f['origin']]) + '</td><td>' + escaped(proof) + '</td></tr>')
    modules = sorted({f.get('module') if isinstance(f.get('module'), str) and f.get('module').strip() else '未分类' for f in doc['findings'] if display_bucket(f) != 'archive'})
    options=lambda mapping:''.join(f'<option value="{k}">{v}</option>' for k,v in mapping.items())
    module_options=''.join('<option value="'+escaped(m)+'">'+escaped(m)+'</option>' for m in modules)
    source_rows=''.join('<tr>'+''.join('<td>'+field_html(s.get(k,''))+'</td>' for k in ['id','kind','location','version','allowed','limitations'])+'</tr>' for s in doc['sources'])
    cov=''.join('<details><summary>'+escaped(c['module'])+'</summary><pre>'+escaped(c)+'</pre></details>' for c in doc['coverage'])
    comp=extra_html('独立输出与参考的对比',doc['comparison']) if doc.get('comparison') else ''
    extras=''.join(extra_html(label,doc[key]) for key,label in [('excluded_contacts','接触但排除的来源'),('probes','验证记录与限制'),('review_history','审查轮次')] if doc.get(key))
    links=[]
    for a in doc.get('attachments',[]):
        url=a.get('url','')
        if safe_url(url):links.append('<a href="'+escaped(url)+'">'+escaped(a.get('title',url))+'</a>')
    attachments='<p>'+ ' · '.join(links)+'</p>' if links else ''
    top_known={'disclaimer','title','mode','target','baseline','scope','limitations','sources','coverage','findings','comparison','excluded_contacts','probes','review_history','attachments'}
    other={k:v for k,v in doc.items() if k not in top_known}
    extras += extra_html('完整补充账本与元数据',other) if other else ''
    short_disclaimer = doc.get('disclaimer', DEFAULT_DISCLAIMER)['summary']
    revision = doc.get('presentation_revision', {})
    notice = delivery.get('notice') or (revision.get('notice') if isinstance(revision, dict) else None)
    if notice:
        delivery = dict(delivery, notice=notice)
    version = version_summary(doc)
    top_disclaimer = '<aside class="top-disclaimer">' + escaped(short_disclaimer) + '</aside>'
    version_details = '<details class="panel scope-panel" id="review-scope"><summary>审查范围与完整版本信息<span>展开查看完整SHA</span></summary><div class="break"><strong>目标完整 SHA</strong> ' + escaped(doc['target']) + '<br><strong>基线完整 SHA</strong> ' + escaped(doc['baseline']) + '</div><p>' + escaped(doc['scope']) + '</p></details>'
    table = '<div class="tablewrap"><table id="finding-overview"><thead><tr><th>ID</th><th>等级</th><th>标题</th><th>模块</th><th>归因</th><th>证明方式</th></tr></thead><tbody>' + ''.join(table_rows) + '</tbody></table></div>'
    toolbar = '<div class="toolbar"><input id="q" placeholder="搜索问题、触发条件、实际/预期或证据" aria-label="搜索"><select id="severity" aria-label="按确定性或等级筛选"><option value="all">全部问题（' + str(n['main_total']) + '）</option><option value="confirmed">确定问题（' + str(n['confirmed_total']) + '）</option>' + ''.join('<option value="' + p + '">' + p + ' ' + label + '（' + str(n['severity_confirmed'][p]) + '）</option>' for p,label in SEVERITIES.items()) + '<option value="pending">待确认（' + str(n['pending_total']) + '）</option></select><select id="origin" aria-label="按归因筛选"><option value="">全部归因</option>' + options(ORIGINS) + '<optgroup label="首页统计（确定问题）"><option value="group:new_or_omission">新增 / 遗漏</option><option value="group:legacy_code_new_config">旧代码 × 新配置</option></optgroup></select><select id="module" aria-label="按模块筛选"><option value="">全部模块</option>' + module_options + '</select></div><p class="muted">总览表与下方问题卡片同步筛选；点击表格标题或编号可定位到对应卡片。已反证、配置未启用及改进建议单列为审计记录。</p><div class="count" id="count"></div>'
    front_limit = doc['limitations'][0] if isinstance(doc['limitations'], list) and doc['limitations'] else '详细范围限制见报告末尾。'
    front_limit_html = escaped(front_limit) if isinstance(front_limit, str) else field_html(front_limit)
    front_summary = '<section class="front-summary panel" id="overview"><strong>摘要</strong><p><b>' + str(n['confirmed_total']) + '</b> 项确定问题 · <b>' + str(n['pending_total']) + '</b> 项待确认 · <b>' + str(n['archive_total']) + '</b> 项审计记录。</p><p>验证边界：' + front_limit_html + '</p></section>'
    page_nav = '<nav class="page-nav" aria-label="页内导航"><a href="#overview">总览</a><a href="#delivery">证据包</a><a href="#problem-overview">问题总览</a><a href="#finding-details">问题详情</a><a href="#complete-inputs">输入</a><a href="#sources">来源</a><a href="#audit-records">审计</a></nav>'
    bottom = input_html(doc) + '<details class="panel" id="review-limitations"><summary>审查范围与限制（' + str(len(doc['limitations'])) + '项）</summary><div class="muted">' + field_html(doc['limitations']) + '</div></details>' + standard + '<details class="classification-note"><summary>统计范围与流程说明</summary><div class="muted">' + field_html(classification_summary(doc)) + '</div></details>' + comp + attachments + disclaimer_html(doc)
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escaped(doc['title'])+'</title><style>'+CSS+DELIVERY_CSS+READABILITY_CSS+' .page-nav{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 18px}.page-nav a{padding:5px 9px;background:#fff;border:1px solid #dce5ef;border-radius:6px;text-decoration:none;font-size:12px}.front-summary{margin:14px 0}.front-summary strong{color:#345777}.front-summary p{margin:6px 0}.front-summary .field-paragraph{display:inline}.delivery-usage{grid-column:1/-1;margin:0;color:#65748a;font-size:12px}@media(max-width:760px){.page-nav{gap:6px}.page-nav a{padding:5px 7px}}'+'</style><main><div class="eyebrow">VERSION · EVIDENCE · REVIEW</div><h1>'+escaped(doc['title'])+'</h1><p class="muted report-links">固定版本审查 · '+escaped(doc['mode'])+' · <a href="'+escaped(basename)+'.json">JSON</a> · <a href="'+escaped(basename)+'.md">Markdown</a></p>'+top_disclaimer+page_nav+version+version_details+front_summary+origin_summary_html(doc)+'<div class="overview">'+metric+'</div>'+delivery_html(delivery)+'<h2 id="problem-overview">问题总览</h2>'+toolbar+table+'<h2 id="finding-details">问题详情</h2><section id="main-findings">'+''.join(cards)+'</section><details class="panel" id="audit-records"><summary>审计记录（'+str(n['archive_total'])+'项，不计入问题总数）</summary><p>已反证、配置未启用及改进建议。保留证据及排除理由。</p>'+''.join(audit_cards)+'</details>'+bottom+'<details class="panel" id="sources"><summary>数据来源（'+str(len(doc['sources']))+'）</summary><div class="tablewrap"><table><thead><tr><th>ID</th><th>类别</th><th>位置</th><th>版本</th><th>允许</th><th>限制</th></tr></thead><tbody>'+source_rows+'</tbody></table></div></details><details class="panel"><summary>覆盖与缺口（'+str(len(doc['coverage']))+' 个模块记录）</summary>'+cov+'</details>'+extra_html('完整来源登记',doc['sources'])+extras+'</main><script>'+JS+'</script></html>'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path);p.add_argument('--out',type=Path);p.add_argument('--basename',default='review');p.add_argument('--check-only',action='store_true')
    p.add_argument('--delivery',type=Path,help='HTML presentation-only delivery context JSON; not copied into review facts')
    a=p.parse_args();doc=json.loads(a.input.read_text());errors=validate(doc)
    if errors: raise SystemExit('\n'.join(errors))
    if a.check_only:print('Structural checks passed; semantic evidence verification still required.');return
    if not a.out:p.error('--out required unless --check-only')
    if Path(a.basename).name!=a.basename or a.basename in ('.','..'):p.error('basename must be a filename stem')
    delivery=json.loads(a.delivery.read_text()) if a.delivery else None
    doc.setdefault('disclaimer', DEFAULT_DISCLAIMER)
    doc['presentation_summary'] = presentation_counts(doc)
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/(a.basename+'.json')).write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    (a.out/(a.basename+'.md')).write_text(markdown(doc))
    (a.out/'index.html').write_text(render(doc,a.basename,delivery))
    print(json.dumps({'findings':len(doc['findings']),'status_counts':dict(collections.Counter(f['status'] for f in doc['findings'])),'classification_counts':classification_counts(doc),'output':str(a.out)},ensure_ascii=False))

if __name__=='__main__': main()
