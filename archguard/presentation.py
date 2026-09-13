"""固定的人读审计报告；裁决来自 B，事实与用量来自本地记录。"""
import json
import re
import math
from archguard.storage import metadata_path, read_json
from archguard.delivery import audit_packet


def parse_result(text):
    try:
        return json.loads(text)
    except ValueError:
        matches = re.findall(r'```json\s*(.*?)\s*```', text, re.S)
        if len(matches) != 1:
            raise ValueError('报告必须含唯一的机器回收 JSON 附录')
        return json.loads(matches[0])


def estimate(text):
    # 仅预测新增文本载荷，不推算上下文、缓存、费用或账户额度。
    n = len(text)
    return {'characters': n, 'estimated_payload_tokens_low': math.ceil(n/4),
            'estimated_payload_tokens_high': n, 'method': '字符数/4 至字符数，宽区间启发式，非 tokenizer 实测',
            'scope': '仅新增文本；不含 A/B 历史、系统工具描述和模型输出，实际可能超出'}


def cell(value):
    return str(value).replace('|', r'\|').replace('\n', '<br>')


def render(root, report, verdict):
    from archguard.adapters.codex.session_manager import VERDICT_SCHEMA
    from jsonschema import validate
    validate(verdict, VERDICT_SCHEMA)
    if verdict['commit_hash'] != report.commit_hash:
        raise ValueError('报告与裁决提交不匹配')
    files = {f['path']: f for f in report.changed_files}
    if {f['path'] for f in verdict['files']} != set(files):
        raise ValueError('报告缺少逐文件裁决')
    ledger = report.ledger_verification
    graph = report.graph_analysis
    consistency = '一致' if ledger.get('is_consistent') is True else '不一致' if ledger.get('is_consistent') is False else '未知'
    analysis_state = '分析完成' if report.analysis_status == 'complete' else report.analysis_status
    lines = [f'# IDE_Audit 审计报告', '', f'提交：`{report.commit_hash}`', '',
             '## 一、审计一：插件客观检查', '',
             f'- 固定范围：父提交 `{report.base_commit}` → 本提交；{len(files)} 个变更文件。',
             f'- 需求：{len(report.prompts)} 条；封存账本：{len(report.ledger_events)} 条事件。',
             f'- 图谱：新增节点 {len(graph.get("nodes_added", []))}，删除节点 {len(graph.get("nodes_removed", []))}；新增边 {len(graph.get("edges_added", []))}，删除边 {len(graph.get("edges_removed", []))}。物理节点变化不等于业务架构越权。',
             f'- 账本一致性：{consistency}；未申报文件 {len(ledger.get("undeclared_files", []))}，虚报文件 {len(ledger.get("phantom_files", []))}，行范围偏差 {len(ledger.get("line_deviations", []))}。',
             f'- 证据状态：{analysis_state}；诊断 {len(report.diagnostics)} 项。', '',
             '## 二、审计二：B 对照需求与实现', '',
             '| 文件 | 用户需求依据 | 实际修改与判断 | 与需求相关 |', '|---|---|---|---|']
    fact_rows = ['', '| 文件 | 实际增删 | 账本事件 | 行级检查 |', '|---|---|---|---|']
    for path, file in files.items():
        events = [e for e in report.ledger_events if any(f.get('file') == path for f in e.get('scope',{}).get('files_changed', []))]
        deviations = [d for d in ledger.get('line_deviations', []) if d.get('file') == path]
        detail = '；'.join(f'{"新增" if d.get("side") == "new" else "删除"}行未申报：{d.get("undeclared_lines", [])}' for d in deviations) or ('已核对，未发现行范围偏差' if ledger else '未知')
        fact_rows.append('| ' + ' | '.join(cell(v) for v in (path, f'+{file.get("additions",0)} / -{file.get("deletions",0)}', ', '.join(e.get('version','未知') for e in events) or '无文件申报', detail)) + ' |')
    split = lines.index('## 二、审计二：B 对照需求与实现')
    lines[split:split] = fact_rows + ['']
    for f in verdict['files']:
        lines.append('| ' + ' | '.join(cell(v) for v in (f['path'], f['requirement_evidence'], f['reason'], '是' if f['related'] else '否')) + ' |')
    lines += ['', '**架构合理性**：' + verdict['architecture_review'], '',
              '**记账完整性**：' + verdict['ledger_review'], '',
              '## 三、最终审计结论', '', '**' + verdict['verdict'] + '**：' + verdict['reason'], '',
              '裁决来自 B；流程记账缺项与业务代码越权分别理解。未获证据支持的环节不宣称通过。', '',
              '**整改与复核**：' + ('按以上具体差异完善后续 A 申报，保留本提交原始封存证据；不得回填篡改以制造通过。' if verdict['verdict'] == '不合理' else '本次范围内无需因本裁决整改；证据覆盖限制仍保留。'), '',
              '## 四、Token 预测与实际用量', '',
              '| 环节 | 预测口径 | 本次实际 token | 窗口累计 token |', '|---|---|---|---|']
    phases = [('接入/增量检查','initial_sync'),('修改前核对','before_edit'),('未读信息对齐','align_updates'),('加锁/续锁','edit_lock'),('记账','record_changes'),('图谱维护','graph_update'),('解锁','edit_unlock'),('提交准备','prepare_commit'),('提交后处理','after_commit'),('送审','dispatch')]
    bound = read_json(metadata_path(root,'jobs', report.audit_id,'input.json'), {}).get('usage_measurement_ids', [])
    all_rows = [read_json(p, {}) for p in metadata_path(root,'usage-phases').glob('*.json')]
    from archguard.phase_usage import window_total
    associated = [r for r in all_rows if r.get('id') in bound or r.get('audit_id') == report.audit_id]
    threads = {r.get('thread_id') for r in associated if r.get('role') == 'A' and r.get('thread_id')}
    totals = {t: window_total(root,t) for t in threads}
    operations = [read_json(p,{}) for p in metadata_path(root,'operation-usage').glob('*.json')]
    tool_phases = {'begin_edit':'edit_lock','renew_edit':'edit_lock','end_edit':'edit_unlock','complete_sync_operation':'record_changes','record_sync_event':'record_changes','get_sync_updates':'align_updates','sync_graph':'graph_update','update_architecture_graph':'graph_update'}
    for title, phase in phases:
        # 只引用显式绑定本提交的记录，绝不拿其他开发区间填补空白。
        rows = [r for r in all_rows if (r.get('audit_id') == report.audit_id or r.get('id') in bound) and r.get('phase') == phase]
        shared = False
        if not rows:
            parent_ids = {o.get('measurement_id') for o in operations if tool_phases.get(o.get('operation')) == phase}
            rows = [r for r in associated if r.get('id') in parent_ids]
            shared = bool(rows)
        forecast = '100–500' if phase in ('edit_lock','edit_unlock','before_edit','dispatch') else '300–3000'
        for index, r in enumerate(sorted(rows, key=lambda r:r.get('started_at',0)) or [{}], 1):
            actual = r.get('counts',{}).get('totalTokens')
            if not r:
                actual = '无阶段记录（不能据此认定未执行）'
            elif r.get('status') != 'completed':
                actual = '阶段尚未结束'
            elif actual == 0:
                actual = '待结算（无新增宿主观测）'
            elif actual is None:
                actual = '宿主计数缺失或重置'
            if shared:
                actual = str(actual) + '（共享 ' + r['phase'] + ' 区间，非独占）'
            selected = totals.get(r.get('thread_id')) or (next(iter(totals.values())) if len(totals) == 1 else {})
            total = selected.get('total')
            if total is None:
                total = r.get('after',{}).get('counts',{}).get('totalTokens')
            total = total if total is not None else selected.get('status', '未记录 A 任务身份')
            suffix = f'（区间 {index}）' if len(rows) > 1 else ''
            lines.append(f'| A · {title}{suffix} | 短摘要新增载荷规划 {forecast}；非实测 | {actual} | {total} |')
    dispatch = read_json(metadata_path(root,'jobs',report.audit_id,'dispatch.json'), {})
    thread = dispatch.get('thread_id')
    records = [read_json(p,{}) for p in metadata_path(root,'usage').glob('*.json')]
    record = next((r for r in records if r.get('thread_id') == thread), {})
    turns = [v for v in record.get('turns',{}).values() if v.get('audit_id') == report.audit_id]
    turn = turns[-1] if turns else {}
    budget = estimate(audit_packet(report))
    lines.append(f'| B · 独立裁决 | 新增证据载荷约 {budget["estimated_payload_tokens_low"]}–{budget["estimated_payload_tokens_high"]} token | {turn.get("counts",{}).get("totalTokens") or "待结算/未知"} | {record.get("latest",{}).get("counts",{}).get("totalTokens", "未知")} |')
    for thread_id, observation in totals.items():
        lines.append('')
        lines.append(f'A 累计来源：任务 `{thread_id}`；观测时间（Unix 秒）：{observation.get("observed_at", "未知")}；{observation["status"]}。')
    lines += ['', '预测仅按字符数/4 至字符数估计证据文本，不含系统提示、工具、历史和输出，不是完整调用预算。A 各环节实际用量必须有对应快照；未记录、未绑定或尚未结算不能补造。未执行步骤由 A 根据执行记录注明“不适用”。', '',
              '累计是宿主当前窗口计数，包含历史上下文与业务开发；缓存输入已包含在输入中，不重复相加。', '',
              '日志：`.ide_audit/operation-usage/`；阶段：`.ide_audit/usage-phases/`。']
    return '\n'.join(lines) + '\n'


