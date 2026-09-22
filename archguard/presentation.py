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
    analysis_state = '检查完成' if report.analysis_status == 'complete' else '检查材料不完整，不能确认全部通过'
    lines = [f'# IDE_Audit 审计报告', '', f'提交：`{report.commit_hash}`', '',
             '## 一、审计一：插件客观检查', '',
             '### 1. 代码与账本对比', '',
             '**结论：' + ('代码与账本核对一致。' if ledger.get('is_consistent') is True else '代码与账本核对不一致，具体差异如下。' if ledger.get('is_consistent') is False else '缺少核验结果，无法判断。') + '**', '',
             f'- 固定范围：父提交 `{report.base_commit}` → 本提交；{len(files)} 个变更文件。',
             f'- 需求：{len(report.prompts)} 条；封存账本：{len(report.ledger_events)} 条事件。',
             f'- 代码与账本是否一致：{consistency}；实际修改但账本未列出的文件 {len(ledger.get("undeclared_files", []))} 个，账本列出但本次提交没有净变化的文件 {len(ledger.get("phantom_files", []))} 个，修改行范围不符 {len(ledger.get("line_deviations", []))} 项。先创建后删除的文件需结合操作记录判断，不能直接认定虚报。',
             f'- 证据状态：{analysis_state}；诊断 {len(report.diagnostics)} 项。', '',
             '## 二、审计二：B 对照需求与实现', '', '**结论：' + verdict['verdict'] + '。** ' + verdict['reason'], '',
             '### 1. 文件修改是否符合需求', '',
             '| 文件 | 用户需求依据 | 实际修改与判断 | 与需求相关 |', '|---|---|---|---|']
    fact_rows = ['', '| 文件 | 实际增删 | 账本事件 | 行级检查 |', '|---|---|---|---|']
    for path, file in files.items():
        events = [e for e in report.ledger_events if any(f.get('file') == path for f in e.get('scope',{}).get('files_changed', []))]
        deviations = [d for d in ledger.get('line_deviations', []) if d.get('file') == path]
        detail = '；'.join(f'{"新增" if d.get("side") == "new" else "删除"}行未申报：{d.get("undeclared_lines", [])}' for d in deviations) or ('没有该文件的账本记录，无法核对修改行范围' if not events else '未列出行范围差异；须结合上方整体检查结果' if ledger else '缺少检查结果')
        fact_rows.append('| ' + ' | '.join(cell(v) for v in (path, f'+{file.get("additions",0)} / -{file.get("deletions",0)}', ', '.join(e.get('version','未知') for e in events) or '无文件申报', detail)) + ' |')
    split = lines.index('## 二、审计二：B 对照需求与实现')
    lines[split:split] = fact_rows + ['', '### 2. 架构变化检查', '', '**结论：本项只确认客观变化，不判定是否越权；是否符合需求见审计二。**', '',
        f'- 图谱中记录的组成项：新增 {len(graph.get("nodes_added", []))} 个，删除 {len(graph.get("nodes_removed", []))} 个；依赖关系：新增 {len(graph.get("edges_added", []))} 条，删除 {len(graph.get("edges_removed", []))} 条。',
        f'- 自动规则提示 {len(report.architecture_signals)} 项，需要结合实际代码进一步判断。规则命中、文件增删或数量相同，都不能单独证明业务架构是否变化。',
        '- 插件在这里记录客观变化；这些变化是否符合用户要求，由下方审计二判断。', '']
    for f in verdict['files']:
        lines.append('| ' + ' | '.join(cell(v) for v in (f['path'], f['requirement_evidence'], f['reason'], '是' if f['related'] else '否')) + ' |')
    lines += ['', '### 2. 架构变化是否符合需求', '', verdict['architecture_review'], '',
              '### 3. 代码账本是否如实记录', '', verdict['ledger_review'], '',
              '## 三、最终审计结论', '', '**' + verdict['verdict'] + '**：' + verdict['reason'], '',
              '裁决来自 B；流程记账缺项与业务代码越权分别理解。未获证据支持的环节不宣称通过。', '',
              '**整改与复核**：' + ('按以上具体差异完善后续 A 申报，保留本提交原始封存证据；不得回填篡改以制造通过。' if verdict['verdict'] == '不合理' else '本次范围内无需因本裁决整改；证据覆盖限制仍保留。'), '',
              '## 四、Token 实际用量', '',
              '| 环节 | 本次实际 token | 窗口累计 token |', '|---|---|---|']
    phases = [('接入/增量检查','initial_sync'),('修改前核对','before_edit'),('未读信息对齐','align_updates'),('加锁/续锁','edit_lock'),('记账','record_changes'),('图谱维护','graph_update'),('解锁','edit_unlock'),('提交准备','prepare_commit'),('提交后处理','after_commit'),('送审','dispatch')]
    bound = read_json(metadata_path(root,'jobs', report.audit_id,'input.json'), {}).get('usage_measurement_ids', [])
    all_rows = [read_json(p, {}) for p in metadata_path(root,'usage-phases').glob('*.json')]
    from archguard.phase_usage import window_total
    associated = [r for r in all_rows if r.get('id') in bound or r.get('audit_id') == report.audit_id]
    threads = {r.get('thread_id') for r in associated if r.get('role') == 'A' and r.get('thread_id')}
    totals = {t: window_total(root,t) for t in threads}
    operations = [read_json(p,{}) for p in metadata_path(root,'operation-usage').glob('*.json')]
    tool_phases = {'begin_edit':'edit_lock','renew_edit':'edit_lock','end_edit':'edit_unlock','complete_sync_operation':'record_changes','record_sync_event':'record_changes','get_sync_updates':'align_updates','sync_graph':'graph_update','update_architecture_graph':'graph_update','patch_architecture_graph':'graph_update'}
    for title, phase in phases:
        # 只引用显式绑定本提交的记录，绝不拿其他开发区间填补空白。
        rows = [r for r in all_rows if (r.get('audit_id') == report.audit_id or r.get('id') in bound) and r.get('phase') == phase]
        shared = False
        if not rows:
            parent_ids = {o.get('measurement_id') for o in operations if tool_phases.get(o.get('operation')) == phase}
            rows = [r for r in associated if r.get('id') in parent_ids]
            shared = bool(rows)
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
            lines.append(f'| A · {title}{suffix} | {actual} | {total} |')
    dispatch = read_json(metadata_path(root,'jobs',report.audit_id,'dispatch.json'), {})
    thread = dispatch.get('thread_id')
    records = [read_json(p,{}) for p in metadata_path(root,'usage').glob('*.json')]
    record = next((r for r in records if r.get('thread_id') == thread), {})
    turns = [v for v in record.get('turns',{}).values() if v.get('audit_id') == report.audit_id]
    turn = turns[-1] if turns else {}
    lines.append(f'| B · 独立裁决 | {turn.get("counts",{}).get("totalTokens") or "待结算/未知"} | {record.get("latest",{}).get("counts",{}).get("totalTokens", "未知")} |')
    counts = turn.get('counts', {})
    lines += ['', '### B 输入与输出实际用量', '', '| 项目 | token |', '|---|---:|']
    for label, key in [('输入合计','inputTokens'),('其中缓存输入','cachedInputTokens'),('输出合计','outputTokens'),('其中推理输出','reasoningOutputTokens'),('输入与输出总计','totalTokens')]:
        value = counts.get(key)
        lines.append(f'| {label} | {value if value is not None else "未记录"} |')
    lines += ['', '缓存输入已包含在输入中，推理输出已包含在输出中，不重复加总。各次调用的实测明细未随本记录保存时，不按文字长度猜测或分摊。']
    for thread_id, observation in totals.items():
        lines.append('')
        lines.append(f'A 累计来源：任务 `{thread_id}`；观测时间（Unix 秒）：{observation.get("observed_at", "未知")}；{observation["status"]}。')
    lines += ['', '实际用量必须有对应记录；没有记录、尚未结算或计数缺失时说明原因，不补造数字。', '',
              '窗口累计包含该窗口历史操作，不能当作本次审计用量。', '',
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