def save_report(root, audit_id):
    """结果排版失败只提示，不使已回收裁决被重复派发。"""
    import warnings
    from archguard.runtime import get_result
    from archguard.storage import atomic_text
    try:
        verdict = read_json(metadata_path(root, 'verdicts', audit_id + '.json'))
        if verdict:
            atomic_text(metadata_path(root, 'reports', audit_id + '.md'), render(root, get_result(root, audit_id), verdict))
    except Exception as exc:
        warnings.warn(f'人读报告保存失败：{type(exc).__name__}，裁决仍已保留', RuntimeWarning)


def refresh_a_window(root, audit_id):
    from archguard.phase_usage import window_total
    bound = read_json(metadata_path(root,'jobs',audit_id,'input.json'),{}).get('usage_measurement_ids',[])
    threads = {r.get('thread_id') for p in metadata_path(root,'usage-phases').glob('*.json')
               if (r := read_json(p,{})).get('role') == 'A' and (r.get('id') in bound or r.get('audit_id') == audit_id)}
    for thread_id in threads - {None}:
        window_total(root, thread_id, refresh=True)


def delivery_status(root, audit_id):
    from archguard.runtime import _key
    identifier = _key(audit_id)
    state = read_json(metadata_path(root,'jobs',identifier,'dispatch.json'),{})
    path = metadata_path(root,'reports',identifier+'.md')
    return {'audit_id':identifier, 'audit_status':state.get('status','unknown'),
            'thread_id':state.get('thread_id'), 'report_path':str(path), 'report_exists':path.exists(),
            'chat_report_present':state.get('chat_report_present',False),
            'report_delivery_status':'requires_b_panel' if path.exists() else 'report_not_ready',
            'action':'用 open_in_codex 将此文件打开到 thread_id 指定的 B 面板；仅裁决完成不能宣称完整交付，禁止为排版重发审计'}
